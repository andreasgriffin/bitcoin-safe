#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

"""Python-only Sparrow H2 MVStore reader tests, no H2 JAR or Java required.

Tests build minimal, well-formed MVStore pages without carrying a real wallet,
then optionally run against external test fixtures via environment variables.
"""

from __future__ import annotations

import hashlib
import os
import struct
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bitcoin_safe.wallet_import.adapters import load_file
from bitcoin_safe.wallet_import.h2_python import (
    H2DecodeError,
    _BinaryReader,
    _expand_lzf,
    _fletcher32,
    _MVStore,
    _xts_decrypt_sector,
    extract_sparrow_h2_rows_python,
)
from bitcoin_safe.wallet_import.h2_verify import _aes_block
from bitcoin_safe.wallet_import.model import ExchangeError


def varint(n: int) -> bytes:
    result = bytearray()
    while n > 127:
        result.append((n & 127) | 128)
        n >>= 7
    return bytes(result) + bytes([n])


def string(s: str) -> bytes:
    assert s.isascii()
    return varint(len(s)) + s.encode("ascii")


def val(x) -> bytes:
    if x is None:
        return b"\x00"
    if x is True:
        return b"\x41"
    if x is False:
        return b"\x40"
    if isinstance(x, int):
        if x < 0:
            return b"\x42" + varint(-x)
        if x < 16:
            return bytes([32 + x])
        return b"\x04" + varint(x)
    if isinstance(x, str):
        return (bytes([68 + len(x)]) + x.encode("ascii")) if len(x) < 32 else b"\x0d" + string(x)
    if isinstance(x, bytes):
        return b"\x0c" + varint(len(x)) + x
    raise TypeError(x)


def header(text: str) -> bytes:
    prefix = text.encode("ascii")
    result = prefix + f",fletcher:{_fletcher32(prefix):08x}\n".encode("ascii")
    assert len(result) < 4096
    return result + b"\0" * (4096 - len(result))


def sample_mvstore_file(network: int = 0, mnemonic: str | None = None) -> bytes:
    """Synthesize a minimal H2 2.1 MVStore with policy, wallet, keystore.

    Source-independent synthetic fixture; optionally includes a test seed.
    Pages use H2's exact on-disk keys, checksum and versioned row encoding.
    """
    chunk = bytearray(b" " * 128)
    page_number = 0

    def make_page(mapid, keys, values, keykind="str", valkind="str", compressed=False):
        nonlocal page_number
        encoded_keys = b"".join(string(x) if keykind == "str" else varint(x) for x in keys)
        if valkind == "str":
            encoded_values = b"".join(string(x) for x in values)
        else:
            encoded_values = b"\x00" + b"".join(b"".join(val(x) for x in row) for row in values)
        contents = encoded_keys + encoded_values
        if compressed:
            compressed_data = zlib.compress(contents)
            if len(compressed_data) + 1 < len(contents):
                flags = 6  # PAGE_COMPRESSED | PAGE_COMPRESSED_HIGH
                payload = varint(len(contents) - len(compressed_data)) + compressed_data
            else:
                flags = 0
                payload = contents
        else:
            flags = 0
            payload = contents
        prefix = varint(page_number) + varint(mapid) + varint(len(keys)) + bytes([flags])
        plen = 6 + len(prefix) + len(payload)
        offset = len(chunk)
        chk = (1 ^ (offset ^ (offset >> 16)) ^ (plen ^ (plen >> 16))) & 65535
        chunk.extend(struct.pack(">IH", plen, chk) + prefix + payload)
        page_number += 1
        # For test purposes, choose the large-page length code, which does not
        # affect the checksum/contents. (H2 can encode smaller capacity.)
        return (1 << 38) | (offset << 6) | (31 << 1)

    schema = "wallet_test"
    wallet_cols = [
        "id",
        "name",
        "label",
        "network",
        "policyType",
        "scriptType",
        "storedBlockHeight",
        "gapLimit",
        "watchLast",
        "birthDate",
        "birthHeight",
        "defaultPolicy",
    ]
    key_cols = [
        "id",
        "label",
        "source",
        "walletModel",
        "masterFingerprint",
        "derivationPath",
        "extendedPublicKey",
        "wallet",
        "index",
        "seed",
        "masterPrivateExtendedKey",
    ]
    policy_cols = ["id", "name", "script"]
    tables = [
        (74, "wallet", wallet_cols, [[1, "Synthetic", None, network, 0, 6, 0, 25, 0, None, None, 24]]),
        (
            16,
            "keystore",
            key_cols,
            [
                [
                    7,
                    "Signer",
                    2,
                    0,
                    None,
                    f"m/84h/{int(network != 0)}h/0h",
                    None,
                    1,
                    0,
                    42 if mnemonic else None,
                    None,
                ]
            ],
        ),
        (24, "policy", policy_cols, [[24, "Default", "wpkh(Signer)"]]),
    ]
    if mnemonic:
        tables.append((25, "seed", ["id", "type", "mnemonicString"], [[42, 0, mnemonic]]))
    roots = {}
    map_names = {}
    mid = 5
    # Construct each table's B-tree leaf and map catalog registration.
    for tid, _name, _cols, rows in tables:
        roots[mid] = make_page(mid, list(range(1, len(rows) + 1)), rows, "long", "row")
        map_names[f"name.table.{tid}"] = format(mid, "x")
        mid += 1
    sql_rows = []
    for tid, name, cols, _rows in tables:
        sql = (
            'CREATE CACHED TABLE "'
            + schema
            + '"."'
            + name
            + '"(\n'
            + ",\n".join('    "' + col + '" CHARACTER VARYING(255)' for col in cols)
            + "\n)"
        )
        sql_rows.append([tid, 0, 0, sql])
    root_sql = make_page(mid, list(range(1, len(sql_rows) + 1)), sql_rows, "long", "row", compressed=True)
    map_names["name.table.0"] = format(mid, "x")
    roots[mid] = root_sql
    mid += 1
    meta_keys = sorted(map_names)
    meta_root = make_page(mid, meta_keys, [map_names[x] for x in meta_keys], compressed=True)
    roots[mid] = meta_root
    mid += 1
    # MAP 0 layout includes map root pointers, and meta.id.
    layout = {"meta.id": format(mid - 1, "x")}
    for id_, pos in roots.items():
        layout[f"root.{id_:x}"] = format(pos, "x")
    ordered = sorted(layout)
    root_layout = make_page(0, ordered, [layout[x] for x in ordered], compressed=True)
    num_blocks = 3
    chunk.extend(b"\0" * (num_blocks * 4096 - len(chunk)))
    line = (
        f"chunk:1,block:2,len:{num_blocks:x},map:{mid:x},max:0,pages:{page_number:x},"
        f"root:{root_layout:x},time:1,version:1,toc:0\n"
    ).encode("ascii")
    chunk[: len(line)] = line
    first = header("H:2,block:2,blockSize:1000,chunk:1,clean:1,created:1,format:2,version:1")
    return first + first + bytes(chunk)


