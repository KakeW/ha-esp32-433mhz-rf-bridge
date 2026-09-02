"""Tests for the one-time legacy-domain migration."""

from __future__ import annotations

import asyncio
from enum import Enum
import importlib.util
from pathlib import Path
import sys
import types


ROOT = Path(__file__).parents[1]
PACKAGE = "custom_components.esp32_433mhz_rf_bridge"


class ConfigEntryState(Enum):
    """Minimal config entry state stub."""

    LOADED = "loaded"
    NOT_LOADED = "not_loaded"


class FakeStore:
    """In-memory replacement for Home Assistant storage."""

    values: dict[str, dict] = {}

    def __class_getitem__(cls, _item):
        return cls

    def __init__(self, _hass, _version, key):
        self.key = key

    async def async_load(self):
        return self.values.get(self.key)

    async def async_save(self, data):
        self.values[self.key] = data


class FakeDeviceRegistry:
    """Record device migration calls."""

    def __init__(self, devices):
        self.devices = devices
        self.updates = []

    def async_update_device(self, device_id, **changes):
        self.updates.append((device_id, changes))


class FakeEntityRegistry:
    """Record entity migration calls."""

    def __init__(self, entities):
        self.entities = entities
        self.updates = []

    def async_update_entity_platform(self, entity_id, platform, **changes):
        self.updates.append((entity_id, platform, changes))


class FakeConfigEntries:
    """Minimal config entry manager used by the migration."""

    def __init__(self, legacy_entry, new_entry):
        self.entries = {
            legacy_entry.entry_id: legacy_entry,
            new_entry.entry_id: new_entry,
        }
        self.unloaded = []
        self.removed = []

    def async_get_entry(self, entry_id):
        return self.entries.get(entry_id)

    async def async_unload(self, entry_id):
        self.unloaded.append(entry_id)
        self.entries[entry_id].state = ConfigEntryState.NOT_LOADED
        return True

    def async_update_entry(self, entry, **changes):
        for key, value in changes.items():
            setattr(entry, key, value)

    async def async_remove(self, entry_id):
        self.removed.append(entry_id)
        self.entries.pop(entry_id)
        return {"require_restart": False}


def _load_migration_module():
    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    storage = types.ModuleType("homeassistant.helpers.storage")

    config_entries.ConfigEntry = object
    config_entries.ConfigEntryState = ConfigEntryState
    core.HomeAssistant = object
    storage.Store = FakeStore
    helpers.device_registry = device_registry
    helpers.entity_registry = entity_registry

    modules = {
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.helpers.storage": storage,
    }
    sys.modules.update(modules)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType(PACKAGE)
    component = ROOT / "custom_components" / "esp32_433mhz_rf_bridge"
    package.__path__ = [str(component)]
    sys.modules["custom_components"] = custom_components
    sys.modules[PACKAGE] = package

    const_spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.const", component / "const.py"
    )
    const = importlib.util.module_from_spec(const_spec)
    sys.modules[f"{PACKAGE}.const"] = const
    const_spec.loader.exec_module(const)

    migration_spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.migration", component / "migration.py"
    )
    migration = importlib.util.module_from_spec(migration_spec)
    sys.modules[f"{PACKAGE}.migration"] = migration
    migration_spec.loader.exec_module(migration)
    return const, migration, device_registry, entity_registry


const, migration, device_registry_module, entity_registry_module = (
    _load_migration_module()
)


def test_domain_values_are_migrated_without_changing_entity_id() -> None:
    """Storage, registries and config options move to the new integration."""

    FakeStore.values = {
        const.LEGACY_STORAGE_KEY: {
            "switches": [{"id": "record-1", "name": "Living room"}]
        }
    }
    legacy_entry = types.SimpleNamespace(
        entry_id="legacy-entry",
        domain=const.LEGACY_DOMAIN,
        title="ESP32 valo-ohjaus",
        data={"send_service": "esphome.valojen_ohjaus_rf_send"},
        options={"receive_entity": "text_sensor.last_rf_code"},
        state=ConfigEntryState.LOADED,
    )
    new_entry = types.SimpleNamespace(
        entry_id="new-entry",
        domain=const.DOMAIN,
        title="ESP32 433 MHz RF Bridge",
        data={const.CONF_LEGACY_ENTRY_ID: legacy_entry.entry_id},
        options={},
    )
    device = types.SimpleNamespace(
        id="device-1",
        identifiers={(const.LEGACY_DOMAIN, "record-1"), ("esphome", "radio")},
    )
    entity = types.SimpleNamespace(
        entity_id="switch.living_room",
        unique_id=f"{const.LEGACY_DOMAIN}_record-1",
        device_id=device.id,
    )
    device_registry = FakeDeviceRegistry([device])
    entity_registry = FakeEntityRegistry([entity])
    device_registry_module.async_get = lambda _hass: device_registry
    device_registry_module.async_entries_for_config_entry = (
        lambda registry, _entry_id: registry.devices
    )
    entity_registry_module.async_get = lambda _hass: entity_registry
    entity_registry_module.async_entries_for_config_entry = (
        lambda registry, _entry_id: registry.entities
    )

    config_entries = FakeConfigEntries(legacy_entry, new_entry)
    hass = types.SimpleNamespace(config_entries=config_entries)
    result = asyncio.run(
        migration.async_migrate_legacy_installation(hass, new_entry)
    )

    assert result.switches == 1
    assert FakeStore.values[const.STORAGE_KEY] == FakeStore.values[
        const.LEGACY_STORAGE_KEY
    ]
    assert config_entries.unloaded == [legacy_entry.entry_id]
    assert config_entries.removed == [legacy_entry.entry_id]
    assert const.CONF_LEGACY_ENTRY_ID not in new_entry.data
    assert new_entry.options["receive_entity"] == "text_sensor.last_rf_code"

    device_id, device_changes = device_registry.updates[0]
    assert device_id == "device-1"
    assert device_changes["new_config_entry_id"] == new_entry.entry_id
    assert (const.DOMAIN, "record-1") in device_changes["new_identifiers"]
    assert ("esphome", "radio") in device_changes["new_identifiers"]

    entity_id, platform, entity_changes = entity_registry.updates[0]
    assert entity_id == "switch.living_room"
    assert platform == const.DOMAIN
    assert entity_changes["new_config_entry_id"] == new_entry.entry_id
    assert entity_changes["new_unique_id"] == f"{const.DOMAIN}_record-1"
    assert entity_changes["new_device_id"] == "device-1"


if __name__ == "__main__":
    test_domain_values_are_migrated_without_changing_entity_id()
    print("migration assertions passed")
