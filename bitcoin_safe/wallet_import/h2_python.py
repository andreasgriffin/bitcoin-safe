"""Pure-Python, read-only H2 2.x MVStore decoder for Sparrow public wallet data.

Supported and verified against an actual Sparrow 2.1.214 encrypted wallet:
- H2 FileEncrypt + Sparrow Argon2id password derivation and 4 KiB-sector AES/XTS
- MVStore block headers, chunk and page checks, B-tree nodes/leaves, LZF/DEFLATE
- H2 SQL catalog and *allowlisted* Sparrow table values using H2 ValueDataType

NO Java/JDBC, subprocess, database writes or generic SQL engine. Supported
BIP39 seeds are read in memory to recover public metadata. Mainnet seeds are
never retained, and `masterPrivateExtendedKey` is never opened.

Limitations: H2 changes its on-disk format between versions, not a general
purpose H2/SQL implementation. Unrecognized encodings fail closed rather than
silently producing potentially incorrect wallet descriptors. A newer/complex
file may require an export from Sparrow instead.

MVStore format source: h2database/h2database, tag version-2.1.214,
  org/h2/mvstore/{Page,Chunk,DataUtils}.java and
  org/h2/mvstore/{db/RowDataType,db/ValueDataType,tx/VersionedValueType}.java
H2 is dual licensed MPL-2.0 / EPL-1.0; this implementation is independent.
"""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .model import ExchangeError
from .sparrow_h2 import sparrow_h2_file_password

# An H2 file may be larger, but reading a huge untrusted binary into memory is
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
# not appropriate here. Typical Sparrow wallet metadata is far below 256 MiB.
MAX_H2_FILE = 256 * 1024 * 1024
MAX_PAGE = 32 * 1024 * 1024
MAX_COLUMNS = 256
MAX_ROWS_PER_TABLE = 300_000
MAX_SCHEMAS = 200
BLOCK = 4096

# Only public columns are exported. Notably,
# privateKey, mnemonicString, encryptedBytes and similar columns are excluded.
PUBLIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "wallet": (
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
    ),
    "policy": ("id", "name", "script"),
    "keystore": (
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
    ),
    "walletNode": ("id", "derivationPath", "label", "wallet", "parent", "addressData"),
    "blockTransactionHashIndex": (
        "id",
        "hash",
        "height",
        "label",
        "index",
        "outputValue",
        "status",
        "spentBy",
        "node",
    ),
    "blockTransaction": ("id", "txid", "height", "label", "wallet"),
    "detachedLabel": ("entry", "label"),
    "externalOutputLabel": ("txid", "index", "label"),
}
HEX_COLUMNS = frozenset(("hash", "txid", "addressData"))
CREATE_TABLE = re.compile(
    r'^CREATE\s+(?:(?:CACHED|MEMORY)\s+)?TABLE\s+"((?:[^"]|"")+)"\."((?:[^"]|"")+)"\s*\(',
    re.IGNORECASE,
)
COLUMN_NAME = re.compile(r'^\s*"((?:[^"]|"")+)"\s+\S', re.MULTILINE)


class H2DecodeError(ExchangeError):
    """Unsupported/corrupted on-disk H2 binary; never quotes source content."""


class _BinaryReader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def read(self, length: int) -> bytes:
        if length < 0 or length > MAX_PAGE or self.pos + length > len(self.data):
            raise H2DecodeError("Truncated or oversized H2 value")
        value = self.data[self.pos : self.pos + length]
        self.pos += length
        return value

    def u8(self) -> int:
        return self.read(1)[0]

    def uint(self, width: int) -> int:
        return int.from_bytes(self.read(width), "big")

    def sint(self, width: int) -> int:
        return int.from_bytes(self.read(width), "big", signed=True)

    def varint(self) -> int:
        result = 0
        for i in range(10):
            n = self.u8()
            result |= (n & 127) << (7 * i)
            if not n & 128:
                return result
        raise H2DecodeError("Invalid H2 variable-length integer")

    def string(self, size: int | None = None) -> str:
        """H2 DataUtils' modified-UTF8 string (number of UTF-16 chars)."""
        size = self.varint() if size is None else size
        if size > 1_000_000:
            raise H2DecodeError("Excessively long H2 string")
        chars = []
        for _ in range(size):
            x = self.u8()
            if x < 0x80:
                codepoint = x
            elif x >= 0xE0:
                codepoint = ((x & 15) << 12) | ((self.u8() & 63) << 6) | (self.u8() & 63)
            else:
                codepoint = ((x & 31) << 6) | (self.u8() & 63)
            chars.append(chr(codepoint))
        # Java's char[] preserves UTF-16 code units; Python should reconstruct
        # supplementary characters (e.g. emoji labels) from surrogate pairs.
        raw = "".join(chars)
        return raw.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")

    def varbytes(self) -> bytes:
        return self.read(self.varint())