def test_synthetic_h2_read_only_import_without_java(tmp_path):
    db = tmp_path / "sample.mv.db"
    db.write_bytes(sample_mvstore_file())
    extracted = extract_sparrow_h2_rows_python(db)
    assert extracted["format"] == "sparrow-h2-rows-v1"
    assert len(extracted["schemas"]) == 1
    section = extracted["schemas"][0]
    assert section["wallet"][0]["name"] == "Synthetic"
    assert section["policy"][0]["script"] == "wpkh(Signer)"
    assert section["keystore"][0]["seed"] is None
    assert section["keystore"][0]["extendedPublicKey"] is None
    wallets = load_file(db, hint="sparrow")
    assert len(wallets) == 1
    assert wallets[0].network == "mainnet"
    assert "mnemonicString" not in wallets[0].to_json()
    assert "seed" not in extracted["schemas"][0]  # no private seed table


@pytest.mark.parametrize("network", [0, 2])
def test_sparrow_seed_recovery_is_automatic(tmp_path: Path, network: int) -> None:
    from bitcoin_safe.wallet_import.sparrow_h2 import load_sparrow_h2
    from tests.non_gui.wallet_import.test_sparrow_seed_public import SYNTHETIC_WORDS

    db = tmp_path / "seed.mv.db"
    db.write_bytes(sample_mvstore_file(network, SYNTHETIC_WORDS))
    wallet = load_file(db, hint="sparrow")[0]
    assert wallet.descriptor and wallet.keystores[0].fingerprint
    assert wallet.keystores[0].non_mainnet_seed == (SYNTHETIC_WORDS if network else None)
    assert (SYNTHETIC_WORDS in wallet.to_json()) == bool(network)
    with pytest.raises(ExchangeError, match="mandatory"):
        load_sparrow_h2(db, derive_public_from_seeds=False)
    with pytest.raises(ExchangeError, match="mandatory"):
        load_file(db, hint="sparrow", derive_public_from_seeds=False)


def test_h2_header_accepts_unpadded_checksum_and_rejects_invalid_values() -> None:
    prefix = next(
        f"H:2,created:{i:x}".encode()
        for i in range(20000)
        if 0x1000000 <= _fletcher32(f"H:2,created:{i:x}".encode()) < 0x10000000
    )
    checksum = _fletcher32(prefix)
    assert _MVStore._header(prefix + f",fletcher:{checksum:x}\n".encode(), True)["H"] == "2"
    for value in (f"{checksum ^ 1:x}", "+1234567", "123456789", ""):
        with pytest.raises(H2DecodeError):
            _MVStore._header(prefix + f",fletcher:{value}\n".encode(), True)


def test_synthetic_h2_corrupt_page_rejected(tmp_path):
    file = tmp_path / "corrupt.mv.db"
    raw = bytearray(sample_mvstore_file())
    raw[8192 + 128 + 5] ^= 1  # damage checksum of first table page
    file.write_bytes(raw)
    with pytest.raises(H2DecodeError, match="checksum"):
        extract_sparrow_h2_rows_python(file)


