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

"""Password-based decryption of *legacy Sparrow JSON* SPRW1 files.

Source: Sparrow JsonPersistence and Drongo Argon2KeyDeriver/ECIESKeyCrypter:
base64("SPRW1" + 16-byte salt) || base64(BIE1 + ephemeral33 +
AES-128-CBC-PKCS7(ciphertext) + HMAC-SHA256).

Legacy format only. Newer H2 '.mv.db' support is in sparrow_h2.py.
No brute-force, no disk plaintext, no seed export.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import zlib

from .model import ExchangeError

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _point_from_compressed(pub: bytes) -> tuple[int, int]:
    if len(pub) != 33 or pub[0] not in (2, 3):
        raise ExchangeError("Malformed ephemeral secp256k1 public key")
    x = int.from_bytes(pub[1:], "big")
    if x >= P:
        raise ExchangeError("Invalid ephemeral point")
    y = pow((x * x * x + 7) % P, (P + 1) // 4, P)
    if y * y % P != (x * x * x + 7) % P:
        raise ExchangeError("Invalid ephemeral point")
    if y & 1 != pub[0] & 1:
        y = P - y
    return x, y


def _point_add(a: tuple[int, int] | None, b: tuple[int, int] | None) -> tuple[int, int] | None:
    if a is None:
        return b
    if b is None:
        return a
    x1, y1 = a
    x2, y2 = b
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    slope = ((3 * x1 * x1 * pow(2 * y1, -1, P)) if a == b else ((y2 - y1) * pow(x2 - x1, -1, P))) % P
    x3 = (slope * slope - x1 - x2) % P
    return x3, (slope * (x1 - x3) - y1) % P


def _scalar_mul(k: int, p: tuple[int, int]) -> tuple[int, int]:
    if not 1 <= k < N:
        raise ExchangeError("Invalid decryption scalar")
    acc: tuple[int, int] | None = None
    while k:
        if k & 1:
            acc = _point_add(acc, p)
        p2 = _point_add(p, p)
        if p2 is None:
            raise ExchangeError("Invalid point double")
        p = p2
        k >>= 1
    if acc is None:
        raise ExchangeError("Invalid derived ECDH point")
    return acc


def _compressed(point: tuple[int, int]) -> bytes:
    x, y = point
    return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")


def _inflate_limited(raw: bytes, maximum: int = 40 * 1024 * 1024) -> bytes:
    dec = zlib.decompressobj()
    try:
        data = dec.decompress(raw, maximum + 1)
        if len(data) > maximum or dec.unconsumed_tail:
            raise ExchangeError("Decrypted JSON exceeds safe size")
        data += dec.flush(maximum + 1 - len(data))
    except zlib.error as exc:
        raise ExchangeError("Decrypted file is not a valid Sparrow compressed wallet") from exc
    if len(data) > maximum or not dec.eof or dec.unused_data:
        raise ExchangeError("Decrypted wallet has truncated/excess data")
    return data


def decrypt_sprw1(data: bytes, password: str, _test_costs: tuple[int, int, int] | None = None) -> bytes:
    """Decrypt a legacy Sparrow encrypted JSON wallet in memory.

    Requires `argon2-cffi`, `cryptography` (install from requirements.txt).
    Production settings: Argon2id iterations=10, memory=262144 KiB, parallelism=4.
    `_test_costs` is ONLY for producing/reading synthetic test fixtures.
    """
    try:
        from argon2.low_level import Type, hash_secret_raw
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
    except ImportError as exc:
        raise ExchangeError("Sparrow decryption requires argon2-cffi and cryptography") from exc
    if not isinstance(password, str) or not password:
        raise ExchangeError("Enter a non-empty Sparrow wallet password")
    if len(data) < 29 or len(data) > 30 * 1024 * 1024:
        raise ExchangeError("Invalid size for SPRW1 wallet")
    try:
        header = base64.b64decode(data[:28], validate=True)
    except ValueError as exc:
        raise ExchangeError("Malformed Sparrow SPRW1 header") from exc
    if len(header) != 21 or not header.startswith(b"SPRW1"):
        raise ExchangeError("Not a legacy encrypted Sparrow JSON file")
    salt = header[5:]
    costs = _test_costs if _test_costs is not None else (10, 256 * 1024, 4)
    secret = hash_secret_raw(
        password.encode("utf-8"),
        salt,
        time_cost=costs[0],
        memory_cost=costs[1],
        parallelism=costs[2],
        hash_len=32,
        type=Type.ID,
    )
    d = int.from_bytes(secret, "big")
    try:
        packet = base64.b64decode(data[28:], validate=True)
    except ValueError as exc:
        raise ExchangeError("Malformed Sparrow ECIES payload") from exc
    if len(packet) < 4 + 33 + 16 + 32 or packet[:4] != b"BIE1":
        raise ExchangeError("Invalid Sparrow ECIES header")
    ciphertext = packet[37:-32]
    if len(ciphertext) % 16:
        raise ExchangeError("Invalid Sparrow ciphertext length")
    public = _point_from_compressed(packet[4:37])
    shared = _compressed(_scalar_mul(d, public))
    keymaterial = hashlib.sha512(shared).digest()
    iv, key_e, key_m = keymaterial[:16], keymaterial[16:32], keymaterial[32:64]
    if not hmac.compare_digest(hmac.new(key_m, packet[:-32], hashlib.sha256).digest(), packet[-32:]):
        raise ExchangeError("Wrong Sparrow password or corrupted wallet")
    decryptor = Cipher(algorithms.AES(key_e), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    try:
        unpadder = PKCS7(128).unpadder()
        raw = unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise ExchangeError("Invalid decrypted Sparrow ciphertext") from exc
    return _inflate_limited(raw)


def is_sprw1(data: bytes) -> bool:
    try:
        return base64.b64decode(data[:28], validate=True).startswith(b"SPRW1")
    except (ValueError, TypeError):
        return False
