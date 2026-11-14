"""v0.7.0: "Level bar" - the value the LED level bar of the chevron panel (01B) shows, set from Home Assistant.

Firmware 2.40.0+, POST /api/slider. Display only: the switch never switches or dims anything because of it. Typical use:
the chevron slider controls a light somewhere else in Home Assistant and the bar should show that light's brightness.
Only while the bar is not tied to a local output of the switch (slider.source "slider"); when it shows a local output,
set that output instead and this entity is unavailable."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BalansCoordinator, BalansEntity
from .api import BalansError
from .const import bar_percent, fw_at_least


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: BalansCoordinator = entry.runtime_data
    s = coord.data.get("slider")
    if isinstance(s, dict) and "value" in s and fw_at_least(coord.info, "2.40.0"):
        add([BalansLevelBar(coord)])


class BalansLevelBar(BalansEntity, NumberEntity):
    _attr_translation_key = "level_bar"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "level_bar")

    def _s(self) -> dict:
        s = self.coordinator.data.get("slider")
        return s if isinstance(s, dict) else {}

    @property
    def available(self) -> bool:
        return super().available and self._s().get("source", "slider") == "slider"

    @property
    def native_value(self) -> int | None:
        return bar_percent(self._s().get("value"))

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.api.slider(max(0, min(100, round(value))))
        except BalansError as e:
            if "slider_has_local_output" in str(e):
                raise HomeAssistantError("BALANS: the level bar shows a local output of the switch; "
                                         "set that output instead") from e
            raise HomeAssistantError(f"BALANS level bar: {e}") from e
        await self.coordinator.async_request_refresh()
