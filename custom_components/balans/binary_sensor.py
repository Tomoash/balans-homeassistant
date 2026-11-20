"""v0.2.0: "Problem" - on while the switch reports any active fault code (E01..), the codes and texts as attributes.

v0.7.2: "Heater supply" (firmware 2.43.1+, 03I-R rev A1 behind a ripple-control (HDO) contactor): on while the heating
supply of the module is live, from heat_meter.feed / feed_state of /api/status. Display only: the switch keeps
regulating on its own; with feed_state "meter_missing" (meter silent over 24 h, fault E23) the state is unknown.
v0.7.3: firmware 2.43.2+ reports feed_state only with the setting "Heating behind HDO" (config heat.hdo) on; with it
off the entity is unavailable. The setting itself is changed only in the switch (admin), never from Home Assistant."""
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
    m = coord.data.get("heat_meter")
    if (isinstance(m, dict) and ("feed" in m or "feed_state" in m)) or hdo_setting(coord) is True:                 # v0.7.2
        ents.append(BalansHeaterSupply(coord))
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


FEED_STATES = ("on", "off", "meter_missing")


def hdo_setting(coord: BalansCoordinator) -> bool | None:
    """v0.7.3: config heat.hdo of firmware 2.43.2+ ("Heating behind HDO"); None = older firmware without the setting"""
    h = coord.cfg.get("heat") if isinstance(coord.cfg, dict) else None
    v = h.get("hdo") if isinstance(h, dict) else None
    return v if isinstance(v, bool) else None


class BalansHeaterSupply(BalansEntity, BinarySensorEntity):
    """v0.7.2: is the heating supply of 03I-R live (off while the HDO contactor has switched the heating off)."""
    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_translation_key = "heater_supply"

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "heater_supply")

    def _m(self) -> dict:
        m = self.coordinator.data.get("heat_meter")
        return m if isinstance(m, dict) else {}

    @property
    def available(self) -> bool:
        # 2.43.1: whenever heat_meter is reported; 2.43.2+: only with "Heating behind HDO" on (then feed_state is sent)
        return super().available and bool(self._m()) and hdo_setting(self.coordinator) is not False \
            and ("feed_state" in self._m() or "feed" in self._m())

    @property
    def is_on(self) -> bool | None:
        m = self._m()
        st = m.get("feed_state")
        if st == "meter_missing":
            return None
        if st in ("on", "off"):
            return st == "on"
        f = m.get("feed")
        return f if isinstance(f, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self._m().get("feed_state")
        return {"feed_state": st if st in FEED_STATES else None, "hdo_setting": hdo_setting(self.coordinator)}
