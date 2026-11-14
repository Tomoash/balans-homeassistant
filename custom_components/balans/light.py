"""Dimmer / RGBW / analog outputs as lights."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN, ATTR_RGBW_COLOR, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BalansCoordinator, BalansEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: BalansCoordinator = entry.runtime_data
    ents: list[LightEntity] = [BalansLight(coord, i) for i, o in enumerate(coord.data.get("outputs", []))
                               if isinstance(o, dict) and o.get("kind") in ("dimmer", "rgbw")]
    dali = coord.data.get("dali") or {}
    ents += [DaliGroupLight(coord, g["g"]) for g in dali.get("groups", []) if isinstance(g, dict) and g.get("used") and "g" in g]
    add(ents)


class BalansLight(BalansEntity, LightEntity):
    def __init__(self, coord: BalansCoordinator, i: int) -> None:
        super().__init__(coord, f"out{i}")
        self._i = i
        o = coord.data["outputs"][i]
        self._rgbw = o.get("kind") == "rgbw"
        if o.get("name"):
            self._attr_name = o["name"]                 # the name given in the switch web UI
        else:
            self._attr_translation_key = "output"
            self._attr_translation_placeholders = {"index": str(i + 1)}
        self._attr_color_mode = ColorMode.RGBW if self._rgbw else ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {self._attr_color_mode}

    @property
    def _o(self) -> dict:
        outs = self.coordinator.data.get("outputs", [])
        return outs[self._i] if self._i < len(outs) else {}

    @property
    def is_on(self) -> bool:
        return bool(self._o.get("on"))

    @property
    def brightness(self) -> int:
        return max(1, round((self._o.get("level") or 1000) * 255 / 1000))

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        c = self._o.get("rgbw")
        return tuple(c) if self._rgbw and c else None

    async def async_turn_on(self, **kw: Any) -> None:
        body: dict[str, Any] = {"on": True}
        if ATTR_BRIGHTNESS in kw:
            body["level"] = max(1, round(kw[ATTR_BRIGHTNESS] * 1000 / 255))
        if ATTR_RGBW_COLOR in kw and self._rgbw:
            body["rgbw"] = list(kw[ATTR_RGBW_COLOR])
        await self.coordinator.api.out(self._i, **body)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kw: Any) -> None:
        await self.coordinator.api.out(self._i, on=False)
        await self.coordinator.async_request_refresh()


class DaliGroupLight(BalansEntity, LightEntity):
    """03F DALI group (brightness; colour temperature when a DT8 device is in the group)."""

    def __init__(self, coord: BalansCoordinator, g: int) -> None:
        super().__init__(coord, f"dali{g}")
        self._g = g
        names = (coord.cfg.get("dali") or {}).get("groups") or []
        if g < len(names) and names[g]:
            self._attr_name = names[g]
        else:
            self._attr_translation_key = "dali_group"
            self._attr_translation_placeholders = {"index": str(g + 1)}
        dt8 = bool(self._grp.get("dt8"))
        self._attr_color_mode = ColorMode.COLOR_TEMP if dt8 else ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {self._attr_color_mode}
        if dt8:
            self._attr_min_color_temp_kelvin, self._attr_max_color_temp_kelvin = 2200, 6500

    @property
    def _grp(self) -> dict:
        gs = (self.coordinator.data.get("dali") or {}).get("groups", [])
        return gs[self._g] if self._g < len(gs) else {}

    @property
    def available(self) -> bool:
        d = self.coordinator.data.get("dali") or {}
        return super().available and bool(d.get("bus_ok"))

    @property
    def is_on(self) -> bool:
        return bool(self._grp.get("on"))

    @property
    def brightness(self) -> int:
        return max(1, round((self._grp.get("level") or 1000) * 255 / 1000))

    @property
    def color_temp_kelvin(self) -> int | None:
        return self._grp.get("kelvin") or None

    async def async_turn_on(self, **kw: Any) -> None:
        body: dict[str, Any] = {"on": True}
        if ATTR_BRIGHTNESS in kw:
            body["level"] = max(1, round(kw[ATTR_BRIGHTNESS] * 1000 / 255))
        if ATTR_COLOR_TEMP_KELVIN in kw:
            body["kelvin"] = int(kw[ATTR_COLOR_TEMP_KELVIN])
        await self.coordinator.api.dali_set(self._g, **body)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kw: Any) -> None:
        await self.coordinator.api.dali_set(self._g, on=False)
        await self.coordinator.async_request_refresh()
