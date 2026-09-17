"""Config flow for Fitness Server Bridge."""
from __future__ import annotations

from homeassistant import config_entries
import voluptuous as vol

from .const import (
    CONF_ALLOWED_SERVICE_DOMAINS,
    CONF_BRIDGE_TOKEN,
    CONF_ENTITY_MIRROR_ENABLED,
    CONF_SERVER_WS_URL,
    DEFAULT_ALLOWED_SERVICE_DOMAINS,
    DEFAULT_ENTITY_MIRROR_ENABLED,
    DEFAULT_SERVER_WS_URL,
    DOMAIN,
)
from .validation import normalize_bridge_token, normalize_service_domains, normalize_ws_url


def _validated_input(user_input: dict) -> dict:
    try:
        url = normalize_ws_url(user_input[CONF_SERVER_WS_URL])
        domains = normalize_service_domains(user_input[CONF_ALLOWED_SERVICE_DOMAINS])
        token = normalize_bridge_token(user_input.get(CONF_BRIDGE_TOKEN, ""), url=url)
    except (KeyError, TypeError, ValueError) as err:
        raise vol.Invalid(str(err)) from err
    return {
        CONF_SERVER_WS_URL: url,
        CONF_BRIDGE_TOKEN: token,
        CONF_ALLOWED_SERVICE_DOMAINS: domains,
        CONF_ENTITY_MIRROR_ENABLED: bool(
            user_input.get(CONF_ENTITY_MIRROR_ENABLED, DEFAULT_ENTITY_MIRROR_ENABLED)
        ),
    }


class FitnessBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["pair", "manual"])

    async def async_step_pair(self, user_input=None):
        await self.async_set_unique_id("fitness_pairing")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Fitness Bridge · ready to connect", data={
            CONF_SERVER_WS_URL: "", CONF_BRIDGE_TOKEN: "",
            CONF_ALLOWED_SERVICE_DOMAINS: list(DEFAULT_ALLOWED_SERVICE_DOMAINS),
            CONF_ENTITY_MIRROR_ENABLED: DEFAULT_ENTITY_MIRROR_ENABLED,
        })

    async def async_step_manual(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                data = _validated_input(user_input)
            except vol.Invalid:
                errors["base"] = "invalid_config"
            else:
                await self.async_set_unique_id(data[CONF_SERVER_WS_URL].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Fitness Server", data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_SERVER_WS_URL, default=DEFAULT_SERVER_WS_URL): str,
                vol.Optional(CONF_BRIDGE_TOKEN, default=""): str,
                vol.Required(
                    CONF_ALLOWED_SERVICE_DOMAINS, default=",".join(DEFAULT_ALLOWED_SERVICE_DOMAINS)
                ): str,
                vol.Optional(
                    CONF_ENTITY_MIRROR_ENABLED, default=DEFAULT_ENTITY_MIRROR_ENABLED
                ): bool,
            }
        )
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return FitnessBridgeOptionsFlow(config_entry)


class FitnessBridgeOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry) -> None:
        self._bridge_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            try:
                domains = normalize_service_domains(user_input[CONF_ALLOWED_SERVICE_DOMAINS])
            except (KeyError, TypeError, ValueError):
                return self.async_show_form(
                    step_id="init", data_schema=self._schema(), errors={"base": "invalid_config"}
                )
            return self.async_create_entry(
                title="",
                data={
                    CONF_ALLOWED_SERVICE_DOMAINS: domains,
                    CONF_ENTITY_MIRROR_ENABLED: bool(
                        user_input.get(CONF_ENTITY_MIRROR_ENABLED, DEFAULT_ENTITY_MIRROR_ENABLED)
                    ),
                },
            )
        return self.async_show_form(step_id="init", data_schema=self._schema())

    def _schema(self):
        current = self._bridge_entry.options.get(
            CONF_ALLOWED_SERVICE_DOMAINS,
            self._bridge_entry.data.get(
                CONF_ALLOWED_SERVICE_DOMAINS, list(DEFAULT_ALLOWED_SERVICE_DOMAINS)
            ),
        )
        if not isinstance(current, list):
            current = list(DEFAULT_ALLOWED_SERVICE_DOMAINS)
        mirror_enabled = bool(
            self._bridge_entry.options.get(
                CONF_ENTITY_MIRROR_ENABLED,
                self._bridge_entry.data.get(
                    CONF_ENTITY_MIRROR_ENABLED, DEFAULT_ENTITY_MIRROR_ENABLED
                ),
            )
        )
        return vol.Schema(
            {
                vol.Required(
                    CONF_ALLOWED_SERVICE_DOMAINS,
                    default=",".join(str(value) for value in current),
                ): str,
                vol.Optional(CONF_ENTITY_MIRROR_ENABLED, default=mirror_enabled): bool,
            }
        )
