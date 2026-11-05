"""Tiny PNG writer. The stdlib has no encoder, and the shots are RGB."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np


def write_png(path, rgb: np.ndarray) -> None:
    image = np.ascontiguousarray(rgb, dtype=np.uint8)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"expected HxWx3, got {image.shape}")
    height, width, _ = image.shape
    raw = b"".join(b"\x00" + image[y].tobytes() for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)


def read_png(path) -> np.ndarray:
    """Read back a PNG that write_png wrote: 8-bit RGB, unfiltered rows."""
    data = Path(path).read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"{path} is not a PNG")
    pos, idat, size = 8, b"", None
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            width, height, depth, colour, _c, _f, _i = struct.unpack(">IIBBBBB", body)
            if depth != 8 or colour != 2:
                raise ValueError(f"{path} is not 8-bit RGB")
            size = (height, width)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    height, width = size
    rows = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(height, 1 + width * 3)
    if rows[:, 0].any():
        raise ValueError(f"{path} uses PNG row filters this reader doesn't decode")
    return rows[:, 1:].reshape(height, width, 3).copy()
