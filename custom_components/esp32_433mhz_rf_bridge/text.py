"""Text platform for ESP32 433 MHz RF Bridge."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import ESP32RFBridgeHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ESP32RFBridgeHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESP32 433 MHz RF Bridge text entities."""

    async_add_entities([NewSwitchNameText(entry.runtime_data)])


class NewSwitchNameText(TextEntity):
    """Editable name for the next created RF switch."""

    _attr_has_entity_name = False
    _attr_name = "New RF switch name"
    _attr_native_max = 80

    def __init__(self, hub: ESP32RFBridgeHub) -> None:
        """Initialize the text entity."""

        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_{hub.entry.entry_id}_new_switch_name"
        self._attr_device_info = hub.device_info
        self._unsub_update: Callable[[], None] | None = None
        if not self.hub.new_switch_name:
            self.hub.new_switch_name = self.hub.next_switch_default_name()

    @property
    def native_value(self) -> str:
        """Return the current pending switch name."""

        return self.hub.new_switch_name

    async def async_set_value(self, value: str) -> None:
        """Set the pending switch name."""

        self.hub.set_new_switch_name(value)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register update listener."""

        @callback
        def _handle_update() -> None:
            self.async_write_ha_state()

        self._unsub_update = async_dispatcher_connect(
            self.hass, self.hub.signal_control_update, _handle_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister update listener."""

        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None
