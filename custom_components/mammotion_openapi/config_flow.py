"""UI setup, options, reconfiguration and credential renewal."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import AuthenticationError, MammotionClient, MammotionError
from .const import CONF_ENABLE_PUSH, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN


class MammotionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Validate credentials using the real API before storing a config entry."""

    VERSION = 1

    async def _credentials(self, step_id: str, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        entry = None
        if step_id == "reauth_confirm":
            entry = self._get_reauth_entry()
        elif step_id == "reconfigure":
            entry = self._get_reconfigure_entry()
        if user_input:
            data = {
                CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
            }
            if not all(data.values()):
                errors["base"] = "invalid_auth"
            else:
                try:
                    client = MammotionClient(async_get_clientsession(self.hass), **data)
                    await client.mowers()
                except AuthenticationError:
                    errors["base"] = "invalid_auth"
                except MammotionError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(data[CONF_CLIENT_ID])
                    if entry:
                        self._abort_if_unique_id_mismatch()
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates=data,
                            reason="reauth_successful"
                            if step_id == "reauth_confirm"
                            else "reconfigure_successful",
                        )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title="Mammotion Open API", data=data)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CLIENT_ID, default=entry.data[CONF_CLIENT_ID] if entry else ""
                ): str,
                vol.Required(CONF_CLIENT_SECRET): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def async_step_user(self, user_input=None):
        return await self._credentials("user", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._credentials("reauth_confirm", user_input)

    async def async_step_reconfigure(self, user_input=None):
        return await self._credentials("reconfigure", user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MammotionOptionsFlow()


class MammotionOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                    vol.Required(
                        CONF_ENABLE_PUSH, default=options.get(CONF_ENABLE_PUSH, True)
                    ): bool,
                }
            ),
        )
