"""The core accepts an artifact only when it exists inside its case folder and decodes."""

from __future__ import annotations

import pytest

from conftest import load_fake
from ihav_auto_improve.artifacts import check

PNG = load_fake().png_bytes()


@pytest.mark.parametrize("name, data, media_type, status", [
    ("ok.png", PNG, "image/png", "pass"),
    ("cut.png", PNG[:-10], "image/png", "fail"),
    ("lie.png", b"GIF89a;", "image/png", "fail"),
    ("ok.jpg", b"\xff\xd8\xff\xe0data\xff\xd9", "image/jpeg", "pass"),
    ("ok.json", b'{"a": 1}', "application/json", "pass"),
    ("bad.json", b"{", "application/json", "fail"),
    ("note.txt", "chữ".encode(), "text/plain", "pass"),
    ("clip.mp4", b"\x00\x00\x00\x18ftyp", "video/mp4", "unscorable"),
])
def test_decoding(tmp_path, name, data, media_type, status):
    (tmp_path / name).write_bytes(data)
    assert check(tmp_path, {"path": name, "media_type": media_type})[0] == status


def test_missing_empty_and_outside_files_fail(tmp_path):
    (tmp_path / "empty.png").write_bytes(b"")
    (tmp_path.parent / "outside.png").write_bytes(PNG)
    assert check(tmp_path, {"path": "absent.png", "media_type": "image/png"})[0] == "fail"
    assert check(tmp_path, {"path": "empty.png", "media_type": "image/png"})[0] == "fail"
    assert check(tmp_path, {"path": "../outside.png", "media_type": "image/png"}) == \
        ("fail", "../outside.png is outside the case folder")
