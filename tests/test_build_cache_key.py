"""The build cache's signing key: its public half here is the key the settings name (spec 002, FR-007).

The site's old key could not be obtained, so a key was made for the cache on
2026-11-24. Its public half ships in the spack role, which trusts it pinned to
spack_key_fingerprint. The fingerprint is computed here from the file itself
(an OpenPGP version 4 fingerprint: SHA-1 over the public-key packet), so that
a key replaced without the setting, or the setting without the key, fails.
Its private half is never here; it is kept in the team's Keybase folder.
"""

from __future__ import annotations

import base64
import hashlib

import yaml
from support import UNIT

KEY_FILE = UNIT / "roles" / "spack" / "files" / "build-cache-signing-key.pub.asc"
SETTINGS = yaml.safe_load((UNIT / "group_vars" / "all.yml").read_text())
PUBLIC_KEY, USER_ID = 6, 13


def packets(armoured: str) -> list[tuple[int, bytes]]:
    """Give the (tag, body) of each packet of an ASCII-armoured key."""
    lines = armoured.strip().splitlines()
    assert lines[0] == "-----BEGIN PGP PUBLIC KEY BLOCK-----", lines[0]
    assert lines[-1] == "-----END PGP PUBLIC KEY BLOCK-----", lines[-1]
    body = lines[lines.index("") + 1 : -1]
    data = base64.b64decode("".join(line for line in body if not line.startswith("=")))
    found, at = [], 0
    while at < len(data):
        head = data[at]
        assert head & 0x80, "not a packet"
        if head & 0x40:  # new format
            tag, first = head & 0x3F, data[at + 1]
            if first < 192:
                length, at = first, at + 2
            elif first < 224:
                length, at = ((first - 192) << 8) + data[at + 2] + 192, at + 3
            else:
                assert first == 255, "partial lengths are not used in keys"
                length, at = int.from_bytes(data[at + 2 : at + 6], "big"), at + 6
        else:  # old format
            tag, size = (head >> 2) & 0x0F, [1, 2, 4][head & 0x03]
            length, at = int.from_bytes(data[at + 1 : at + 1 + size], "big"), at + 1 + size
        found.append((tag, data[at : at + length]))
        at += length
    return found


def test_the_file_is_a_public_key_and_nothing_secret() -> None:
    text = KEY_FILE.read_text()
    assert "PRIVATE" not in text
    assert next(tag for tag, _ in packets(text)) == PUBLIC_KEY


def test_its_fingerprint_is_the_one_the_settings_name() -> None:
    (key,) = [body for tag, body in packets(KEY_FILE.read_text()) if tag == PUBLIC_KEY]
    assert key[0] == 4, "a version 4 key"
    fingerprint = hashlib.sha1(b"\x99" + len(key).to_bytes(2, "big") + key).hexdigest().upper()
    assert fingerprint == SETTINGS["spack_key_fingerprint"]


def test_its_user_id_names_no_person() -> None:
    (user_id,) = [body.decode() for tag, body in packets(KEY_FILE.read_text()) if tag == USER_ID]
    assert "@" not in user_id, user_id
    assert "build cache" in user_id
