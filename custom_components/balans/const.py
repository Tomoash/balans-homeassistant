"""Constants of the BALANS integration."""
from .firmware import version_key

DOMAIN = "balans"
CONF_TOKEN = "token"
CONF_HTTPS = "https"
CONF_FINGERPRINT = "fingerprint"
CONF_ADMIN_TOKEN = "admin_token"   # optional: firmware update, identify, restart (v0.2.0)
SCAN_INTERVAL_S = 3            # status poll (the device has no push channel without MQTT yet)
INFO_INTERVAL_S = 600          # info + configuration (names, scenes) refresh


def is_heat_output(data: dict, out: dict) -> bool:
    """v0.3.0: heat-demand outputs of 03I-T / 03I-R are not plain switches.

    Firmware with the heating release marks them "role":"heat"; older firmware only reports kind "switch", there every
    output of a device that has the "heat" block in /api/status is a heat output (those modules have no other outputs)."""
    return out.get("role") == "heat" or ("role" not in out and bool(data.get("heat")))


def slider_percent(pos, last):
    """v0.3.0: slider.pos in /api/status is 0..1000 while a finger is on the slider and -1 otherwise.

    Returns 0..100; while nothing touches the slider the last value is kept."""
    if isinstance(pos, bool) or not isinstance(pos, (int, float)) or pos < 0:
        return last
    return min(100, round(pos / 10))


def has_cap(info: dict, name: str, default: bool = False) -> bool:
    """v0.5.0: "caps" of /api/info (firmware 2.38.1+), an object of flags or a list of names; `default` without it"""
    caps = info.get("caps") if isinstance(info, dict) else None
    if isinstance(caps, dict):
        return bool(caps.get(name))
    if isinstance(caps, list):
        return name in caps
    return default


def is_heat_device(info: dict) -> bool:
    """v0.5.0: a heating module (03I-T, 03I-R) by hw.role or caps; none of its outputs is a plain switch"""
    hw = info.get("hw") if isinstance(info, dict) else None
    return (isinstance(hw, dict) and hw.get("role") == "heat") or has_cap(info, "heat")


def climate_modes(c: dict) -> list:
    """v0.5.0: modes the switch offers, only the words this integration knows; "off" always"""
    ms = c.get("modes") if isinstance(c.get("modes"), list) else ["off", "heat"]
    out = [m for m in ("off", "heat", "cool") if m in ms or m == "off"]
    return out


def climate_action(c: dict):
    """v0.5.0: what the thermostat does now, in Home Assistant's words, or None when the switch says something unknown"""
    a = c.get("action")
    if a == "heating" and c.get("preheat"):
        return "preheating"
    return a if a in ("off", "idle", "heating", "cooling") else None


PLATFORMS = ["light", "switch", "sensor", "binary_sensor", "button", "event", "update", "climate", "number"]
FW_DIR = "balans/firmware"         # under the HA configuration directory: put smartswitch_ota.bin here (never downloaded)
OTA_WAIT_S = 240


def fw_at_least(info: dict, version: str) -> bool:
    """v0.7.0: is the firmware in /api/info at least `version`? Unparsable versions count as older."""
    have = version_key(info.get("fw") if isinstance(info, dict) else None)
    return have >= version_key(version)


def bar_percent(v):
    """v0.7.0: slider.value of /api/status (0..100 %, -1 = nothing shown yet) -> 0..100 or None"""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        return None
    return min(100, int(v))
