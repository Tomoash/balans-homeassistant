"""v0.2.0: "Problem" - on while the switch reports any active fault code (E01..), the codes and texts as attributes."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BalansCoordinator, BalansEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: BalansCoordinator = entry.runtime_data
    ents: list[BinarySensorEntity] = [BalansProblem(coord)]
    ents += [BalansHeating(coord, z) for z, h in enumerate(coord.data.get("heat") or []) if isinstance(h, dict)]    # v0.3.0
    add(ents)


class BalansProblem(BalansEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "fault"

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "fault")

    def _faults(self) -> list[dict]:
        return [f for f in (self.coordinator.data.get("faults") or []) if isinstance(f, dict)]

    @property
    def is_on(self) -> bool:
        return bool(self._faults()) or bool(self.coordinator.data.get("safe_mode"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fs = self._faults()
        return {"codes": [f.get("code") for f in fs],
                "faults": [f"{f.get('code')} {f.get('text')}" for f in fs],
                "errors": sum(1 for f in fs if f.get("sev") == "error"),
                "safe_mode": bool(self.coordinator.data.get("safe_mode"))}


class BalansHeating(BalansEntity, BinarySensorEntity):
    """v0.3.0: heating zone of 03I-T / 03I-R: on while the safety layer of the switch really lets the zone heat."""
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coord: BalansCoordinator, z: int) -> None:
        super().__init__(coord, f"heat{z}")
        self._z = z
        self._attr_translation_key = "heating"
        self._attr_translation_placeholders = {"zone": str(z + 1)}

    def _h(self) -> dict:
        hs = self.coordinator.data.get("heat") or []
        return hs[self._z] if self._z < len(hs) and isinstance(hs[self._z], dict) else {}

    @property
    def is_on(self) -> bool:
        return bool(self._h().get("heat"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        h = self._h()
        return {"demand": bool(h.get("demand")), "reason": h.get("reason"), "fault": h.get("fault")}