def _fletcher32(src: bytes) -> int:
    """H2 DataUtils.getFletcher32, for validating MVStore file headers."""
    s1 = s2 = 0xFFFF
    for i in range(0, len(src), 720):
        segment = src[i : i + 720]
        for k in range(0, len(segment), 2):
            word = (segment[k] << 8) | (segment[k + 1] if k + 1 < len(segment) else 0)
            s1 += word
            s2 += s1
        s1 = (s1 & 65535) + (s1 >> 16)
        s2 = (s2 & 65535) + (s2 >> 16)
    s1 = (s1 & 65535) + (s1 >> 16)
    s2 = (s2 & 65535) + (s2 >> 16)
    return ((s2 << 16) | s1) & 0xFFFFFFFF


def _xts_decrypt_sector(key: bytes, number: int, payload: bytes) -> bytes:
    """Match H2's XTS class (AES-128 for *both* the data and tweak key)."""
    if not payload or len(payload) % 16:
        raise H2DecodeError("Invalid Sparrow H2 encrypted block")
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encrypter, decrypter = cipher.encryptor(), cipher.decryptor()
    tweak = bytearray(encrypter.update(number.to_bytes(16, "little")))
    plain = bytearray(len(payload))
    try:
        for offset in range(0, len(payload), 16):
            block = bytes(a ^ b for a, b in zip(payload[offset : offset + 16], tweak, strict=True))
            unmasked = decrypter.update(block)
            plain[offset : offset + 16] = bytes(a ^ b for a, b in zip(unmasked, tweak, strict=True))
            carry = 0
            for j in range(16):
                doubled = (tweak[j] << 1) + carry
                tweak[j] = doubled & 255
                carry = doubled >> 8
            if carry:
                tweak[0] ^= 0x87
        encrypter.finalize()
        decrypter.finalize()
        return bytes(plain)
    finally:
        # This buffer can contain mainnet mnemonics/private keys from H2 pages.
        # Clear mutable scratch storage even if sector decryption raises.
        plain[:] = b"\x00" * len(plain)
        tweak[:] = b"\x00" * len(tweak)


