"""Artifact checks the core can make without project libraries: the file is inside its folder and decodes."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path


def check(out_dir: Path, artifact) -> tuple:
    """(status, reason) for one artifact entry {"path": relative to out_dir, "media_type": ...}."""
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
        return "fail", "artifact entry needs a path"
    root = Path(out_dir).resolve()
    path = (root / artifact["path"]).resolve()
    if root not in path.parents:
        return "fail", f"{artifact['path']} is outside the case folder"
    if not path.is_file() or path.stat().st_size == 0:
        return "fail", f"{artifact['path']} is missing or empty"
    media_type = artifact.get("media_type") or ""
    decoder = DECODERS.get(media_type) or (_text if media_type.startswith("text/") else None)
    if decoder is None:
        return "unscorable", f"{artifact['path']}: the core cannot decode {media_type or 'an unnamed media type'}"
    try:
        decoder(path.read_bytes())
    except Exception as exc:  # any decode error means the artifact is not usable
        return "fail", f"{artifact['path']} does not decode as {media_type}: {exc}"
    return "pass", ""


def _png(data: bytes) -> None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("no PNG signature")
    pos, kinds, pixels = 8, [], b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body, crc = data[pos + 8:pos + 8 + length], data[pos + 8 + length:pos + 12 + length]
        if len(body) != length or len(crc) != 4 or zlib.crc32(kind + body) != struct.unpack(">I", crc)[0]:
            raise ValueError(f"chunk {kind.decode('latin-1')} is truncated or corrupt")
        kinds.append(kind)
        pixels += body if kind == b"IDAT" else b""
        pos += 12 + length
    if not kinds or kinds[0] != b"IHDR" or kinds[-1] != b"IEND" or b"IDAT" not in kinds:
        raise ValueError("IHDR, IDAT or IEND missing")
    zlib.decompress(pixels)


def _jpeg(data: bytes) -> None:
    if data[:3] != b"\xff\xd8\xff" or data.rstrip(b"\x00")[-2:] != b"\xff\xd9":
        raise ValueError("no JPEG start or end marker")


def _gif(data: bytes) -> None:
    if data[:6] not in (b"GIF87a", b"GIF89a") or data[-1:] != b";":
        raise ValueError("no GIF header or trailer")


def _webp(data: bytes) -> None:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or struct.unpack("<I", data[4:8])[0] + 8 > len(data):
        raise ValueError("no WEBP header or truncated")


def _text(data: bytes) -> None:
    data.decode("utf-8")


DECODERS = {
    "image/png": _png,
    "image/jpeg": _jpeg,
    "image/gif": _gif,
    "image/webp": _webp,
    "application/json": lambda data: json.loads(data.decode("utf-8")),
}
