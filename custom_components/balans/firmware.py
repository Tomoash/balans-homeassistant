"""Firmware images in <config>/balans/firmware (v0.2.0). Nothing is ever downloaded: the BALANS firmware must not be
published, so the signed smartswitch_ota.bin is copied there by hand. Only the version is read here - the switch itself
verifies chip, project, anti-downgrade and the signature on /api/ota. Pure Python, no Home Assistant imports."""
from __future__ import annotations

import os
import struct

APP_DESC_MAGIC = 0xABCD5432
APP_DESC_OFFSET = 32            # image header (24 B) + first segment header (8 B)
PROJECT = "smartswitch"


def _cstr(b: bytes) -> str:
    return b.split(b"\x00", 1)[0].decode("ascii", "replace")


def parse_image(head: bytes) -> dict | None:
    """first >= 256 bytes of a file -> {"version", "project"} or None when it is not an ESP32 application image"""
    if len(head) < APP_DESC_OFFSET + 112 or head[:1] != b"\xe9":
        return None
    if struct.unpack_from("<I", head, APP_DESC_OFFSET)[0] != APP_DESC_MAGIC:
        return None
    o = APP_DESC_OFFSET + 16
    return {"version": _cstr(head[o:o + 32]), "project": _cstr(head[o + 32:o + 64])}


def version_key(v: str | None) -> tuple:
    """"2.35.1" -> (2, 35, 1); anything unparsable sorts lowest"""
    out = []
    for p in str(v or "").strip().lstrip("vV").split("."):
        n = ""
        for ch in p:
            if not ch.isdigit():
                break
            n += ch
        if not n:
            return (-1,)
        out.append(int(n))
    return tuple(out) if out else (-1,)


def is_newer(candidate: str | None, installed: str | None) -> bool:
    return version_key(candidate) > version_key(installed)


def find_latest(folder: str) -> dict | None:
    """newest BALANS application image in the folder (not recursive) -> {"version", "path"} or None. Blocking I/O."""
    best = None
    try:
        names = sorted(os.listdir(folder))
        root = os.path.realpath(folder)
    except OSError:
        return None
    for fn in names:
        if not fn.lower().endswith(".bin"):
            continue
        p = os.path.join(folder, fn)
        rp = os.path.realpath(p)
        if os.path.dirname(rp) != root or not os.path.isfile(rp):      # (a link pointing out of the folder is ignored)
            continue
        try:
            with open(p, "rb") as f:
                d = parse_image(f.read(256))
        except OSError:
            continue
        if d and d["project"] == PROJECT and (best is None or is_newer(d["version"], best["version"])):
            best = {"version": d["version"], "path": p}
    return best


def read_checked(path: str, version: str) -> bytes:
    """the whole image, only if it still is the version that was offered (the file may have been replaced). Blocking."""
    with open(path, "rb") as f:
        data = f.read()
    d = parse_image(data[:256])
    if not d or d["project"] != PROJECT or d["version"] != version:
        raise ValueError("firmware file changed or is not a BALANS image")
    return data
