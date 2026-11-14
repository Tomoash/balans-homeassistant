"""Named scenes of the switch as buttons; v0.2.0: identify + restart (only with the administrator token)."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BalansCoordinator, BalansEntity
from .api import BalansError


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: BalansCoordinator = entry.runtime_data
    add(BalansScene(coord, n, s["name"]) for n, s in enumerate(coord.cfg.get("scenes") or [])
        if isinstance(s, dict) and s.get("name"))
    if coord.api.has_admin:
        add([BalansIdentify(coord), BalansRestart(coord)])


class BalansScene(BalansEntity, ButtonEntity):
    def __init__(self, coord: BalansCoordinator, n: int, name: str) -> None:
        super().__init__(coord, f"scene{n}")
        self._n = n
        self._attr_translation_key = "scene"
        self._attr_translation_placeholders = {"name": name}

    async def async_press(self) -> None:
        await self.coordinator.api.scene(self._n)
        await self.coordinator.async_request_refresh()


class BalansIdentify(BalansEntity, ButtonEntity):
    """blink all LEDs + haptic / beep for 3 s: find the switch on the wall"""
    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "identify"

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "identify")

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.identify()
        except BalansError as e:
            raise HomeAssistantError(str(e)) from e


class BalansRestart(BalansEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "restart"

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "restart")

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.reboot()
        except BalansError as e:
            raise HomeAssistantError(str(e)) from e
        self.coordinator.force_info()