def test_h2_rejects_page_from_an_unexpected_map():
    store = _MVStore(sample_mvstore_file())
    root = int(store.layout["root.5"], 16)
    with pytest.raises(H2DecodeError, match="unexpected map"):
        store.map_at(root, "long", "row", columns=12, expected_id=999)


def test_h2_rejects_unfinished_transaction(tmp_path):
    raw = bytearray(sample_mvstore_file())
    # First page has a one-byte page number, map id, row count, flag and key.
    raw[8192 + 128 + 6 + 4 + 1] = 1
    file = tmp_path / "unfinished.mv.db"
    file.write_bytes(raw)
    with pytest.raises(H2DecodeError, match="unfinished transactions"):
        extract_sparrow_h2_rows_python(file)


def test_h2_decoder_various_values_and_lzf():
    from bitcoin_safe.wallet_import.h2_python import _h2_value

    r = _BinaryReader(val(None) + val(False) + val(True) + val(-13) + val(255) + val("hello") + val(b"abc"))
    assert [_h2_value(r) for _ in range(7)] == [None, False, True, -13, 255, "hello", b"abc"]
    assert r.pos == len(r.data)
    # LZF literal: 3 bytes abc, then back-reference to repeat abc (3 bytes)
    assert _expand_lzf(b"\x02abc\x20\x02", 6) == b"abcabc"
    with pytest.raises(H2DecodeError):
        _expand_lzf(b"\x20\x02", 3)


def test_h2_xts_sector_matches_independent_cipher():
    key = hashlib.sha256(b"synthetic file key").digest()[:16]
    for number in (0, 1, 15):
        plain = b"a" * 4096
        tweak = bytearray(_aes_block(key, number.to_bytes(16, "little")))
        cipher = bytearray()
        for off in range(0, len(plain), 16):
            x = bytes(a ^ b for a, b in zip(plain[off : off + 16], tweak, strict=True))
            y = _aes_block(key, x)
            cipher.extend(a ^ b for a, b in zip(y, tweak, strict=True))
            carry = 0
            for j in range(16):
                n = tweak[j] * 2 + carry
                tweak[j] = n & 255
                carry = n >> 8
            if carry:
                tweak[0] ^= 0x87
        assert _xts_decrypt_sector(key, number, bytes(cipher)) == plain


def test_h2_synthetic_encrypted_wrong_password(tmp_path):
    from bitcoin_safe.wallet_import.h2_python import _plaintext_store
    from bitcoin_safe.wallet_import.sparrow_h2 import H2_MAGIC, H2_SPRW_MAGIC

    # Avoid the 256 MiB/10 iteration KDF cost for an isolated *synthetic* test.
    def fake(header: bytes, password: str):
        return "02" + ("11" if password == "correct" else "22") * 32

    with patch("bitcoin_safe.wallet_import.h2_python.sparrow_h2_file_password", fake):
        path = tmp_path / "encrypted.mv.db"
        salt = b"abcdefgh"
        header = H2_MAGIC + salt + H2_SPRW_MAGIC + b"z" * 16
        header += b"\0" * (4096 - len(header))
        derived = fake(header, "correct")
        key = hashlib.pbkdf2_hmac("sha256", derived.encode("utf-16-be"), salt, 10, dklen=16)
        cipher = Cipher(algorithms.AES(key), modes.ECB())
        encrypted = bytearray()
        plain = sample_mvstore_file()
        for idx in range(len(plain) // 4096):
            tweak = bytearray(_aes_block(key, idx.to_bytes(16, "little")))
            encrypt = cipher.encryptor()
            for off in range(0, 4096, 16):
                block = plain[idx * 4096 + off : idx * 4096 + off + 16]
                x = bytes(a ^ b for a, b in zip(block, tweak, strict=True))
                y = encrypt.update(x)
                encrypted += bytes(a ^ b for a, b in zip(y, tweak, strict=True))
                carry = 0
                for j in range(16):
                    n = tweak[j] * 2 + carry
                    tweak[j] = n & 255
                    carry = n >> 8
                if carry:
                    tweak[0] ^= 0x87
            encrypt.finalize()
        path.write_bytes(header + encrypted)
        assert _plaintext_store(path, "correct") == plain
        assert (
            extract_sparrow_h2_rows_python(path, password="correct")["schemas"][0]["wallet"][0]["name"]
            == "Synthetic"
        )
        with pytest.raises(H2DecodeError):
            _plaintext_store(path, None)
        with pytest.raises(H2DecodeError, match="Wrong Sparrow password"):
            _plaintext_store(path, "wrong")


@pytest.mark.skipif(not os.environ.get("SPARROW_H2_TEST_FILE"), reason="optional real backup")
def test_uploaded_sparrow_database_without_java():
    path = Path(os.environ["SPARROW_H2_TEST_FILE"])
    password = os.environ.get("WALLET_TEST_PASSWORD")
    wallets = load_file(path, password=password, hint="sparrow")
    assert wallets
    for w in wallets:
        assert "mnemonicString" not in w.to_json()
        assert "encryptedBytes" not in w.to_json()
