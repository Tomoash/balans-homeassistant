"""Small async client for the BALANS switch web API (FW >= 2.10.2).

Authentication: an API token from the switch web UI (System -> API tokens), role "control" is enough (status, outputs,
scenes); "admin" also works. Sent as "Authorization: Bearer bt_..." - never in the URL.
HTTPS (optional): the device certificate is self-signed, so it is pinned by its SHA-256 fingerprint (shown in the switch
web UI and on the 01C display) instead of a CA check.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

XRW = {"X-Requested-With": "smartswitch"}


class BalansError(Exception):
    """Communication error."""


class BalansAuthError(BalansError):
    """Token missing, wrong or without the needed role."""


class BalansApi:
    def __init__(self, session: aiohttp.ClientSession, host: str, token: str, https: bool = False,
                 fingerprint: str | None = None, admin_token: str | None = None) -> None:
        self._s = session
        self._base = f"{'https' if https else 'http'}://{host}"
        self._h = {**XRW, "Authorization": f"Bearer {token}"}
        # v0.2.0: the optional administrator token is used ONLY for update / identify / restart - everything else keeps
        # running on the control token
        self._ha = {**XRW, "Authorization": f"Bearer {admin_token}"} if admin_token else None
        self._ssl: Any = None
        if https:
            fp = (fingerprint or "").replace(":", "").strip()
            if len(fp) != 64:
                raise BalansError("HTTPS needs the certificate SHA-256 fingerprint of the switch")
            self._ssl = aiohttp.Fingerprint(bytes.fromhex(fp))

    @property
    def has_admin(self) -> bool:
        return self._ha is not None

    async def _req(self, method: str, path: str, body: dict | None = None, *, admin: bool = False,
                   data: bytes | None = None, timeout: float = 10) -> Any:
        if admin and self._ha is None:
            raise BalansAuthError("administrator token not configured")
        headers = dict(self._ha if admin else self._h)
        if data is not None:
            headers["Content-Type"] = "application/octet-stream"
        try:
            async with asyncio.timeout(timeout):
                async with self._s.request(method, self._base + path, json=body if data is None else None, data=data,
                                           headers=headers,
                                           ssl=self._ssl if self._ssl is not None else None) as r:
                    if r.status in (401, 403):
                        raise BalansAuthError(f"HTTP {r.status}: {await r.text()}")
                    if r.status >= 400:
                        raise BalansError(f"HTTP {r.status}: {await r.text()}")
                    return await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise BalansError(str(e)) from e

    async def info(self) -> dict:
        return await self._req("GET", "/api/info")

    async def status(self) -> dict:
        return await self._req("GET", "/api/status")

    async def config(self) -> dict:
        return await self._req("GET", "/api/config")

    async def out(self, i: int, **kw: Any) -> None:
        """kw: on (bool), level (1..1000), rgbw ([r, g, b, w] 0..255), toggle (True)"""
        await self._req("POST", "/api/out", {"i": i, **kw})

    async def thermostat(self, zone: int = 1, **kw: Any) -> None:
        """v0.5.0, FW 2.38.1+: kw target (5..35) and / or mode ("off", "heat", "cool"); nothing else is accepted.
        v0.7.0, FW 2.41.0+: zone 2 = the second thermostat of 03I-T (modes off / heat only); zone 1 sends no "zone" key so
        older firmware keeps working."""
        body = {k: v for k, v in kw.items() if k in ("target", "mode")}
        if zone == 2:
            body["zone"] = 2
        await self._req("POST", "/api/thermostat", body)

    async def slider(self, value: int) -> None:
        """v0.7.0, FW 2.40.0+: the value the level bar of the chevron panel shows (0..100, display only)"""
        await self._req("POST", "/api/slider", {"value": int(value)})

    async def scene(self, n: int) -> None:
        await self._req("POST", "/api/scene", {"apply": n})

    async def dali(self) -> dict:
        """03F DALI module: bus, devices, groups (FW with the DALI driver)."""
        return await self._req("GET", "/api/dali")

    async def dali_set(self, g: int, **kw: Any) -> None:
        """kw: on (bool), level (1..1000), kelvin, rgbw"""
        await self._req("POST", "/api/dali", {"set": {"g": g, **kw}})

    # ---- v0.2.0: administrator token
    async def admin_check(self) -> None:
        """the administrator token must be accepted by an admin-only endpoint"""
        await self._req("GET", "/api/tokens", admin=True)

    async def identify(self) -> None:
        await self._req("POST", "/api/identify", {}, admin=True)

    async def reboot(self) -> None:
        await self._req("POST", "/api/reboot", {}, admin=True)

    async def ota(self, image: bytes) -> None:
        """upload a signed application image; the switch checks chip, project, anti-downgrade and signature itself"""
        await self._req("POST", "/api/ota", admin=True, data=image, timeout=300)
