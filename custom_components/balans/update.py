"""v0.2.0: firmware update entity. Installed version from the switch, available version from the newest image in
<config>/balans/firmware (copied there by hand - nothing is downloaded). Installing needs the administrator token;
without it the entity only informs. The switch verifies the signature itself and rolls back if the new image fails."""
from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BalansCoordinator, BalansEntity, firmware
from .api import BalansError
from .const import DOMAIN, OTA_WAIT_S


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    add([BalansUpdate(hass.data[DOMAIN][entry.entry_id])])


class BalansUpdate(BalansEntity, UpdateEntity):
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_translation_key = "firmware"

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "firmware")
        if coord.api.has_admin:
            self._attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.info.get("fw")

    @property
    def latest_version(self) -> str | None:
        cur, latest = self.installed_version, self.coordinator.latest
        if latest and firmware.is_newer(latest["version"], cur):
            return latest["version"]
        return cur                              # nothing newer on disk: "up to date"

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        coord, latest = self.coordinator, self.coordinator.latest
        if not latest or not firmware.is_newer(latest["version"], self.installed_version):
            raise HomeAssistantError("No newer firmware file in the balans/firmware folder")
        target = latest["version"]
        try:
            image = await self.hass.async_add_executor_job(firmware.read_checked, latest["path"], target)
        except (OSError, ValueError) as e:
            raise HomeAssistantError(f"Firmware file cannot be used: {e}") from e
        self._attr_in_progress = True
        self.async_write_ha_state()
        try:
            try:
                await coord.api.ota(image)
            except BalansError as e:
                raise HomeAssistantError(f"The switch refused the firmware: {e}") from e
            await asyncio.sleep(8)
            running = None
            for _ in range(OTA_WAIT_S // 3):            # restart + the switch confirming the new image
                try:
                    running = (await coord.api.info()).get("fw")
                    break
                except BalansError:
                    await asyncio.sleep(3)
            if running is None:
                raise HomeAssistantError("The switch does not answer after the update; it returns to the previous "
                                         "version by itself within 5 minutes - check it")
            if running != target:
                raise HomeAssistantError(f"The switch runs {running} instead of {target} (image refused or rolled back)")
        finally:
            self._attr_in_progress = False
            coord.force_info()
            await coord.async_request_refresh()
