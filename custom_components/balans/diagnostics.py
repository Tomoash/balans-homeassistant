"""v0.7.1: diagnostics download (Settings → Devices & services → BALANS → ⋮ → Download diagnostics).

Contains what the integration reads from the switch, so a problem can be reported. Tokens, the certificate fingerprint,
the address and network details are removed."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_ADMIN_TOKEN, CONF_FINGERPRINT, CONF_TOKEN

TO_REDACT = {CONF_TOKEN, CONF_ADMIN_TOKEN, CONF_FINGERPRINT, CONF_HOST, "ip", "mac", "ssid", "bssid", "gw", "gateway",
             "dns", "mask", "netmask", "hostname", "broker", "user", "username", "password", "pass", "psk", "key", "secret", "token", "code",
             "setup_code", "fw_key", "pub", "serial", "ca", "pem"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coord = entry.runtime_data
    return {
        "entry": {"data": async_redact_data(dict(entry.data), TO_REDACT),
                  "options": async_redact_data(dict(entry.options), TO_REDACT)},
        "info": async_redact_data(coord.info, TO_REDACT),
        "status": async_redact_data(coord.data or {}, TO_REDACT),
        "config": async_redact_data(coord.cfg, TO_REDACT),
        "firmware_file": (coord.latest or {}).get("version"),
        "admin_token": coord.api.has_admin,
    }
