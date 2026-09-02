"""One-time migration from the legacy ESP32 light control domain."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_LEGACY_ENTRY_ID,
    DOMAIN,
    LEGACY_DOMAIN,
    LEGACY_STORAGE_KEY,
    STORAGE_KEY,
    STORAGE_VERSION,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MigrationResult:
    """Summary of a completed legacy migration."""

    switches: int
    entities: int
    devices: int


async def async_migrate_legacy_installation(
    hass: HomeAssistant, new_entry: ConfigEntry
) -> MigrationResult | None:
    """Move a legacy installation to the new domain before platforms load."""

    legacy_entry_id = new_entry.data.get(CONF_LEGACY_ENTRY_ID)
    if not legacy_entry_id:
        return None

    legacy_entry = hass.config_entries.async_get_entry(str(legacy_entry_id))
    if legacy_entry is None or legacy_entry.domain != LEGACY_DOMAIN:
        raise ValueError("Legacy ESP32 light control config entry was not found")

    if legacy_entry.state is ConfigEntryState.LOADED:
        if not await hass.config_entries.async_unload(legacy_entry.entry_id):
            raise RuntimeError("Legacy ESP32 light control entry could not be unloaded")

    legacy_store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION, LEGACY_STORAGE_KEY
    )
    legacy_data = await legacy_store.async_load() or {}
    switch_count = len(legacy_data.get("switches", []))

    new_store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    existing_data = await new_store.async_load() or {}
    if existing_data.get("switches") and existing_data != legacy_data:
        raise RuntimeError("New RF Bridge storage already contains different switches")
    await new_store.async_save(legacy_data)

    device_registry = dr.async_get(hass)
    legacy_devices = list(
        dr.async_entries_for_config_entry(device_registry, legacy_entry.entry_id)
    )
    for device in legacy_devices:
        identifiers = migrated_identifiers(device.identifiers)
        device_registry.async_update_device(
            device.id,
            new_config_entry_id=new_entry.entry_id,
            new_identifiers=identifiers,
        )

    entity_registry = er.async_get(hass)
    legacy_entities = list(
        er.async_entries_for_config_entry(entity_registry, legacy_entry.entry_id)
    )
    for entity in legacy_entities:
        unique_id = migrated_unique_id(entity.unique_id)
        entity_registry.async_update_entity_platform(
            entity.entity_id,
            DOMAIN,
            new_config_entry_id=new_entry.entry_id,
            new_unique_id=unique_id,
            new_device_id=entity.device_id,
        )

    options = {**legacy_entry.options, **new_entry.options}
    data = {
        **legacy_entry.data,
        **new_entry.data,
    }
    data.pop(CONF_LEGACY_ENTRY_ID, None)
    remove_result = await hass.config_entries.async_remove(legacy_entry.entry_id)
    if remove_result.get("require_restart"):
        LOGGER.warning("Home Assistant requested a restart after legacy entry removal")

    hass.config_entries.async_update_entry(
        new_entry,
        data=data,
        options=options,
        title=new_entry.title,
    )

    result = MigrationResult(
        switches=switch_count,
        entities=len(legacy_entities),
        devices=len(legacy_devices),
    )
    LOGGER.info(
        "Migrated legacy RF bridge: %s switches, %s entities, %s devices",
        result.switches,
        result.entities,
        result.devices,
    )
    return result


def migrated_identifiers(
    identifiers: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Replace only legacy-domain device identifiers."""

    return {
        (DOMAIN if domain == LEGACY_DOMAIN else domain, identifier)
        for domain, identifier in identifiers
    }


def migrated_unique_id(unique_id: str) -> str:
    """Replace the legacy domain prefix in an entity unique ID."""

    prefix = f"{LEGACY_DOMAIN}_"
    if unique_id.startswith(prefix):
        return f"{DOMAIN}_{unique_id.removeprefix(prefix)}"
    return unique_id
