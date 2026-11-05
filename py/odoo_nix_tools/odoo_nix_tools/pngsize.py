"""A PNG's size from its IHDR chunk, without an imaging library (DESIGN.md §1.1)."""

from __future__ import annotations

import struct

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int]:
    """``(width, height)`` of the PNG ``data``; ``ValueError`` when it is not a PNG."""
    if len(data) < 24 or not data.startswith(SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG image")
    width, height = struct.unpack(">II", data[16:24])
    return width, height