def _plaintext_store(path: str | Path, password: str | None) -> bytes:
    source = Path(path)
    if source.stat().st_size > MAX_H2_FILE:
        raise H2DecodeError("Sparrow H2 database exceeds the Python reader's 256 MiB limit")
    raw = source.read_bytes()
    if raw.startswith((b"H:2,", b"H:2:")):
        if password is not None:
            raise H2DecodeError("Sparrow H2 database is not encrypted; omit --ask-password")
        return raw
    if not raw.startswith(b"H2encrypt\n") or len(raw) < BLOCK * 4 or len(raw) % BLOCK:
        raise H2DecodeError("Not a recognized Sparrow-encrypted H2 database")
    if not password:
        raise H2DecodeError("Encrypted Sparrow H2 database requires --ask-password")
    derived = sparrow_h2_file_password(raw[:BLOCK], password)
    file_key = hashlib.pbkdf2_hmac(
        "sha256",
        derived.encode("utf-16-be"),
        raw[10:18],
        10,
        dklen=16,
    )
    plain = b"".join(
        _xts_decrypt_sector(file_key, i, raw[(i + 1) * BLOCK : (i + 2) * BLOCK])
        for i in range(len(raw) // BLOCK - 1)
    )
    if not plain.startswith(b"H:2,"):
        raise H2DecodeError("Wrong Sparrow password or corrupted H2 database")
    return plain


def _expand_lzf(raw: bytes, expected: int) -> bytes:
    """H2 CompressLZF, read-only expansion with size and backref checks."""
    if expected < 0 or expected > MAX_PAGE:
        raise H2DecodeError("Excessive H2 LZF expansion size")
    reader = _BinaryReader(raw)
    out = bytearray()
    while len(out) < expected:
        control = reader.u8()
        if control < 32:
            out += reader.read(control + 1)
        else:
            length = control >> 5
            if length == 7:
                length += reader.u8()
            length += 2
            delta = -((control & 31) << 8) - 1 - reader.u8()
            start = len(out) + delta
            if start < 0:
                raise H2DecodeError("Invalid H2 LZF back-reference")
            for j in range(length):
                out.append(out[start + j])
        if len(out) > expected:
            raise H2DecodeError("H2 LZF page length mismatch")
    if reader.pos != len(raw):
        raise H2DecodeError("H2 LZF page contains unexpected trailing bytes")
    return bytes(out)


def _reverse_bits(number: int, bits: int) -> int:
    return int(f"{number:0{bits}b}"[::-1], 2)


def _h2_date_value(encoded: int) -> str | None:
    year, month, day = encoded >> 9, (encoded >> 5) & 15, encoded & 31
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _h2_value(reader: _BinaryReader) -> Any:
    """Decode H2 ValueDataType, never Java-deserialize JAVA_OBJECT values."""
    type_code = reader.u8()
    if type_code == 0:
        return None
    if type_code == 64:
        return False
    if type_code == 65:
        return True
    if 32 <= type_code < 48:
        return type_code - 32
    if 48 <= type_code < 56:
        return type_code - 48
    if 68 <= type_code < 100:
        return reader.string(type_code - 68)
    if 100 <= type_code < 132:
        return reader.read(type_code - 100)
    if type_code == 66:
        return -reader.varint()
    if type_code == 67:
        return -reader.varint()
    if type_code == 2:
        return reader.sint(1)
    if type_code == 3:
        return reader.sint(2)
    if type_code in (4, 5, 25):
        return reader.varint()
    if type_code in (12, 19, 22, 134, 137):
        return reader.varbytes()
    if type_code in (13, 14, 21):
        return reader.string()
    if type_code == 20:
        return str(UUID(bytes=reader.read(16)))
    if type_code == 10:
        return _h2_date_value(reader.varint())
    if type_code in (9, 11, 24, 135, 136):
        # Timestamps and times are read to maintain row boundaries; these are
        # nonessential metadata, and the converter accepts JSON strings/null.
        if type_code == 9:
            return ("H2_TIME", reader.varint() * 1_000_000 + reader.varint())
        encoded_date, nanos = (
            (None if type_code == 136 else reader.varint()),
            (reader.varint() * 1_000_000 + reader.varint()),
        )
        if type_code == 11:
            return ("H2_TIMESTAMP", encoded_date, nanos)
        if type_code == 24:
            return ("H2_TIMESTAMP_TZ", encoded_date, nanos, reader.varint() * 60)
        zone = reader.sint(1)
        if zone == 127:
            zone = reader.varint()
        elif zone == -128:
            zone = -reader.varint()
        else:
            zone *= 900
        return ("H2_TIME_TZ" if type_code == 136 else "H2_TIMESTAMP_TZ", encoded_date, nanos, zone)
    if type_code in (56, 60, 62):
        return 0
    if type_code in (57, 61, 63):
        return 1
    if type_code == 58:
        return reader.varint()
    if type_code == 59:
        scale = reader.varint()
        if scale > 100:
            raise H2DecodeError("Unsupported H2 numeric scale")
        return reader.varint() / 10**scale
    if type_code == 6:
        scale = reader.varint()
        if scale > 100:
            raise H2DecodeError("Unsupported H2 decimal scale")
        return int.from_bytes(reader.varbytes(), "big", signed=True) / 10**scale
    if type_code == 7:
        return struct.unpack(">d", _reverse_bits(reader.varint(), 64).to_bytes(8, "big"))[0]
    if type_code == 8:
        return struct.unpack(">f", _reverse_bits(reader.varint(), 32).to_bytes(4, "big"))[0]
    if type_code in (15, 16):
        size = reader.varint()
        if size >= 0:
            data = reader.read(size)
            if type_code == 16:
                reader.varint()  # character length
            return data
        raise H2DecodeError("External H2 LOBs are unsupported in the read-only importer")
    if type_code in (17, 27):
        size = reader.varint()
        if size > MAX_COLUMNS:
            raise H2DecodeError("Excessive H2 array / row length")
        return [_h2_value(reader) for _ in range(size)]
    raise H2DecodeError(f"Unsupported H2 value encoding code {type_code}")


class _MVStore:
    def __init__(self, payload: bytes) -> None:
        self.data = payload
        if len(payload) < BLOCK * 3 or len(payload) % BLOCK:
            raise H2DecodeError("Truncated H2 MVStore file")
        headers = []
        for offset in (0, BLOCK):
            try:
                headers.append(self._header(payload[offset : offset + BLOCK], verify=True))
            except H2DecodeError:
                pass
        if not headers or not any(h.get("H") == "2" for h in headers):
            raise H2DecodeError("Invalid or corrupted H2 MVStore file header")
        if not all(h.get("format") in ("2", "3") for h in headers):
            raise H2DecodeError("Unsupported H2 MVStore file format")
        self.chunks: dict[int, tuple[int, dict[str, str]]] = {}
        for offset in range(2 * BLOCK, len(payload), BLOCK):
            if not payload[offset : offset + 6] == b"chunk:":
                continue
            try:
                header = self._header(payload[offset : offset + BLOCK], verify=False)
                chunk_id = int(header["chunk"], 16)
                length = int(header["len"], 16)
                if not 0 < length <= (len(payload) - offset) // BLOCK:
                    continue
                if int(header["block"], 16) * BLOCK != offset:
                    continue
                self.chunks[chunk_id] = (offset, header)
            except (KeyError, ValueError, H2DecodeError):
                continue
        if not self.chunks:
            raise H2DecodeError("No valid MVStore chunks found")
        current_chunk = max(self.chunks.values(), key=lambda entry: int(entry[1].get("version", "0"), 16))
        layout_root = int(current_chunk[1]["root"], 16)
        self.layout = dict(self.map_at(layout_root, key_kind="str", value_kind="str"))
        if "meta.id" not in self.layout:
            raise H2DecodeError("Unsupported H2 layout: missing SQL metadata map")
        self.meta_id = int(self.layout["meta.id"], 16)
        self.meta = dict(self.map_id(self.meta_id, key_kind="str", value_kind="str"))

    @staticmethod
    def _header(payload: bytes, verify: bool) -> dict[str, str]:
        line = payload.split(b"\n", 1)[0].strip()
        if len(line) > 512 or not line:
            raise H2DecodeError("Invalid H2 block header")
        if verify:
            prefix, sep, checksum = line.partition(b",fletcher:")
            if not sep or not (1 <= len(checksum) <= 8) or not re.fullmatch(rb"[0-9a-fA-F]+", checksum):
                raise H2DecodeError("Missing or malformed H2 block-header checksum")
            number = int(checksum, 16)
            if _fletcher32(prefix) != number:
                raise H2DecodeError("Corrupted H2 block header")
        try:
            return dict(item.split(":", 1) for item in line.decode("latin-1").split(",") if ":" in item)
        except ValueError as exc:
            raise H2DecodeError("Malformed H2 block header") from exc

    def _page(
        self, page_pos: int, key_kind: str, value_kind: str, count: int | None
    ) -> tuple[int, list[int], list[Any], list[Any] | None]:
        chunk_id = page_pos >> 38
        offset = (page_pos >> 6) & 0xFFFFFFFF
        if chunk_id not in self.chunks:
            raise H2DecodeError("MVStore references missing chunk")
        chunk_start, chunk_header = self.chunks[chunk_id]
        if offset >= int(chunk_header["len"], 16) * BLOCK:
            raise H2DecodeError("Page offset outside its H2 chunk")
        reader = _BinaryReader(self.data, chunk_start + offset)
        page_start = reader.pos
        page_length = reader.uint(4)
        page_checksum = reader.uint(2)
        max_chunk_end = chunk_start + int(chunk_header["len"], 16) * BLOCK
        if not 8 <= page_length <= min(MAX_PAGE, len(self.data) - page_start, max_chunk_end - page_start):
            raise H2DecodeError("Invalid MVStore page length")
        check = (
            ((chunk_id >> 16) ^ chunk_id) ^ ((offset >> 16) ^ offset) ^ ((page_length >> 16) ^ page_length)
        )
        if page_checksum != (check & 65535):
            raise H2DecodeError("MVStore page checksum mismatch")
        reader = _BinaryReader(self.data[page_start : page_start + page_length], 6)
        reader.varint()  # Page sequence number within the chunk.
        map_id = reader.varint()
        n = reader.varint()
        page_flags = reader.u8()
        if n > MAX_ROWS_PER_TABLE or bool(page_flags & 1) != bool(page_pos & 1):
            raise H2DecodeError("Invalid H2 MVStore page type or record count")
        children = []
        if page_flags & 1:
            children = [reader.uint(8) for _ in range(n + 1)]
            for _ in children:
                reader.varint()  # Descendant counts, not used in read-only traversal.
        if page_flags & 2:
            extra_length = reader.varint()
            encoded = reader.data[reader.pos :]
            target_length = len(encoded) + extra_length
            if not 0 < target_length <= MAX_PAGE:
                raise H2DecodeError("Invalid H2 compressed page size")
            if page_flags & 4:
                try:
                    # Bound decompression before allocating: wallet files are
                    # untrusted and a malformed DEFLATE page could otherwise
                    # cause unbounded decompressed output.
                    decompressor = zlib.decompressobj()
                    uncompressed = decompressor.decompress(encoded, target_length + 1)
                except (zlib.error, ValueError) as exc:
                    raise H2DecodeError("Corrupt H2 DEFLATE page") from exc
                if (
                    len(uncompressed) != target_length
                    or not decompressor.eof
                    or decompressor.unused_data
                    or decompressor.unconsumed_tail
                ):
                    raise H2DecodeError("H2 DEFLATE page length mismatch")
            else:
                uncompressed = _expand_lzf(encoded, target_length)
            reader = _BinaryReader(uncompressed)
        else:
            reader = _BinaryReader(reader.data[reader.pos :])
        if key_kind == "str":
            keys: list[Any] = [reader.string() for _ in range(n)]
        elif key_kind == "long":
            keys = [reader.varint() for _ in range(n)]
        else:
            raise H2DecodeError("Unsupported H2 map key type")
        if page_flags & 1:
            return map_id, children, keys, None
        if value_kind == "str":
            values: list[Any] = [reader.string() for _ in range(n)]
        elif value_kind == "row":
            if count is None or not 0 < count <= MAX_COLUMNS:
                raise H2DecodeError("Invalid H2 row column count")
            # MVPrimaryIndex values use VersionedValueType<RowDataType>.
            # Fast-path: one tag 0 then N rows. Slow-path: one tag 1 then
            # per-row operationId/flags and current/committed versions.
            bulk = reader.u8()
            if bulk == 0:
                values = [[_h2_value(reader) for _ in range(count)] for _ in range(n)]
            elif bulk == 1:
                values = []
                for _ in range(n):
                    op_id = reader.varint()
                    if op_id == 0:
                        values.append([_h2_value(reader) for _ in range(count)])
                        continue
                    # Do not guess which version of an unfinished transaction
                    # belongs to a consistent wallet snapshot.
                    raise H2DecodeError(
                        "Sparrow database contains unfinished transactions; close Sparrow and retry"
                    )
            else:
                raise H2DecodeError("Unsupported H2 transaction row encoding")
        else:
            raise H2DecodeError("Unsupported H2 map value type")
        if reader.pos != len(reader.data):
            raise H2DecodeError("Trailing bytes in H2 page payload")
        return map_id, children, keys, values

    def map_at(
        self,
        page_pos: int,
        key_kind: str,
        value_kind: str,
        columns: int | None = None,
        expected_id: int | None = None,
    ) -> list[tuple[Any, Any]]:
        seen: set[int] = set()
        all_rows: list[tuple[Any, Any]] = []

        def walk(pos: int) -> None:
            nonlocal expected_id
            if pos in seen or len(seen) > 100_000:
                raise H2DecodeError("MVStore page cycle or excessive page count")
            seen.add(pos)
            map_id, children, keys, values = self._page(pos, key_kind, value_kind, columns)
            if expected_id is None:
                expected_id = map_id
            elif map_id != expected_id:
                raise H2DecodeError("H2 B-tree page belongs to an unexpected map")
            if values is None:
                for child in children:
                    if child:
                        walk(child)
            else:
                all_rows.extend((k, v) for k, v in zip(keys, values, strict=True) if v is not None)
            if len(all_rows) > MAX_ROWS_PER_TABLE:
                raise H2DecodeError("H2 table row limit exceeded")

        if page_pos:
            walk(page_pos)
        return all_rows

    def map_id(
        self, map_id: int, key_kind: str, value_kind: str, columns: int | None = None
    ) -> list[tuple[Any, Any]]:
        root_pos = self.layout.get(f"root.{map_id:x}")
        if not root_pos:
            return []
        rows = self.map_at(
            int(root_pos, 16), key_kind=key_kind, value_kind=value_kind, columns=columns, expected_id=map_id
        )
        return rows

    def table_catalog(self) -> list[tuple[str, str, int, list[str]]]:
        meta_map_id = self.meta.get("name.table.0")
        if not meta_map_id:
            raise H2DecodeError("Missing H2 SQL catalog")
        rows = self.map_id(int(meta_map_id, 16), key_kind="long", value_kind="row", columns=4)
        result: list[tuple[str, str, int, list[str]]] = []
        for _, value in rows:
            if len(value) != 4 or not isinstance(value[0], int) or not isinstance(value[3], str):
                continue
            found = CREATE_TABLE.match(value[3])
            if not found:
                continue
            schema, table = (item.replace('""', '"') for item in found.groups())
            if not schema.startswith("wallet_") or not 8 <= len(schema) <= 255:
                continue
            if any(ord(c) < 32 or ord(c) == 127 for c in schema):
                continue
            if table not in PUBLIC_COLUMNS:
                continue
            columns = [name.replace('""', '"') for name in COLUMN_NAME.findall(value[3])]
            if not 0 < len(columns) <= MAX_COLUMNS or len(set(columns)) != len(columns):
                raise H2DecodeError("Unsupported H2 SQL catalog column layout")
            result.append((schema, table, value[0], columns))
        return result

    def public_rows(self) -> dict[str, Any]:
        grouped: dict[str, dict[str, Any]] = {}
        for schema, table, table_id, columns in self.table_catalog():
            by_name = self.meta.get("name.table." + str(table_id))
            if by_name is None:
                raise H2DecodeError("H2 catalog is missing a wallet table map")
            map_id = int(by_name, 16)
            rows = self.map_id(map_id, key_kind="long", value_kind="row", columns=len(columns))
            out: list[dict[str, Any]] = []
            approved = PUBLIC_COLUMNS[table]
            for _, values in rows:
                if len(values) != len(columns):
                    raise H2DecodeError("H2 row does not match the table's declared columns")
                item: dict[str, Any] = {}
                for name, val in zip(columns, values, strict=True):
                    if name not in approved:
                        continue
                    if name in ("seed", "masterPrivateExtendedKey"):
                        # These are foreign keys, NEVER dereference them.
                        if val is not None and not isinstance(val, int):
                            raise H2DecodeError("Unexpected H2 private-key reference type")
                        item[name] = val
                    elif isinstance(val, bytes):
                        if name not in HEX_COLUMNS:
                            raise H2DecodeError("Unexpected H2 binary public column")
                        item[name] = val.hex()
                    elif isinstance(val, tuple):
                        # Non-essential timestamp values: no secret is present.
                        item[name] = None
                    elif val is None or isinstance(val, (bool, int, str)):
                        item[name] = val
                    else:
                        raise H2DecodeError("Unsupported H2 public column value")
                out.append(item)
            section = grouped.setdefault(schema, {"schema": schema})
            if table in section:
                raise H2DecodeError("Duplicate H2 Sparrow catalog table")
            section[table] = out
        if len(grouped) > MAX_SCHEMAS:
            raise H2DecodeError("Excessive Sparrow wallet schema count")
        # Ignore internal wallet_ schemas that have no wallet table. Do not
        # invent empty wallets; a wallet table is mandatory for conversion.
        schemas = [section for section in grouped.values() if "wallet" in section]
        if not schemas:
            raise H2DecodeError("No Sparrow wallet tables found in H2 database")
        return {"format": "sparrow-h2-rows-v1", "schemas": schemas}


def extract_sparrow_h2_rows_python(
    path: str | Path,
    password: str | None = None,
    bip39_passphrase: str | None = None,
    bip39_passphrases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read public data and recover BIP39 metadata without Java or disk plaintext.

    To construct WalletExchange instances, pass the result to
    ``from_sparrow_h2_rows(..., filename=...)``. The result can contain
    test-network mnemonics and must be treated as sensitive.
    """
    try:
        store = _MVStore(_plaintext_store(path, password))
        data = store.public_rows()
        from .sparrow_seed_public import augment_public_rows_from_seeds

        augment_public_rows_from_seeds(
            store,
            data,
            password,
            bip39_passphrase=bip39_passphrase,
            bip39_passphrases=bip39_passphrases,
        )
        return data
    except ExchangeError:
        raise
    except (OverflowError, UnicodeError, struct.error, IndexError, KeyError, TypeError, ValueError) as exc:
        # Do not include input bytes, plaintext SQL, wallet secrets, or passwords.
        raise H2DecodeError("Corrupt or unsupported Sparrow H2 database") from exc
