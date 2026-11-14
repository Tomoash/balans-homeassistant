"""Relay / DO outputs as switches. v0.3.0: heat-demand outputs (03I-T, 03I-R) are left out, see sensor.py and climate.py."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BalansCoordinator, BalansEntity
from .const import is_heat_device, is_heat_output


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: BalansCoordinator = entry.runtime_data
    add(BalansSwitch(coord, i) for i, o in enumerate(coord.data.get("outputs", [])) if isinstance(o, dict) and o.get("kind") == "switch" and not is_heat_device(coord.info) and not is_heat_output(coord.data, o))


class BalansSwitch(BalansEntity, SwitchEntity):
    def __init__(self, coord: BalansCoordinator, i: int) -> None:
        super().__init__(coord, f"out{i}")
        self._i = i
        name = coord.data["outputs"][i].get("name")
        if name:
            self._attr_name = name                      # the name given in the switch web UI
        else:
            self._attr_translation_key = "relay"
            self._attr_translation_placeholders = {"index": str(i + 1)}

    @property
    def is_on(self) -> bool:
        outs = self.coordinator.data.get("outputs", [])
        return bool(outs[self._i].get("on")) if self._i < len(outs) else False

    async def async_turn_on(self, **kw: Any) -> None:
        await self.coordinator.api.out(self._i, on=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kw: Any) -> None:
        await self.coordinator.api.out(self._i, on=False)
        await self.coordinator.async_request_refresh()
