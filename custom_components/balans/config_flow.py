"""Config flow: manual (host + token) or found by zeroconf (mDNS TXT vendor=Benesl Automation)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import BalansApi, BalansAuthError, BalansError
from .const import CONF_ADMIN_TOKEN, CONF_FINGERPRINT, CONF_HTTPS, CONF_TOKEN, DOMAIN

CONF_REMOVE_ADMIN = "remove_admin_token"
_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))     # masked in the UI


class BalansConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._name: str | None = None

    async def _validate(self, data: dict) -> dict:
        api = BalansApi(async_get_clientsession(self.hass, verify_ssl=False), data[CONF_HOST], data[CONF_TOKEN],
                        data.get(CONF_HTTPS, False), data.get(CONF_FINGERPRINT),
                        (data.get(CONF_ADMIN_TOKEN) or "").strip() or None)
        info = await api.info()
        await api.status()                               # the token must be accepted for reading
        if api.has_admin:
            await api.admin_check()                      # v0.2.0: and the optional one for administration
        return info

    def _schema(self, host: str | None) -> vol.Schema:
        return vol.Schema({
            vol.Required(CONF_HOST, default=host or ""): str,
            vol.Required(CONF_TOKEN): str,
            vol.Optional(CONF_HTTPS, default=False): bool,
            vol.Optional(CONF_FINGERPRINT, default=""): str,
            vol.Optional(CONF_ADMIN_TOKEN, default=""): _SECRET,
        })

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BalansOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await self._validate(user_input)
            except BalansAuthError:
                errors["base"] = "invalid_auth"
            except BalansError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.get("id"))
                if self.source == SOURCE_REAUTH:           # v0.7.0: a new token replaces the rejected one
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=user_input)
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                return self.async_create_entry(title=info.get("name", "BALANS"), data=user_input)
        return self.async_show_form(step_id="user", data_schema=self._schema(self._host), errors=errors,
                                    description_placeholders={"name": self._name or ""})

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        props = discovery_info.properties
        if props.get("vendor") != "Benesl Automation" or not props.get("id"):
            return self.async_abort(reason="not_balans")
        await self.async_set_unique_id(props["id"])
        self._host = discovery_info.host
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        self._name = discovery_info.name.split("._http")[0]
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._host = entry_data.get(CONF_HOST)
        return await self.async_step_user()


class BalansOptionsFlow(OptionsFlow):
    """v0.2.0: add / change / remove the administrator token of an existing entry. The stored token is never shown again
    (the field starts empty and is masked): empty = keep the current one, the checkbox removes it."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        d = self.config_entry.data
        cur = (self.config_entry.options.get(CONF_ADMIN_TOKEN, d.get(CONF_ADMIN_TOKEN, "")) or "").strip()
        if user_input is not None:
            tok = (user_input.get(CONF_ADMIN_TOKEN) or "").strip()
            if user_input.get(CONF_REMOVE_ADMIN):
                tok = ""
            elif not tok:
                tok = cur                       # empty field: keep the current token
            try:
                if tok and tok != cur:
                    api = BalansApi(async_get_clientsession(self.hass, verify_ssl=False), d[CONF_HOST], d[CONF_TOKEN],
                                    d.get(CONF_HTTPS, False), d.get(CONF_FINGERPRINT), tok)
                    await api.admin_check()
            except BalansAuthError:
                errors["base"] = "invalid_admin"
            except BalansError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(data={CONF_ADMIN_TOKEN: tok})
        return self.async_show_form(step_id="init", errors=errors,
                                    description_placeholders={"state": "set" if cur else "-"},
                                    data_schema=vol.Schema({vol.Optional(CONF_ADMIN_TOKEN, default=""): _SECRET,
                                                            vol.Optional(CONF_REMOVE_ADMIN, default=False): bool}))
