# custom_components/quartierfuchs/verbindung.py
"""MQTT-Verbindung zum Quartierfuchs-Broker.

Veröffentlicht die Zustände der freigegebenen Entitäten und führt Befehle des
Portals aus, sofern Entität, Dienst und Parameter freigegeben sind.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, __version__ as HA_VERSION
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
    split_entity_id,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.json import json_dumps
from homeassistant.util.json import json_loads

from .const import (
    ANMELDUNG_ABGELEHNT_CODES,
    DIENST_TIMEOUT,
    ERLAUBTE_DIENSTE,
    KONF_BENUTZERNAME,
    KONF_BROKER_HOST,
    KONF_BROKER_PORT,
    KONF_BROKER_TLS,
    KONF_PASSWORT,
    KONF_TOPIC_BASIS,
    LISTE_VERZOEGERUNG,
    MAX_NACHRICHTENGROESSE,
    MQTT_KEEPALIVE,
    MQTT_QOS,
    OPT_ENTITAETEN,
    PROTOKOLL_VERSION,
    SIGNAL_VERBINDUNG,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    TOPIC_ANTWORT,
    TOPIC_BEFEHL,
    TOPIC_ENTITAETEN,
    TOPIC_STATUS,
    TOPIC_ZUSTAND,
    UNTERSTUETZTE_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)


def freigaben_filtern(entitaeten: list[str]) -> set[str]:
    """Behält nur Entitäten aus unterstützten Domains."""
    ergebnis: set[str] = set()
    for entity_id in entitaeten:
        try:
            domain, _ = split_entity_id(entity_id)
        except ValueError:
            continue
        if domain in UNTERSTUETZTE_DOMAINS:
            ergebnis.add(entity_id)
    return ergebnis


class QuartierfuchsVerbindung:
    """Hält die Verbindung zum Broker und vermittelt zwischen Portal und Home Assistant."""

    def __init__(
        self, hass: HomeAssistant, eintrag: ConfigEntry, integrations_version: str
    ) -> None:
        """Initialisiert die Verbindung (ohne sie aufzubauen)."""
        self.hass = hass
        self._eintrag = eintrag
        self._integrations_version = integrations_version
        self._basis: str = eintrag.data[KONF_TOPIC_BASIS]
        self._freigaben: set[str] = freigaben_filtern(
            eintrag.options.get(OPT_ENTITAETEN, [])
        )
        self._client: mqtt.Client | None = None
        self._abmeldung_zustaende: CALLBACK_TYPE | None = None
        self._abmeldungen_register: list[CALLBACK_TYPE] = []
        self._geplante_liste: CALLBACK_TYPE | None = None
        self._verbunden = False
        self._gestoppt = False
        self._reauth_ausgeloest = False
        self._signal = SIGNAL_VERBINDUNG.format(eintrag.entry_id)

    @property
    def verbunden(self) -> bool:
        """Gibt an, ob aktuell eine Verbindung zum Broker besteht."""
        return self._verbunden

    def _topic(self, *teile: str) -> str:
        """Setzt ein Topic unterhalb der Topic-Basis dieser Kopplung zusammen."""
        return "/".join((self._basis, *teile))

    # ------------------------------------------------------------------
    # Start und Stopp
    # ------------------------------------------------------------------

    async def async_starten(self) -> None:
        """Baut den MQTT-Client auf und startet die Verbindung im Hintergrund."""
        self._client = await self.hass.async_add_executor_job(self._client_erzeugen)
        self._zustaende_abonnieren()
        self._register_beobachten()
        await self.hass.async_add_executor_job(self._client_verbinden, self._client)

    async def async_stoppen(self) -> None:
        """Meldet sich ordnungsgemäß ab und beendet die Verbindung."""
        self._gestoppt = True
        if self._abmeldung_zustaende is not None:
            self._abmeldung_zustaende()
            self._abmeldung_zustaende = None
        for abmelden in self._abmeldungen_register:
            abmelden()
        self._abmeldungen_register = []
        if self._geplante_liste is not None:
            self._geplante_liste()
            self._geplante_liste = None

        client = self._client
        self._client = None
        if client is not None:
            await self.hass.async_add_executor_job(
                self._client_beenden, client, self._verbunden
            )
        self._status_setzen(False)

    def _client_erzeugen(self) -> mqtt.Client:
        """Erzeugt den MQTT-Client (läuft im Executor, da TLS-Kontext blockierend lädt)."""
        daten = self._eintrag.data
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"ha-{daten[KONF_BENUTZERNAME]}",
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(daten[KONF_BENUTZERNAME], daten[KONF_PASSWORT])
        if daten.get(KONF_BROKER_TLS, True):
            client.tls_set_context(ssl.create_default_context())
        client.will_set(
            self._topic(TOPIC_STATUS), STATUS_OFFLINE, qos=MQTT_QOS, retain=True
        )
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        client.on_connect = self._bei_verbindung
        client.on_disconnect = self._bei_trennung
        client.on_message = self._bei_nachricht
        return client

    def _client_verbinden(self, client: mqtt.Client) -> None:
        """Startet den Verbindungsaufbau; paho verbindet bei Abbruch selbst neu."""
        daten = self._eintrag.data
        client.connect_async(
            daten[KONF_BROKER_HOST], int(daten[KONF_BROKER_PORT]), keepalive=MQTT_KEEPALIVE
        )
        client.loop_start()

    def _client_beenden(self, client: mqtt.Client, offline_melden: bool) -> None:
        """Meldet optional 'offline' und beendet Client und Netzwerk-Thread."""
        if offline_melden:
            info = client.publish(
                self._topic(TOPIC_STATUS), STATUS_OFFLINE, qos=MQTT_QOS, retain=True
            )
            try:
                info.wait_for_publish(timeout=3)
            except (ValueError, RuntimeError):
                _LOGGER.debug("Offline-Meldung konnte nicht bestätigt werden")
        client.disconnect()
        client.loop_stop()

    # ------------------------------------------------------------------
    # Callbacks aus dem paho-Thread (nur an die Event-Loop weiterreichen)
    # ------------------------------------------------------------------

    def _bei_verbindung(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if reason_code.is_failure:
            code = getattr(reason_code, "value", reason_code)
            _LOGGER.warning("Verbindung zum Quartierfuchs-Broker abgelehnt: %s", reason_code)
            if code in ANMELDUNG_ABGELEHNT_CODES:
                self.hass.loop.call_soon_threadsafe(self._anmeldung_abgelehnt)
            return
        client.subscribe(self._topic(TOPIC_BEFEHL), qos=MQTT_QOS)
        self.hass.loop.call_soon_threadsafe(self._verbindung_hergestellt)

    def _bei_trennung(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        self.hass.loop.call_soon_threadsafe(self._verbindung_verloren)

    def _bei_nachricht(
        self, client: mqtt.Client, userdata: Any, nachricht: mqtt.MQTTMessage
    ) -> None:
        if nachricht.topic != self._topic(TOPIC_BEFEHL):
            return
        if len(nachricht.payload) > MAX_NACHRICHTENGROESSE:
            _LOGGER.warning("Befehl verworfen: Nachricht zu groß")
            return
        self.hass.create_task(
            self._async_befehl_verarbeiten(bytes(nachricht.payload)),
            "quartierfuchs_befehl",
        )

    # ------------------------------------------------------------------
    # Verbindungsstatus (Event-Loop)
    # ------------------------------------------------------------------

    @callback
    def _status_setzen(self, verbunden: bool) -> None:
        if self._verbunden == verbunden:
            return
        self._verbunden = verbunden
        async_dispatcher_send(self.hass, self._signal)

    @callback
    def _verbindung_hergestellt(self) -> None:
        if self._gestoppt:
            return
        _LOGGER.info("Mit dem Quartierfuchs-Broker verbunden")
        self._status_setzen(True)
        self._alles_veroeffentlichen()

    @callback
    def _verbindung_verloren(self) -> None:
        if self._verbunden and not self._gestoppt:
            _LOGGER.info("Verbindung zum Quartierfuchs-Broker getrennt, verbinde neu")
        self._status_setzen(False)

    @callback
    def _anmeldung_abgelehnt(self) -> None:
        if self._gestoppt or self._reauth_ausgeloest:
            return
        self._reauth_ausgeloest = True
        _LOGGER.error(
            "Der Quartierfuchs-Broker lehnt die Anmeldung ab; die Kopplung muss erneuert werden"
        )
        self.hass.async_create_task(self._async_nach_ablehnung())

    async def _async_nach_ablehnung(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await self.hass.async_add_executor_job(self._client_beenden, client, False)
        self._status_setzen(False)
        self._eintrag.async_start_reauth(self.hass)

    # ------------------------------------------------------------------
    # Freigaben und Zustände
    # ------------------------------------------------------------------

    @callback
    def _zustaende_abonnieren(self) -> None:
        if self._abmeldung_zustaende is not None:
            self._abmeldung_zustaende()
            self._abmeldung_zustaende = None
        if self._freigaben:
            self._abmeldung_zustaende = async_track_state_change_event(
                self.hass, sorted(self._freigaben), self._zustand_geaendert
            )

    async def async_freigaben_aktualisieren(self, entitaeten: list[str]) -> None:
        """Übernimmt geänderte Freigaben aus den Optionen."""
        neu = freigaben_filtern(entitaeten)
        entfernt = self._freigaben - neu
        self._freigaben = neu
        self._zustaende_abonnieren()
        for entity_id in sorted(entfernt):
            # Leere Retained-Nachricht löscht den zuletzt gemeldeten Zustand beim Broker
            self._senden(self._topic(TOPIC_ZUSTAND, entity_id), None, retain=True)
        self._alles_veroeffentlichen()

    @callback
    def _zustand_geaendert(self, ereignis: Event[EventStateChangedData]) -> None:
        self._zustand_veroeffentlichen(ereignis.data["entity_id"], ereignis.data["new_state"])
        # Taucht eine Entität erst nach dem Start auf (z. B. Zigbee-Thermostate),
        # stimmen Name und Bereich in der zuletzt gesendeten Liste ggf. nicht.
        if ereignis.data["old_state"] is None:
            self._liste_spaeter_senden()

    @callback
    def _register_beobachten(self) -> None:
        """Sendet die Geräteliste neu, wenn Entitäten, Geräte oder Bereiche umbenannt werden."""
        for abmelden in self._abmeldungen_register:
            abmelden()

        @callback
        def _entitaet_geaendert(ereignis: Event) -> None:
            daten = ereignis.data
            if daten.get("entity_id") in self._freigaben or daten.get("old_entity_id") in self._freigaben:
                self._liste_spaeter_senden()

        @callback
        def _sonstiges_geaendert(_ereignis: Event) -> None:
            if self._freigaben:
                self._liste_spaeter_senden()

        self._abmeldungen_register = [
            self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _entitaet_geaendert),
            self.hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _sonstiges_geaendert),
            self.hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, _sonstiges_geaendert),
        ]

    @callback
    def _liste_spaeter_senden(self) -> None:
        """Fasst viele Änderungen kurz hintereinander zu einer Geräteliste zusammen."""
        if self._geplante_liste is not None or self._gestoppt:
            return

        @callback
        def _jetzt(_zeit: Any) -> None:
            self._geplante_liste = None
            if self._verbunden and not self._gestoppt:
                self._entitaeten_veroeffentlichen()

        self._geplante_liste = async_call_later(self.hass, LISTE_VERZOEGERUNG, _jetzt)

    @callback
    def _alles_veroeffentlichen(self) -> None:
        if not self._verbunden:
            return
        self._senden(self._topic(TOPIC_STATUS), STATUS_ONLINE, retain=True)
        self._entitaeten_veroeffentlichen()
        for entity_id in sorted(self._freigaben):
            self._zustand_veroeffentlichen(entity_id, self.hass.states.get(entity_id))

    @callback
    def _entitaeten_veroeffentlichen(self) -> None:
        if self._geplante_liste is not None:
            self._geplante_liste()
            self._geplante_liste = None
        entitaets_register = er.async_get(self.hass)
        geraete_register = dr.async_get(self.hass)
        bereichs_register = ar.async_get(self.hass)

        liste: list[dict[str, Any]] = []
        for entity_id in sorted(self._freigaben):
            domain, _ = split_entity_id(entity_id)
            zustand = self.hass.states.get(entity_id)
            attribute = zustand.attributes if zustand is not None else {}

            bereich_id: str | None = None
            geraet_name: str | None = None
            if (registereintrag := entitaets_register.async_get(entity_id)) is not None:
                bereich_id = registereintrag.area_id
                if registereintrag.device_id and (
                    geraet := geraete_register.async_get(registereintrag.device_id)
                ):
                    geraet_name = geraet.name_by_user or geraet.name
                    bereich_id = bereich_id or geraet.area_id
            bereich = bereichs_register.async_get_area(bereich_id) if bereich_id else None

            liste.append(
                {
                    "entity_id": entity_id,
                    "domain": domain,
                    "name": anzeigename(entity_id, zustand, registereintrag, geraet_name),
                    "bereich": bereich.name if bereich is not None else None,
                    "geraet": geraet_name,
                    "device_class": attribute.get("device_class"),
                    "einheit": attribute.get("unit_of_measurement"),
                    "dienste": {
                        dienst: sorted(parameter)
                        for dienst, parameter in ERLAUBTE_DIENSTE.get(domain, {}).items()
                    },
                }
            )

        self._senden(
            self._topic(TOPIC_ENTITAETEN),
            json_dumps(
                {
                    "protokoll_version": PROTOKOLL_VERSION,
                    "integration_version": self._integrations_version,
                    "ha_version": HA_VERSION,
                    "entitaeten": liste,
                }
            ),
            retain=True,
        )

    @callback
    def _zustand_veroeffentlichen(self, entity_id: str, zustand: State | None) -> None:
        if entity_id not in self._freigaben:
            return
        if zustand is None:
            nutzlast: dict[str, Any] = {"entity_id": entity_id, "state": None}
        else:
            nutzlast = {
                "entity_id": entity_id,
                "state": zustand.state,
                "attribute": dict(zustand.attributes),
                "zuletzt_geaendert": zustand.last_changed.isoformat(),
                "zuletzt_aktualisiert": zustand.last_updated.isoformat(),
            }
        try:
            text = json_dumps(nutzlast)
        except TypeError:
            _LOGGER.debug("Attribute von %s nicht serialisierbar, sende ohne Attribute", entity_id)
            nutzlast.pop("attribute", None)
            text = json_dumps(nutzlast)
        self._senden(self._topic(TOPIC_ZUSTAND, entity_id), text, retain=True)

    @callback
    def _senden(self, topic: str, nutzlast: str | None, retain: bool = False) -> None:
        if self._client is None or not self._verbunden:
            return
        self._client.publish(topic, nutzlast, qos=MQTT_QOS, retain=retain)

    # ------------------------------------------------------------------
    # Befehle des Portals
    # ------------------------------------------------------------------

    async def _async_befehl_verarbeiten(self, roh: bytes) -> None:
        if self._gestoppt:
            return
        try:
            befehl = json_loads(roh)
        except ValueError:
            _LOGGER.warning("Befehl verworfen: kein gültiges JSON")
            return
        if not isinstance(befehl, dict):
            _LOGGER.warning("Befehl verworfen: kein JSON-Objekt")
            return

        befehl_id = befehl.get("id")
        typ = befehl.get("typ")

        if typ == "ping":
            self._antworten(befehl_id, True)
            return
        if typ == "synchronisieren":
            self._alles_veroeffentlichen()
            self._antworten(befehl_id, True)
            return
        if typ != "dienst":
            self._antworten(befehl_id, False, "unbekannter_typ")
            return

        domain = befehl.get("domain")
        dienst = befehl.get("service")
        entity_id = befehl.get("entity_id")
        daten = befehl.get("data") or {}

        if not isinstance(entity_id, str) or entity_id not in self._freigaben:
            self._antworten(befehl_id, False, "entitaet_nicht_freigegeben")
            return
        if not isinstance(domain, str) or split_entity_id(entity_id)[0] != domain:
            self._antworten(befehl_id, False, "domain_passt_nicht")
            return
        erlaubte_parameter = (
            ERLAUBTE_DIENSTE.get(domain, {}).get(dienst) if isinstance(dienst, str) else None
        )
        if erlaubte_parameter is None:
            self._antworten(befehl_id, False, "dienst_nicht_erlaubt")
            return
        if not isinstance(daten, dict):
            self._antworten(befehl_id, False, "ungueltige_daten")
            return
        if unzulaessig := set(daten) - erlaubte_parameter:
            self._antworten(
                befehl_id, False, "unzulaessige_parameter: " + ", ".join(sorted(unzulaessig))
            )
            return

        _LOGGER.debug("Führe %s.%s für %s aus", domain, dienst, entity_id)
        try:
            async with asyncio.timeout(DIENST_TIMEOUT):
                await self.hass.services.async_call(
                    domain, dienst, {**daten, ATTR_ENTITY_ID: entity_id}, blocking=True
                )
        except TimeoutError:
            self._antworten(befehl_id, False, "zeitueberschreitung")
        except (HomeAssistantError, vol.Invalid) as fehler:
            self._antworten(befehl_id, False, str(fehler) or type(fehler).__name__)
        else:
            self._antworten(befehl_id, True)

    @callback
    def _antworten(self, befehl_id: Any, erfolg: bool, fehler: str | None = None) -> None:
        if befehl_id is None:
            return
        self._senden(
            self._topic(TOPIC_ANTWORT),
            json_dumps({"id": befehl_id, "erfolg": erfolg, "fehler": fehler}),
        )


def anzeigename(
    entity_id: str,
    zustand: State | None,
    registereintrag: er.RegistryEntry | None,
    geraet_name: str | None,
) -> str:
    """Name, wie Home Assistant ihn anzeigt – auch, wenn noch kein Zustand vorliegt.

    1. friendly_name des aktuellen Zustands,
    2. sonst aus dem Register: eigener Name (name) bzw. der der Integration
       (original_name); bei has_entity_name mit vorangestelltem Gerätenamen,
    3. sonst die entity_id.
    """
    if zustand is not None and (name := zustand.attributes.get("friendly_name")):
        return str(name)
    if registereintrag is not None:
        eigener = registereintrag.name or registereintrag.original_name
        if registereintrag.has_entity_name and geraet_name:
            return f"{geraet_name} {eigener}" if eigener else geraet_name
        if eigener:
            return str(eigener)
    return entity_id
