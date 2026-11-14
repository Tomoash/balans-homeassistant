"""The thermostats of the switch as climate entities.

v0.5.0 (firmware 2.38.1+): "Thermostat", from the "climate" block of /api/status.
v0.7.0 (firmware 2.41.0+, only with the 03I-T module): "Thermostat 2" for heating zone 2, from the "climate2" block
(modes off / heat only, own target, own floor limit inside the switch).

Both write only through POST /api/thermostat (target temperature and mode). Outputs, floor limits, minimum on / off
times and the safety layer stay with the switch: these entities change the wish, never an output."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BalansCoordinator, BalansEntity
from .api import BalansError
from .const import DOMAIN, climate_action, climate_modes, has_cap

MODES = {"off": HVACMode.OFF, "heat": HVACMode.HEAT, "cool": HVACMode.COOL}
ACTIONS = {"off": HVACAction.OFF, "idle": HVACAction.IDLE, "heating": HVACAction.HEATING, "cooling": HVACAction.COOLING,
           "preheating": HVACAction.PREHEATING}
ZONE_ERRORS = {"no_zone2": "this switch has no second thermostat (03I-T module needed)",
               "mode_not_allowed": "zone 2 can only heat or be off"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: BalansCoordinator = hass.data[DOMAIN][entry.entry_id]
    ents: list[ClimateEntity] = []
    if isinstance(coord.data.get("climate"), dict) and has_cap(coord.info, "thermostat", True):
        ents.append(BalansClimate(coord, 1))
    if isinstance(coord.data.get("climate2"), dict):                  # firmware 2.41.0+ with 03I-T
        ents.append(BalansClimate(coord, 2))
    add(ents)


class BalansClimate(BalansEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 5.0                # the switch refuses anything outside 5..35, it does not clip
    _attr_max_temp = 35.0
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON
                                | ClimateEntityFeature.TURN_OFF)
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coord: BalansCoordinator, zone: int) -> None:
        # zone 1 keeps the unique id of 0.5.0 ("climate"), zone 2 uses the one of the firmware's MQTT discovery
        super().__init__(coord, "climate" if zone == 1 else "climate2")
        self._zone = zone
        self._block = "climate" if zone == 1 else "climate2"
        self._attr_translation_key = "thermostat" if zone == 1 else "thermostat2"

    def _c(self) -> dict:
        c = self.coordinator.data.get(self._block)
        return c if isinstance(c, dict) else {}

    def _modes(self) -> list[str]:
        ms = climate_modes(self._c())
        return [m for m in ms if m != "cool"] if self._zone == 2 else ms   # zone 2 never cools, whatever is reported

    @property
    def available(self) -> bool:
        # no output assigned to the thermostat: the switch would answer 409 to every command
        return super().available and bool(self._c()) and self._c().get("reason") != "no_output"

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return [MODES[m] for m in self._modes()]

    @property
    def hvac_mode(self) -> HVACMode | None:
        return MODES.get(self._c().get("mode"))

    @property
    def hvac_action(self) -> HVACAction | None:
        return ACTIONS.get(climate_action(self._c()))

    @property
    def current_temperature(self) -> float | None:
        v = self._c().get("current")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def target_temperature(self) -> float | None:
        v = self._c().get("target")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._c()
        attrs = {"reason": c.get("reason"), "target_effective": c.get("target_eff"), "preheat": bool(c.get("preheat")),
                 "valve_exercise": bool(c.get("exercise")), "zone": c.get("zone")}
        if "regulate" in c:
            attrs["regulate"] = c.get("regulate")          # "floor" or "room"
        return attrs

    async def _send(self, **kw: Any) -> None:
        try:
            await self.coordinator.api.thermostat(self._zone, **kw)
        except BalansError as e:
            msg = str(e)
            hint = next((t for k, t in ZONE_ERRORS.items() if k in msg), None)
            raise HomeAssistantError(f"BALANS thermostat {self._zone}: {hint or msg}") from e
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kw: Any) -> None:
        t = kw.get(ATTR_TEMPERATURE)
        if t is None:
            return
        t = round(float(t) * 2) / 2
        if not self._attr_min_temp <= t <= self._attr_max_temp:
            raise HomeAssistantError("BALANS thermostat: target temperature must be 5 to 35 °C")
        await self._send(target=t)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        word = next((w for w, m in MODES.items() if m == hvac_mode), None)
        if word not in self._modes():
            raise HomeAssistantError(f"BALANS thermostat {self._zone}: mode {hvac_mode} is not offered by this switch")
        await self._send(mode=word)

    async def async_turn_off(self) -> None:
        await self._send(mode="off")

    async def async_turn_on(self) -> None:
        on = [m for m in self._modes() if m != "off"]
        if not on:
            raise HomeAssistantError("BALANS thermostat: the switch offers no mode to turn on")
        await self._send(mode=on[0])
