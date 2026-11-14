"""BALANS (Benešl Automation) switch - local integration without MQTT."""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed

from .api import BalansApi, BalansAuthError, BalansError
from . import firmware
from .const import (CONF_ADMIN_TOKEN, CONF_FINGERPRINT, CONF_HTTPS, CONF_TOKEN, DOMAIN, FW_DIR, INFO_INTERVAL_S, PLATFORMS,
                    SCAN_INTERVAL_S)

_LOGGER = logging.getLogger(__name__)


class BalansCoordinator(DataUpdateCoordinator[dict]):
    """Polls /api/status; /api/info and /api/config (names, scenes) every 10 min."""

    def __init__(self, hass: HomeAssistant, api: BalansApi, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"balans {entry.data[CONF_HOST]}",
                         update_interval=timedelta(seconds=SCAN_INTERVAL_S))
        self.api = api
        self.entry = entry
        self.info: dict = {}
        self.cfg: dict = {}
        self.latest: dict | None = None         # v0.2.0: newest image in <config>/balans/firmware (None = none there)
        self._info_at = 0.0

    async def _async_update_data(self) -> dict:
        try:
            if not self.info or time.monotonic() - self._info_at > INFO_INTERVAL_S:
                self.info = await self.api.info()
                self.cfg = await self.api.config()
                self.latest = await self.hass.async_add_executor_job(firmware.find_latest, self.hass.config.path(FW_DIR))
                self._info_at = time.monotonic()
            st = await self.api.status()
            if self.info.get("hw", {}).get("module") == "dali":   # 03F DALI: group states with every poll
                try:
                    st["dali"] = await self.api.dali()
                except BalansError:
                    st["dali"] = None
            return st
        except BalansAuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except BalansError as e:
            raise UpdateFailed(str(e)) from e

    def force_info(self) -> None:
        """read /api/info again with the next poll (after an update or a restart)"""
        self._info_at = 0.0

    @property
    def device_info(self) -> DeviceInfo:
        i = self.info
        return DeviceInfo(identifiers={(DOMAIN, i.get("id", self.entry.entry_id))}, name=i.get("name", "BALANS"),
                          manufacturer=i.get("vendor", "Benešl Automation"), model="BALANS " + str(i.get("hw", {}).get("panel", "")),
                          sw_version=i.get("fw"), configuration_url=f"http://{self.entry.data[CONF_HOST]}/")


class BalansEntity(CoordinatorEntity[BalansCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coord: BalansCoordinator, key: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{coord.info.get('id', coord.entry.entry_id)}_{key}"
        self._attr_device_info = coord.device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        api = BalansApi(async_get_clientsession(hass, verify_ssl=False), entry.data[CONF_HOST], entry.data[CONF_TOKEN],
                        entry.data.get(CONF_HTTPS, False), entry.data.get(CONF_FINGERPRINT),
                        (entry.options.get(CONF_ADMIN_TOKEN) or entry.data.get(CONF_ADMIN_TOKEN) or "").strip() or None)
    except BalansError as e:
        raise ConfigEntryNotReady(str(e)) from e
    coord = BalansCoordinator(hass, api, entry)
    await coord.async_config_entry_first_refresh()
    entry.runtime_data = coord
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_changed))
    return True


async def _options_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)     # the administrator token was added / removed


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
