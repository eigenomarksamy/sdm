"""Decrypt a SQLCipher 4 database into a plain SQLite file.

Rekordbox 6 and 7 encrypt `master.db` with SQLCipher, and pyrekordbox opens it
through `sqlcipher3`, a compiled extension. That has no Pyodide build, and its
wheels do not cover every platform, so where it is missing `core.rekordbox_db`
decrypts the file with this module and hands pyrekordbox the plain copy.

**The format is SQLCipher 4's defaults, checked against the real thing, not
assumed:** a local `master.db` (17,525 pages) decrypts with every page's HMAC
verifying, and the copy reads back the same rows as sqlcipher3 does. Per page:

- 4096 bytes, of which the last 80 are reserved: a 16-byte IV, then a 64-byte
  HMAC-SHA512 over the ciphertext, the IV and the page number (little-endian).
- AES-256-CBC over everything before the reserve. Page 1's first 16 bytes are
  not encrypted: they are the KDF salt, and become SQLite's magic string again.
- The key is PBKDF2-HMAC-SHA512 of the passphrase, 256,000 iterations; the HMAC
  key is PBKDF2 of that key, 2 iterations, over the salt XOR 0x3a.

The plain copy keeps the 80 reserved bytes per page (zeroed): page 1's header
already says they are reserved, and SQLite skips reserved space, so no b-tree
offset has to move.

Every HMAC is checked, so a wrong key or a damaged page is an error rather
than a database of noise. Pages are streamed, one at a time, so a large
library costs no more memory than a small one.

Needs `pycryptodome` for AES and PBKDF2; the HMAC is stdlib. Not
`cryptography`: its Rust extension panics on import in Pyodide 314, and
Pyodide's stdlib has no `hashlib.pbkdf2_hmac` (no OpenSSL). pycryptodome is
plain C, has no dependencies, and is both a Pyodide package and a pip one.
"""
from __future__ import annotations

import hmac
import struct

PAGE_SIZE = 4096
KDF_ITERATIONS = 256_000
SALT_SIZE = 16
IV_SIZE = 16
HMAC_SIZE = 64
RESERVE = IV_SIZE + HMAC_SIZE
KEY_SIZE = 32
SQLITE_MAGIC = b"SQLite format 3\x00"


class DecryptError(ValueError):
    """The file is not a SQLCipher 4 database this passphrase opens, or a page is damaged."""


def decrypt_file(source: str, target: str, passphrase: str) -> int:
    """Write the plain SQLite form of `source` to `target`. Returns the page count."""
    from Crypto.Cipher import AES
    from Crypto.Hash import SHA512
    from Crypto.Protocol.KDF import PBKDF2

    with open(source, "rb") as src, open(target, "wb") as dst:
        first = src.read(PAGE_SIZE)
        if len(first) < PAGE_SIZE:
            raise DecryptError(f"{source} is too short to be a SQLCipher database")
        if first.startswith(SQLITE_MAGIC):
            raise DecryptError(f"{source} is a plain SQLite database, not an encrypted one")

        salt = first[:SALT_SIZE]
        key = PBKDF2(passphrase.encode(), salt, KEY_SIZE, count=KDF_ITERATIONS, hmac_hash_module=SHA512)
        mac_salt = bytes(b ^ 0x3A for b in salt)
        mac_key = PBKDF2(key, mac_salt, KEY_SIZE, count=2, hmac_hash_module=SHA512)

        number, page = 1, first
        while page:
            if len(page) < PAGE_SIZE:
                raise DecryptError(f"{source} ends partway through page {number}")
            start = SALT_SIZE if number == 1 else 0
            body = page[start:PAGE_SIZE - RESERVE]
            iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - HMAC_SIZE]
            expected = page[PAGE_SIZE - HMAC_SIZE:]
            actual = hmac.digest(mac_key, body + iv + struct.pack("<I", number), "sha512")
            if not hmac.compare_digest(actual, expected):
                if number == 1:
                    raise DecryptError(f"{source} does not open with this key: not a "
                                       "Rekordbox 6/7 master.db, or a newer encryption")
                raise DecryptError(f"page {number} of {source} is damaged (its HMAC does not match)")

            plain = AES.new(key, AES.MODE_CBC, iv).decrypt(body)
            dst.write((SQLITE_MAGIC if number == 1 else b"") + plain + bytes(RESERVE))
            number += 1
            page = src.read(PAGE_SIZE)
    return number - 1
