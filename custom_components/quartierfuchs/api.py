# custom_components/quartierfuchs/api.py
"""Kopplung mit dem Quartierfuchs-Portal über HTTPS."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import instance_id
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    KONF_BENUTZERNAME,
    KONF_BROKER_HOST,
    KONF_BROKER_PORT,
    KONF_BROKER_TLS,
    KONF_PASSWORT,
    KONF_TOPIC_BASIS,
    KONF_VERMIETER_NAME,
    KOPPLUNGS_PFAD,
    KOPPLUNGS_TIMEOUT,
    PROTOKOLL_VERSION,
)

PFLICHTFELDER = ("broker_host", "broker_port", "benutzername", "passwort", "topic_basis")


class KopplungsFehler(Exception):
    """Basisklasse für Fehler bei der Kopplung."""


class KopplungsCodeUngueltig(KopplungsFehler):
    """Der Code ist unbekannt, abgelaufen oder bereits verwendet."""


class PortalNichtErreichbar(KopplungsFehler):
    """Das Portal konnte nicht erreicht werden oder hat mit einem Fehler geantwortet."""


class UngueltigeAntwort(KopplungsFehler):
    """Die Antwort des Portals ist unvollständig oder fehlerhaft."""


def portal_url_normalisieren(portal_url: str) -> str:
    """Entfernt Leerzeichen und abschließende Schrägstriche."""
    return portal_url.strip().rstrip("/")


def portal_url_gueltig(portal_url: str) -> bool:
    """Prüft, ob die Portal-Adresse mit http:// oder https:// beginnt."""
    return portal_url.startswith(("https://", "http://"))


async def async_koppeln(hass: HomeAssistant, portal_url: str, code: str) -> dict[str, Any]:
    """Tauscht einen Kopplungscode beim Portal gegen die Broker-Zugangsdaten."""
    sitzung = async_get_clientsession(hass)
    url = portal_url_normalisieren(portal_url) + KOPPLUNGS_PFAD
    nutzlast = {
        "code": code.strip().upper(),
        "instanz_id": await instance_id.async_get(hass),
        "instanz_name": hass.config.location_name,
        "ha_version": HA_VERSION,
        "protokoll_version": PROTOKOLL_VERSION,
    }

    try:
        async with asyncio.timeout(KOPPLUNGS_TIMEOUT):
            async with sitzung.post(url, json=nutzlast) as antwort:
                if antwort.status in (400, 404, 409, 410):
                    raise KopplungsCodeUngueltig
                if antwort.status != 200:
                    raise PortalNichtErreichbar(f"HTTP {antwort.status}")
                daten = await antwort.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as fehler:
        raise PortalNichtErreichbar(str(fehler)) from fehler
    except ValueError as fehler:
        raise UngueltigeAntwort("Antwort ist kein gültiges JSON") from fehler

    return _antwort_pruefen(daten)


def _antwort_pruefen(daten: Any) -> dict[str, Any]:
    """Prüft die Antwort des Portals und wandelt sie in Konfigurationsdaten um."""
    if not isinstance(daten, dict) or any(feld not in daten for feld in PFLICHTFELDER):
        raise UngueltigeAntwort("Pflichtfelder fehlen")

    try:
        port = int(daten["broker_port"])
    except (TypeError, ValueError) as fehler:
        raise UngueltigeAntwort("broker_port ist keine Zahl") from fehler
    if not 1 <= port <= 65535:
        raise UngueltigeAntwort("broker_port außerhalb des gültigen Bereichs")

    topic_basis = str(daten["topic_basis"]).strip().rstrip("/")
    if not topic_basis or any(zeichen in topic_basis for zeichen in ("+", "#")):
        raise UngueltigeAntwort("topic_basis ist ungültig")

    benutzername = str(daten["benutzername"]).strip()
    passwort = str(daten["passwort"])
    broker_host = str(daten["broker_host"]).strip()
    if not benutzername or not passwort or not broker_host:
        raise UngueltigeAntwort("Zugangsdaten unvollständig")

    return {
        KONF_BROKER_HOST: broker_host,
        KONF_BROKER_PORT: port,
        KONF_BROKER_TLS: bool(daten.get("broker_tls", True)),
        KONF_BENUTZERNAME: benutzername,
        KONF_PASSWORT: passwort,
        KONF_TOPIC_BASIS: topic_basis,
        KONF_VERMIETER_NAME: str(daten.get("vermieter_name") or ""),
    }
