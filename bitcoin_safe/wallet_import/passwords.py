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

"""Narrow, locally verified password support for public-only wallet migration.

Ledger Live Desktop native app.json AES-256-CBC password lock is handled in
ledger_live_db.py (not this module).

Wasabi's native KeyManager JSON holds a BIP38 non-EC-multiply encrypted
BitcoinEncryptedSecretNoEC. Unlocking/validating that secret does NOT make
recovering private keys necessary for public wallet import, so the private key
is never returned. BIP38 rules: https://github.com/bitcoin/bips/blob/master/bip-0038.mediawiki

"""

from __future__ import annotations

import hashlib
import hmac
import unicodedata
from typing import Any

from Crypto.Hash import RIPEMD160
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from hwilib._base58 import encode_check as b58encode_check

from .descriptors import b58decode_check
from .model import ExchangeError

SECP_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _hash160(data: bytes) -> bytes:
    return RIPEMD160.new(hashlib.sha256(data).digest()).digest()


def _sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def verify_wasabi_password(data: dict[str, Any], password: str) -> None:
    """Verify Wasabi's BIP38 EncryptedSecret against its network and fingerprint.

    Does not return the private key, seed, or any decrypted secret material. It
    validates both the BIP38 address-hash salt and (if present) the Wasabi
    master-key fingerprint. Only BIP38's non-EC scheme (01 42) is supported.
    """
    encrypted = data.get("EncryptedSecret")
    if not isinstance(password, str):
        raise ExchangeError("Wasabi password must be a string")
    if not isinstance(encrypted, str) or not encrypted:
        raise ExchangeError(
            "Wasabi watch-only JSON has no encrypted private key to verify; omit --ask-password"
        )
    try:
        payload = b58decode_check(encrypted)
    except ExchangeError as exc:
        raise ExchangeError(
            "Wasabi EncryptedSecret is not valid BIP38; cannot verify supplied password"
        ) from exc
    if len(payload) != 39 or payload[:2] != b"\x01\x42" or payload[2] not in (0xC0, 0xE0):
        raise ExchangeError("Unsupported Wasabi BIP38 encryption variant (expected non-EC 0142)")

    state = data.get("BlockchainState")
    if not isinstance(state, dict):
        raise ExchangeError("Wasabi BlockchainState is needed to verify the encrypted key")
    net = str(state.get("Network", "")).lower()
    if net in ("main", "mainnet"):
        addr_version = 0
    elif net in ("testnet", "testnet4", "signet", "regtest"):
        addr_version = 111
    else:
        raise ExchangeError("Unknown Wasabi network; cannot check BIP38 address hash safely")

    address_salt = payload[3:7]
    # BIP38 mandates NFC unicode normalization and scrypt N=16384, r=8, p=8.
    try:
        derived = hashlib.scrypt(
            unicodedata.normalize("NFC", password).encode("utf-8"),
            salt=address_salt,
            n=16384,
            r=8,
            p=8,
            dklen=64,
            maxmem=128 * 1024 * 1024,
        )
        dec = Cipher(algorithms.AES(derived[32:]), modes.ECB()).decryptor()
        key_bytes = bytearray(dec.update(payload[7:]) + dec.finalize())
        secret_bytes = bytearray(a ^ b for a, b in zip(key_bytes, derived[:32], strict=True))
        try:
            secret_scalar = int.from_bytes(secret_bytes, "big")
        finally:
            # Scratch contains a decrypted BIP38 private key; wipe immediately.
            key_bytes[:] = b"\x00" * len(key_bytes)
            secret_bytes[:] = b"\x00" * len(secret_bytes)
        if not 1 <= secret_scalar < SECP_N:
            raise ValueError("invalid secret scalar")
        private = ec.derive_private_key(secret_scalar, ec.SECP256K1())
        compressed = private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint
        )
        public_bytes = (
            compressed
            if payload[2] == 0xE0
            else private.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        )
        address = b58encode_check(bytes([addr_version]) + _hash160(public_bytes))
        if not hmac.compare_digest(address_salt, _sha256d(address.encode("ascii"))[:4]):
            raise ValueError("BIP38 address mismatch")
        expected_fp = data.get("MasterFingerprint")
        if expected_fp is not None:
            if not isinstance(expected_fp, str) or len(expected_fp) != 8:
                raise ExchangeError("Malformed Wasabi MasterFingerprint")
            try:
                fingerprint = bytes.fromhex(expected_fp)
            except ValueError as exc:
                raise ExchangeError("Malformed Wasabi MasterFingerprint") from exc
            if not hmac.compare_digest(fingerprint, _hash160(compressed)[:4]):
                raise ValueError("Wasabi root fingerprint mismatch")
    except (ValueError, MemoryError) as exc:
        raise ExchangeError(
            "Incorrect Wasabi BIP38 password or inconsistent encrypted key/fingerprint"
        ) from exc
