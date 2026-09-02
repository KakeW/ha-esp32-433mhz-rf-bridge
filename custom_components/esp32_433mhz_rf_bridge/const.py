"""Constants for the ESP32 433 MHz RF Bridge integration."""

from __future__ import annotations

DOMAIN = "esp32_433mhz_rf_bridge"
LEGACY_DOMAIN = "esp32_valo_ohjaus"

PLATFORMS = ["switch", "button", "text", "select", "sensor"]

CONF_SEND_SERVICE = "send_service"
CONF_RECEIVE_ENTITY = "receive_entity"
CONF_TRANSMITTER_ID = "transmitter_id"
CONF_FIRST_CHANNEL = "first_channel"
CONF_LEGACY_ENTRY_ID = "legacy_entry_id"

DEFAULT_NAME = "ESP32 433 MHz RF Bridge"
DEFAULT_SEND_SERVICE = "esphome.valojen_ohjaus_rf_send"
DEFAULT_HARJU_SEND_SERVICE = "esphome.valojen_ohjaus_rf_send_harju"
DEFAULT_RECEIVE_ENTITY = "text_sensor.valojen_ohjaus_viimeisin_rf_koodi"
DEFAULT_TRANSMITTER_ID = "563DC0"
DEFAULT_FIRST_CHANNEL = 4
DEFAULT_SWITCH_PROTOCOL = "nexa"

SERVICE_CREATE_SWITCH = "create_switch"
SERVICE_LEARN_NEXT = "learn_next"
SERVICE_RECEIVE_CODE = "receive_code"
SERVICE_SEND_CODE = "send_code"

ATTR_NAME = "name"
ATTR_SWITCH_ID = "switch_id"
ATTR_ENTITY_ID = "entity_id"
ATTR_CODE = "code"
ATTR_KIND = "kind"
ATTR_ON_CODE = "on_code"
ATTR_OFF_CODE = "off_code"
ATTR_CHANNEL = "channel"
ATTR_PROTOCOL = "protocol"

LEARN_ON = "on"
LEARN_OFF = "off"
PROTOCOL_NEXA = "nexa"
PROTOCOL_HARJU = "harju"
PROTOCOL_LABELS = {
    PROTOCOL_NEXA: "Nexa",
    PROTOCOL_HARJU: "Harju",
}
EVENT_RF_RECEIVED = f"{DOMAIN}_received"

STORAGE_KEY = f"{DOMAIN}.switches"
LEGACY_STORAGE_KEY = f"{LEGACY_DOMAIN}.switches"
STORAGE_VERSION = 1
