# custom_components/quartierfuchs/binary_sensor.py
"""Diagnose-Sensor für den Verbindungsstatus zu Quartierfuchs."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import QuartierfuchsConfigEntry
from .const import DOMAIN, KONF_PORTAL_URL, SIGNAL_VERBINDUNG

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    eintrag: QuartierfuchsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Legt den Verbindungssensor an."""
    async_add_entities([QuartierfuchsVerbindungsSensor(eintrag)])


class QuartierfuchsVerbindungsSensor(BinarySensorEntity):
    """Zeigt an, ob die Verbindung zum Quartierfuchs-Broker besteht."""

    _attr_has_entity_name = True
    _attr_translation_key = "verbindung"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, eintrag: QuartierfuchsConfigEntry) -> None:
        """Initialisiert den Sensor."""
        self._eintrag = eintrag
        self._attr_unique_id = f"{eintrag.entry_id}_verbindung"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, eintrag.entry_id)},
            name="Quartierfuchs",
            manufacturer="Quartierfuchs",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=eintrag.data[KONF_PORTAL_URL],
        )

    @property
    def is_on(self) -> bool:
        """Gibt an, ob die Verbindung besteht."""
        return self._eintrag.runtime_data.verbunden

    async def async_added_to_hass(self) -> None:
        """Abonniert Änderungen des Verbindungsstatus."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_VERBINDUNG.format(self._eintrag.entry_id),
                self.async_write_ha_state,
            )
        )
