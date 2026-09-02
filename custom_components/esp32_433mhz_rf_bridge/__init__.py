"""ESP32 433 MHz RF Bridge custom integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_CHANNEL,
    ATTR_CODE,
    ATTR_ENTITY_ID,
    ATTR_KIND,
    ATTR_NAME,
    ATTR_OFF_CODE,
    ATTR_ON_CODE,
    ATTR_PROTOCOL,
    ATTR_SWITCH_ID,
    DOMAIN,
    LEARN_OFF,
    LEARN_ON,
    PLATFORMS,
    PROTOCOL_HARJU,
    PROTOCOL_NEXA,
    SERVICE_CREATE_SWITCH,
    SERVICE_LEARN_NEXT,
    SERVICE_RECEIVE_CODE,
    SERVICE_SEND_CODE,
)
from .hub import ESP32RFBridgeHub
from .migration import async_migrate_legacy_installation
from .protocol import ProtocolError

LOGGER = logging.getLogger(__name__)

ESP32RFBridgeConfigEntry = ConfigEntry[ESP32RFBridgeHub]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up ESP32 433 MHz RF Bridge services."""

    async def async_create_switch(call: ServiceCall) -> None:
        hub = _get_first_loaded_hub(hass)
        try:
            await hub.async_create_switch(
                call.data[ATTR_NAME],
                channel=call.data.get(ATTR_CHANNEL),
                on_code=call.data.get(ATTR_ON_CODE),
                off_code=call.data.get(ATTR_OFF_CODE),
                protocol=call.data.get(ATTR_PROTOCOL, PROTOCOL_NEXA),
            )
        except ProtocolError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_learn_next(call: ServiceCall) -> None:
        hub = _get_first_loaded_hub(hass)
        record_id = await _resolve_record_id(hub, call.data)
        await hub.async_arm_learning(record_id, call.data[ATTR_KIND])

    async def async_receive_code(call: ServiceCall) -> None:
        hub = _get_first_loaded_hub(hass)
        try:
            await hub.async_receive_code(call.data[ATTR_CODE])
        except ProtocolError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_send_code(call: ServiceCall) -> None:
        hub = _get_first_loaded_hub(hass)
        try:
            await hub.async_send_code(call.data[ATTR_CODE])
        except ProtocolError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_SWITCH,
        async_create_switch,
        schema=vol.Schema(
            {
                vol.Required(ATTR_NAME): cv.string,
                vol.Optional(ATTR_CHANNEL): vol.All(vol.Coerce(int), vol.Range(min=1)),
                vol.Optional(ATTR_ON_CODE): cv.string,
                vol.Optional(ATTR_OFF_CODE): cv.string,
                vol.Optional(ATTR_PROTOCOL, default=PROTOCOL_NEXA): vol.In(
                    [PROTOCOL_NEXA, PROTOCOL_HARJU]
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LEARN_NEXT,
        async_learn_next,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_SWITCH_ID): cv.string,
                vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
                vol.Required(ATTR_KIND): vol.In([LEARN_ON, LEARN_OFF]),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RECEIVE_CODE,
        async_receive_code,
        schema=vol.Schema({vol.Required(ATTR_CODE): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_CODE,
        async_send_code,
        schema=vol.Schema({vol.Required(ATTR_CODE): cv.string}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ESP32RFBridgeConfigEntry) -> bool:
    """Set up ESP32 433 MHz RF Bridge from a config entry."""

    await async_migrate_legacy_installation(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    hub = ESP32RFBridgeHub(hass, entry)
    await hub.async_setup()
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ESP32RFBridgeConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    if unload_ok:
        await entry.runtime_data.async_unload()
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: ESP32RFBridgeConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow HA to remove switch devices no longer present in integration storage."""

    hub = entry.runtime_data
    return not any(
        identifier_domain == DOMAIN and identifier_id in hub.store.records
        for identifier_domain, identifier_id in device_entry.identifiers
    )


async def _async_reload_entry(
    hass: HomeAssistant, entry: ESP32RFBridgeConfigEntry
) -> None:
    """Reload the integration when options change."""

    await hass.config_entries.async_reload(entry.entry_id)


def _get_first_loaded_hub(hass: HomeAssistant) -> ESP32RFBridgeHub:
    """Return the first loaded hub instance."""

    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("ESP32 433 MHz RF Bridge is not configured")
    return entries[0].runtime_data


async def _resolve_record_id(hub: ESP32RFBridgeHub, data: dict) -> str:
    """Resolve a stored switch id from service data."""

    if ATTR_SWITCH_ID in data:
        record_id = data[ATTR_SWITCH_ID]
        if record_id in hub.store.records:
            return record_id
        raise HomeAssistantError("Unknown RF switch id")

    if ATTR_ENTITY_ID in data:
        entity_id = data[ATTR_ENTITY_ID]
        registry = er.async_get(hub.hass)
        entry = registry.async_get(entity_id)
        if entry and entry.unique_id and entry.unique_id.startswith(f"{DOMAIN}_"):
            record_id = entry.unique_id.removeprefix(f"{DOMAIN}_")
            if record_id in hub.store.records:
                return record_id
        raise HomeAssistantError("Unknown RF switch entity")

    raise HomeAssistantError("switch_id or entity_id is required")
