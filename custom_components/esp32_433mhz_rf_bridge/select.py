"""Select platform for ESP32 433 MHz RF Bridge."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROTOCOL_LABELS
from .hub import ESP32RFBridgeHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ESP32RFBridgeHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESP32 433 MHz RF Bridge select entities."""

    async_add_entities([NewSwitchProtocolSelect(entry.runtime_data)])


class NewSwitchProtocolSelect(SelectEntity):
    """Select the RF protocol used for the next created switch."""

    _attr_has_entity_name = False
    _attr_name = "New outlet type"
    _attr_options = list(PROTOCOL_LABELS.values())

    def __init__(self, hub: ESP32RFBridgeHub) -> None:
        """Initialize the select entity."""

        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_{hub.entry.entry_id}_new_switch_protocol"
        self._attr_device_info = hub.device_info
        self._unsub_update: Callable[[], None] | None = None

    @property
    def current_option(self) -> str:
        """Return the selected protocol label."""

        return PROTOCOL_LABELS[self.hub.new_switch_protocol]

    async def async_select_option(self, option: str) -> None:
        """Set the protocol used for the next created switch."""

        for protocol, label in PROTOCOL_LABELS.items():
            if label == option:
                self.hub.set_new_switch_protocol(protocol)
                self.async_write_ha_state()
                return

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
