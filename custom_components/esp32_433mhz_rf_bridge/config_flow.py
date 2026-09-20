"""Config flow for ESP32 433 MHz RF Bridge."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .const import (
    CONF_FIRST_CHANNEL,
    CONF_HARJU_SEND_SERVICE,
    CONF_LEGACY_ENTRY_ID,
    CONF_RECEIVE_ENTITY,
    CONF_SEND_SERVICE,
    CONF_TRANSMIT_SERVICE,
    CONF_TRANSMITTER_ID,
    DEFAULT_FIRST_CHANNEL,
    DEFAULT_HARJU_SEND_SERVICE,
    DEFAULT_NAME,
    DEFAULT_RECEIVE_ENTITY,
    DEFAULT_SEND_SERVICE,
    DEFAULT_TRANSMIT_SERVICE,
    DEFAULT_TRANSMITTER_ID,
    DOMAIN,
    LEGACY_DOMAIN,
)
from .protocol import ProtocolError, normalize_transmitter_id


class ESP32RFBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ESP32 433 MHz RF Bridge."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""

        return ESP32RFBridgeOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""

        legacy_entries = self.hass.config_entries.async_entries(LEGACY_DOMAIN)
        if user_input is None and legacy_entries:
            self._legacy_entry = legacy_entries[0]
            return await self.async_step_migrate()

        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_input(user_input)

            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        defaults = {
            CONF_NAME: DEFAULT_NAME,
            CONF_TRANSMIT_SERVICE: DEFAULT_TRANSMIT_SERVICE,
            CONF_TRANSMITTER_ID: DEFAULT_TRANSMITTER_ID,
            CONF_FIRST_CHANNEL: DEFAULT_FIRST_CHANNEL,
        }

        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema(
                defaults,
                send_service_options=_service_options(
                    self.hass, defaults[CONF_TRANSMIT_SERVICE]
                ),
            ),
            errors=errors,
        )

    async def async_step_migrate(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm a one-time migration from the legacy integration domain."""

        legacy_entry = getattr(self, "_legacy_entry", None)
        if legacy_entry is None:
            legacy_entries = self.hass.config_entries.async_entries(LEGACY_DOMAIN)
            if not legacy_entries:
                return self.async_abort(reason="legacy_not_found")
            legacy_entry = legacy_entries[0]

        if user_input is not None:
            if not user_input["confirm"]:
                return self.async_abort(reason="migration_cancelled")
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=DEFAULT_NAME,
                data={
                    **legacy_entry.data,
                    CONF_TRANSMIT_SERVICE: DEFAULT_TRANSMIT_SERVICE,
                    CONF_LEGACY_ENTRY_ID: legacy_entry.entry_id,
                },
            )

        return self.async_show_form(
            step_id="migrate",
            data_schema=vol.Schema({vol.Required("confirm", default=True): bool}),
            description_placeholders={"legacy_title": legacy_entry.title},
        )


class ESP32RFBridgeOptionsFlow(config_entries.OptionsFlow):
    """Handle options for ESP32 433 MHz RF Bridge."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""

        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""

        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_input(user_input)
            if not errors:
                hidden_legacy_values = {
                    key: self._current_value(key, default)
                    for key, default in (
                        (CONF_SEND_SERVICE, DEFAULT_SEND_SERVICE),
                        (CONF_HARJU_SEND_SERVICE, DEFAULT_HARJU_SEND_SERVICE),
                        (CONF_RECEIVE_ENTITY, DEFAULT_RECEIVE_ENTITY),
                    )
                }
                return self.async_create_entry(
                    title="", data={**hidden_legacy_values, **user_input}
                )

        defaults = {
            CONF_TRANSMIT_SERVICE: self._current_value(
                CONF_TRANSMIT_SERVICE, DEFAULT_TRANSMIT_SERVICE
            ),
            CONF_TRANSMITTER_ID: self._current_value(
                CONF_TRANSMITTER_ID, DEFAULT_TRANSMITTER_ID
            ),
            CONF_FIRST_CHANNEL: self._current_value(
                CONF_FIRST_CHANNEL, DEFAULT_FIRST_CHANNEL
            ),
        }

        return self.async_show_form(
            step_id="init",
            data_schema=_data_schema(
                defaults,
                include_name=False,
                send_service_options=_service_options(
                    self.hass,
                    defaults[CONF_TRANSMIT_SERVICE],
                ),
            ),
            errors=errors,
        )

    def _current_value(self, key: str, default: Any) -> Any:
        """Return current option or config value."""

        return self._config_entry.options.get(
            key, self._config_entry.data.get(key, default)
        )


def _data_schema(
    defaults: dict[str, Any],
    *,
    include_name: bool = True,
    send_service_options: list[str] | None = None,
) -> vol.Schema:
    """Build the setup/options schema."""

    schema: dict[Any, Any] = {}
    if include_name:
        schema[vol.Required(CONF_NAME, default=defaults[CONF_NAME])] = cv.string
    schema[
        vol.Required(
            CONF_TRANSMIT_SERVICE, default=defaults[CONF_TRANSMIT_SERVICE]
        )
    ] = (
        selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=send_service_options or [defaults[CONF_TRANSMIT_SERVICE]],
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
                sort=True,
            )
        )
    )
    schema[
        vol.Required(CONF_TRANSMITTER_ID, default=defaults[CONF_TRANSMITTER_ID])
    ] = cv.string
    schema[vol.Required(CONF_FIRST_CHANNEL, default=defaults[CONF_FIRST_CHANNEL])] = (
        vol.All(vol.Coerce(int), vol.Range(min=1))
    )
    return vol.Schema(schema)


def _service_options(hass: Any, *current: str) -> list[str]:
    """Return known Home Assistant services for the send action picker."""

    services = hass.services.async_services()
    options = {
        f"{domain}.{service}"
        for domain, domain_services in services.items()
        for service in domain_services
    }
    options.update(current)
    options.add(DEFAULT_TRANSMIT_SERVICE)
    options.add(DEFAULT_SEND_SERVICE)
    options.add(DEFAULT_HARJU_SEND_SERVICE)
    return sorted(options)


def _validate_input(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate setup/options input."""

    errors: dict[str, str] = {}

    try:
        normalize_transmitter_id(user_input[CONF_TRANSMITTER_ID])
    except ProtocolError:
        errors[CONF_TRANSMITTER_ID] = "invalid_transmitter_id"

    if "." not in user_input[CONF_TRANSMIT_SERVICE]:
        errors[CONF_TRANSMIT_SERVICE] = "invalid_service"

    return errors
