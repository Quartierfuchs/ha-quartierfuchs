# custom_components/quartierfuchs/const.py
"""Konstanten der Quartierfuchs-Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "quartierfuchs"

# Version des Nachrichtenprotokolls zwischen Integration und Portal (siehe PROTOKOLL.md)
PROTOKOLL_VERSION: Final = 1

# Portal
STANDARD_PORTAL_URL: Final = "https://portal.haffquartier.de"
KOPPLUNGS_PFAD: Final = "/api/homeassistant/kopplung"
KOPPLUNGS_TIMEOUT: Final = 20

# Schlüssel im Konfigurationseintrag (data)
KONF_PORTAL_URL: Final = "portal_url"
KONF_CODE: Final = "code"
KONF_BROKER_HOST: Final = "broker_host"
KONF_BROKER_PORT: Final = "broker_port"
KONF_BROKER_TLS: Final = "broker_tls"
KONF_BENUTZERNAME: Final = "benutzername"
KONF_PASSWORT: Final = "passwort"
KONF_TOPIC_BASIS: Final = "topic_basis"
KONF_VERMIETER_NAME: Final = "vermieter_name"

# Schlüssel in den Optionen (options)
OPT_ENTITAETEN: Final = "entitaeten"

# Domains, deren Entitäten freigegeben werden können
UNTERSTUETZTE_DOMAINS: Final = (
    "climate",
    "light",
    "switch",
    "sensor",
    "binary_sensor",
)

# Dienste, die das Portal aufrufen darf, mit den jeweils erlaubten Parametern.
# Alles, was hier nicht steht, wird abgelehnt. entity_id setzt die Integration selbst.
ERLAUBTE_DIENSTE: Final[dict[str, dict[str, frozenset[str]]]] = {
    "climate": {
        "set_temperature": frozenset(
            {"temperature", "target_temp_low", "target_temp_high", "hvac_mode"}
        ),
        "set_hvac_mode": frozenset({"hvac_mode"}),
        "set_preset_mode": frozenset({"preset_mode"}),
        "turn_on": frozenset(),
        "turn_off": frozenset(),
    },
    "light": {
        "turn_on": frozenset(
            {
                "brightness",
                "brightness_pct",
                "color_temp_kelvin",
                "rgb_color",
                "hs_color",
                "transition",
            }
        ),
        "turn_off": frozenset({"transition"}),
        "toggle": frozenset(),
    },
    "switch": {
        "turn_on": frozenset(),
        "turn_off": frozenset(),
        "toggle": frozenset(),
    },
}

# MQTT
TOPIC_STATUS: Final = "status"
TOPIC_ENTITAETEN: Final = "entitaeten"
TOPIC_ZUSTAND: Final = "zustand"
TOPIC_BEFEHL: Final = "befehl"
TOPIC_ANTWORT: Final = "antwort"

STATUS_ONLINE: Final = "online"
STATUS_OFFLINE: Final = "offline"

MQTT_KEEPALIVE: Final = 60
MQTT_QOS: Final = 1
MAX_NACHRICHTENGROESSE: Final = 65536
DIENST_TIMEOUT: Final = 15

# Rückgabecodes beim Verbindungsaufbau, die eine abgelehnte Anmeldung bedeuten
# (MQTT 3.1.1: 4/5, von paho als 134/135 gemeldet)
ANMELDUNG_ABGELEHNT_CODES: Final = frozenset({4, 5, 134, 135})

# Dispatcher-Signal für Änderungen des Verbindungsstatus (Platzhalter: entry_id)
SIGNAL_VERBINDUNG: Final = "quartierfuchs_verbindung_{}"
