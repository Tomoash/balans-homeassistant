"""Panel buttons as event entities - from the press counters in /api/status.

"short" / "long" since the first version; v0.6.0 (firmware 2.38.3+): "double", "triple", "very_long" per button, and one
entity "Pads" for two pads at once ("combo") and a touch swallowed by the cleaning or child lock ("locked").

Polling every 3 s: two presses of the same kind within one poll are reported as one event (MQTT gives every press at
once; use it for time-critical automations). The release after a long press (MQTT "long_release") has no counter in
/api/status, so it is not available here."""
from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BalansCoordinator, BalansEntity

# event type -> counter in buttons[i]
BUTTON_EVENTS = {"short": "short", "long": "long", "double": "double", "triple": "triple", "very_long": "vlong"}
PAD_EVENTS = {"combo": "combo_last", "locked": "locked_last"}       # event type = counter in "pads" -> field with the pad name(s)


def _count(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def stepped(now: int, last: int) -> bool:
    """did the counter move? The counters are 16 bit, live in RAM and start from 0 after a restart: a fall to 0 is a
    restart (or the rare wrap) and no press, a fall to another value means presses since the restart."""
    return now > last or (0 < now < last)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    coord: BalansCoordinator = entry.runtime_data
    ents: list[EventEntity] = [BalansButtonEvent(coord, i, b.get("name", str(i + 1)))
                               for i, b in enumerate(coord.data.get("buttons", [])) if isinstance(b, dict)]
    pads = coord.data.get("pads")
    if isinstance(pads, dict) and any(k in pads for k in PAD_EVENTS):  # firmware 2.38.3+
        ents.append(BalansPadsEvent(coord))
    add(ents)


class BalansButtonEvent(BalansEntity, EventEntity):
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(BUTTON_EVENTS)                         # types an older firmware does not count never fire

    def __init__(self, coord: BalansCoordinator, i: int, name: str) -> None:
        super().__init__(coord, f"btn{i}")
        self._i = i
        self._attr_translation_key = "button"
        self._attr_translation_placeholders = {"name": name}
        self._last = self._read()

    def _read(self) -> dict | None:
        bs = self.coordinator.data.get("buttons", [])
        if self._i >= len(bs) or not isinstance(bs[self._i], dict):
            return None
        return {t: _count(bs[self._i].get(k)) for t, k in BUTTON_EVENTS.items()}

    @callback
    def _handle_coordinator_update(self) -> None:
        now = self._read()
        if now is not None:
            for t in BUTTON_EVENTS:
                if self._last is not None and stepped(now[t], self._last[t]):
                    self._trigger_event(t)
            self._last = now
        super()._handle_coordinator_update()


class BalansPadsEvent(BalansEntity, EventEntity):
    """two pads at once and a touch while the panel is locked; the pad names come as the event attribute pads"""
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(PAD_EVENTS)
    _attr_translation_key = "pads"

    def __init__(self, coord: BalansCoordinator) -> None:
        super().__init__(coord, "pads")
        self._last = self._read()

    def _read(self) -> dict | None:
        p = self.coordinator.data.get("pads")
        return {t: _count(p.get(t)) for t in PAD_EVENTS} if isinstance(p, dict) else None

    @callback
    def _handle_coordinator_update(self) -> None:
        now = self._read()
        if now is not None:
            p = self.coordinator.data["pads"]
            for t, name in PAD_EVENTS.items():
                if self._last is not None and stepped(now[t], self._last[t]):
                    self._trigger_event(t, {"pads": str(p.get(name) or "")})
            self._last = now
        super()._handle_coordinator_update()
