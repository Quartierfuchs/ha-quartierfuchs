# custom_components/quartierfuchs/__init__.py
"""Quartierfuchs-Integration für Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN, OPT_ENTITAETEN
from .verbindung import QuartierfuchsVerbindung

PLATTFORMEN: list[Platform] = [Platform.BINARY_SENSOR]

type QuartierfuchsConfigEntry = ConfigEntry[QuartierfuchsVerbindung]


async def async_setup_entry(hass: HomeAssistant, eintrag: QuartierfuchsConfigEntry) -> bool:
    """Richtet eine Kopplung ein und startet die Verbindung zum Broker."""
    integration = await async_get_integration(hass, DOMAIN)
    verbindung = QuartierfuchsVerbindung(hass, eintrag, str(integration.version))
    eintrag.runtime_data = verbindung

    await verbindung.async_starten()
    eintrag.async_on_unload(eintrag.add_update_listener(_async_eintrag_geaendert))

    await hass.config_entries.async_forward_entry_setups(eintrag, PLATTFORMEN)
    return True


async def _async_eintrag_geaendert(hass: HomeAssistant, eintrag: QuartierfuchsConfigEntry) -> None:
    """Übernimmt geänderte Freigaben ohne Neuaufbau der Verbindung."""
    await eintrag.runtime_data.async_freigaben_aktualisieren(
        eintrag.options.get(OPT_ENTITAETEN, [])
    )


async def async_unload_entry(hass: HomeAssistant, eintrag: QuartierfuchsConfigEntry) -> bool:
    """Entlädt eine Kopplung und meldet sich beim Broker ab."""
    entladen = await hass.config_entries.async_unload_platforms(eintrag, PLATTFORMEN)
    if entladen:
        await eintrag.runtime_data.async_stoppen()
    return entladen
