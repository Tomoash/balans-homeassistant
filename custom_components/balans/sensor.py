"""Panel sensor (BME688 + BSEC2 IAQ), energy estimate, mains frequency.

v0.3.0: slider position (01B chevron), read-only heating values (03I-T, 03I-R).
v0.4.0: device health (firmware 2.38.0+).
v0.5.0: thermostat values moved to climate.py when the firmware has the "climate" block.
v0.6.0: proximity value (firmware 2.38.3+), off by default."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory,
                                 UnitOfEnergy, UnitOfFrequency, UnitOfPower, UnitOfPressure, UnitOfTemperature, UnitOfTime)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import BalansCoordinator, BalansEntity
from .const import slider_percent


@dataclass(frozen=True, kw_only=True)
class BDesc(SensorEntityDescription):
    value: Callable[[dict], float | None]


def _s(k):
    return lambda d: (d.get("sensor") or {}).get(k) if (d.get("sensor") or {}).get("ok") else None


def _wifi(d):
    return (d.get("nets") or {}).get("wifi") or {}


def _e(k):
    return lambda d: (d.get("energy") or {}).get(k)


SENSORS = (
    BDesc(key="temperature", translation_key="temperature", device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
          native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=1, value=_s("temperature")),
    BDesc(key="humidity", translation_key="humidity", device_class=SensorDeviceClass.HUMIDITY, state_class=SensorStateClass.MEASUREMENT,
          native_unit_of_measurement=PERCENTAGE, suggested_display_precision=0, value=_s("humidity")),
    BDesc(key="pressure", translation_key="pressure", device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE, state_class=SensorStateClass.MEASUREMENT,
          native_unit_of_measurement=UnitOfPressure.HPA, suggested_display_precision=0, value=_s("pressure")),
    BDesc(key="iaq", translation_key="iaq", device_class=SensorDeviceClass.AQI, state_class=SensorStateClass.MEASUREMENT,
          value=_s("iaq")),
    BDesc(key="co2_eq", translation_key="co2_eq", device_class=SensorDeviceClass.CO2, state_class=SensorStateClass.MEASUREMENT,
          native_unit_of_measurement="ppm", value=_s("co2_eq")),      # literal: the old constant is deprecated
    BDesc(key="power", translation_key="power", device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT,
          native_unit_of_measurement=UnitOfPower.WATT, value=_e("power")),
    BDesc(key="energy", translation_key="energy", device_class=SensorDeviceClass.ENERGY, state_class=SensorStateClass.TOTAL_INCREASING,
          native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, suggested_display_precision=3, value=_e("total")),
    BDesc(key="mains_hz", translation_key="mains_hz", device_class=SensorDeviceClass.FREQUENCY, state_class=SensorStateClass.MEASUREMENT,
          native_unit_of_measurement=UnitOfFrequency.HERTZ, suggested_display_precision=2, entity_registry_enabled_default=False,
          value=lambda d: d.get("mains_hz") or None),
    # v0.2.0: diagnostics
    BDesc(key="wifi_rssi", translation_key="wifi_rssi", device_class=SensorDeviceClass.SIGNAL_STRENGTH, state_class=SensorStateClass.MEASUREMENT,
          native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT, entity_category=EntityCategory.DIAGNOSTIC,
          value=lambda d: _wifi(d).get("rssi") if _wifi(d).get("up") else None),
    BDesc(key="uptime", translation_key="uptime", device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.SECONDS,
          entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,     # changes with every poll
          value=lambda d: d.get("uptime")),
)


def _th(k):
    return lambda d: (d.get("thermo") or {}).get(k)


def _hz(z, k):
    def get(d):
        hs = d.get("heat") or []
        return hs[z].get(k) if z < len(hs) and isinstance(hs[z], dict) else None
    return get


THERMO = (
    BDesc(key="thermo_current", translation_key="thermo_current", device_class=SensorDeviceClass.TEMPERATURE,
          state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=1,
          value=_th("current")),
    BDesc(key="thermo_target", translation_key="thermo_target", device_class=SensorDeviceClass.TEMPERATURE,
          native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=1, value=_th("set_eff")),
)


def heat_zone(z: int, floor: bool) -> list[BDesc]:
    """per zone: why the safety layer heats or not, and the floor temperature when the zone has a floor sensor"""
    out = [BDesc(key=f"heat{z}_reason", translation_key="heat_reason", value=_hz(z, "reason"))]
    if floor:
        out.append(BDesc(key=f"heat{z}_floor", translation_key="heat_floor", device_class=SensorDeviceClass.TEMPERATURE,
                         state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                         suggested_display_precision=1, value=_hz(z, "floor")))
    return out


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: BalansCoordinator = entry.runtime_data
    d = coord.data
    present = [s for s in SENSORS
               if (s.key in ("temperature", "humidity", "pressure") and (d.get("sensor") or {}).get("ok"))
               or (s.key in ("iaq", "co2_eq") and "iaq" in (d.get("sensor") or {}))
               or (s.key in ("power", "energy") and d.get("energy"))
               or (s.key == "mains_hz" and d.get("mains_hz"))
               or (s.key == "wifi_rssi" and _wifi(d).get("configured"))
               or s.key == "uptime"]
    ents: list[SensorEntity] = [BalansSensor(coord, s) for s in present]
    if isinstance(d.get("slider"), dict):                              # panels with a slider (01B)
        ents.append(BalansSlider(coord))
    if isinstance(d.get("health"), dict):                              # firmware 2.38.0+
        ents.append(BalansHealth(coord))
    if isinstance(d.get("prox"), dict) and "value" in d["prox"]:       # firmware 2.38.3+
        ents.append(BalansProximity(coord))
    if d.get("heat"):                                                  # heating modules: values only, no control yet
        th = d.get("thermo") or {}
        if not isinstance(d.get("climate"), dict):                     # v0.5.0: with the climate entity these would be doubles
            ents += [BalansSensor(coord, s) for s in THERMO if s.key != "thermo_current" or "current" in th]
        for z, h in enumerate(d["heat"]):
            if isinstance(h, dict):
                ents += [BalansSensor(coord, s, z + 1) for s in heat_zone(z, "floor" in h)]
    add(ents)


class BalansSensor(BalansEntity, SensorEntity):
    entity_description: BDesc

    def __init__(self, coord: BalansCoordinator, desc: BDesc, zone: int | None = None) -> None:
        super().__init__(coord, desc.key)
        self.entity_description = desc
        if zone is not None:
            self._attr_translation_placeholders = {"zone": str(zone)}

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value(self.coordinator.data)


class BalansSlider(BalansEntity, SensorEntity, RestoreEntity):
    """v0.3.0: position of the slider in percent. The switch reports a position only while a finger is on the slider, so
    the last one is kept (also over a restart of Home Assistant). With the 3 s poll a short touch can be missed; MQTT
    (<base>/slider/pos) gives every move."""
    _attr_translation_key = "slider"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "slider_pos")
        self._last: int | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        old = await self.async_get_last_state()
        if old is not None and self._last is None:
            try:
                self._last = max(0, min(100, int(float(old.state))))
            except (TypeError, ValueError):
                pass
        self._take()

    def _take(self) -> None:
        self._last = slider_percent((self.coordinator.data.get("slider") or {}).get("pos"), self._last)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._take()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> int | None:
        return self._last

    @property
    def extra_state_attributes(self) -> dict:
        s = self.coordinator.data.get("slider") or {}
        pos = s.get("pos")
        return {"touched": isinstance(pos, (int, float)) and pos >= 0, "blocked": bool(s.get("blocked"))}


class BalansHealth(BalansEntity, SensorEntity):
    """v0.4.0: "Zdravi zarizeni" of the switch (firmware 2.38.0+): ok / warn / error, the reasons as an attribute."""
    _attr_translation_key = "health"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "warn", "error"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "health")

    @property
    def native_value(self) -> str | None:
        lvl = (self.coordinator.data.get("health") or {}).get("level")
        return lvl if lvl in self._attr_options else None        # a level this version does not know: unknown, not an error

    @property
    def extra_state_attributes(self) -> dict:
        rs = (self.coordinator.data.get("health") or {}).get("reasons")
        return {"reasons": [str(r) for r in rs] if isinstance(rs, list) else []}


class BalansProximity(BalansEntity, SensorEntity):
    """v0.6.0: live value of the wake-on-approach sensing (firmware 2.38.3+), for tuning the threshold: per mille above
    the idle value of the strongest channel, can be negative. Off by default: it changes all the time and would only fill
    the recorder."""
    _attr_translation_key = "proximity"
    _attr_native_unit_of_measurement = "\u2030"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "prox")

    @property
    def native_value(self) -> float | None:
        v = (self.coordinator.data.get("prox") or {}).get("value")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def extra_state_attributes(self) -> dict:
        p = self.coordinator.data.get("prox") or {}
        return {k: p[k] for k in ("thr", "release", "near", "channel", "min60", "max60", "blanked", "blank_min", "blank_max") if k in p}
