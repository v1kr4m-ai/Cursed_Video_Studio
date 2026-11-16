"""Read facts from DJI's embedded `djmd` metadata track.

The track is protobuf with an unpublished schema (`dvtm_AVATA360.proto`). Fields are found by
number, so everything here is reverse engineered from labelled sample clips and must fail
safe: anything unexpected returns "unknown", never a guess.

Colour mode (found 2026-11-16, see DECISIONS D-014): clip-header field 2.2.4.1.
  absent / 0 -> Normal   (proto3 omits zero values)
  19         -> D-Log M
Confirmed on 7 Avata 360 clips, firmware 01.00.01 and 01.00.06. Caveat: in that sample every
D-Log M clip was outdoor and every Normal clip indoor; field 2.2 sits in the static camera
header, not the GPS block, but one indoor D-Log M clip would remove the doubt (R-02).
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from .tools import find_tool, run

COLOR_MODE_FIELD = "2.2.4"
COLOR_MODE_CODES = {0: "normal", 19: "dlog_m"}


class ColorMode(StrEnum):
    NORMAL = "normal"
    DLOG_M = "dlog_m"
    UNKNOWN = "unknown"


class ColorModeResult(BaseModel):
    mode: ColorMode
    source: str          # "camera_metadata" | "none"
    raw: int | None = None
    note: str | None = None


def _varint(b: bytes, i: int) -> tuple[int, int]:
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def decode(b: bytes, prefix: str = "", depth: int = 0) -> dict[str, list] | None:
    """Generic protobuf wire decode into {"2.2.4.1": [19], ...}; None if b is not protobuf.

    Length-delimited fields that parse as messages are expanded; an empty one is recorded
    as b"" so "present but all-default" stays distinguishable from "absent".
    """
    out: dict[str, list] = defaultdict(list)
    i = 0
    try:
        while i < len(b):
            key, i = _varint(b, i)
            f, wt = key >> 3, key & 7
            if f == 0:
                return None
            p = f"{prefix}{f}"
            if wt == 0:
                v, i = _varint(b, i)
                out[p].append(v)
            elif wt == 1:
                out[p].append(b[i:i + 8]); i += 8
            elif wt == 5:
                out[p].append(b[i:i + 4]); i += 4
            elif wt == 2:
                n, i = _varint(b, i)
                chunk = b[i:i + n]
                i += n
                if i > len(b):
                    return None
                sub = decode(chunk, p + ".", depth + 1) if chunk and depth < 8 else None
                if sub:
                    for k, vs in sub.items():
                        out[k].extend(vs)
                out[p].append(chunk if sub is None else b"<msg>")
            else:
                return None
    except IndexError:
        return None
    return out


def first_packet(path: str | Path) -> bytes:
    proc = run([find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:d:0?",
                "-c", "copy", "-frames:d", "1", "-f", "data", "-"], timeout=30)
    return proc.stdout if proc.returncode == 0 else b""


def color_mode_from_fields(fields: dict[str, list] | None) -> ColorModeResult:
    if not fields or COLOR_MODE_FIELD not in fields:
        return ColorModeResult(mode=ColorMode.UNKNOWN, source="none",
                               note="no DJI colour-mode field in metadata")
    raw = fields.get(COLOR_MODE_FIELD + ".1", [0])[0]
    mode = COLOR_MODE_CODES.get(raw)
    if mode is None:
        return ColorModeResult(mode=ColorMode.UNKNOWN, source="camera_metadata", raw=raw,
                               note=f"unrecognised colour-mode code {raw} (HLG or new mode?)")
    return ColorModeResult(mode=ColorMode(mode), source="camera_metadata", raw=raw)


def color_mode(path: str | Path) -> ColorModeResult:
    """Colour mode of a DJI clip from its own metadata; UNKNOWN for non-DJI files."""
    return color_mode_from_fields(decode(first_packet(path)))
