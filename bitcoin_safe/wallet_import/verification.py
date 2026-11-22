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

"""Public-only BIP32 address derivation for validating Electrum imports.

This is a verification helper, not a signing stack. Derives nonhardened child
pubkeys from account xpubs and validates stored receive/change addresses.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence

from Crypto.Hash import RIPEMD160
from hwilib._base58 import encode_check as b58encode_check

from .descriptors import b58decode_check
from .model import ExchangeError, Keystore
from .sparrow_crypto import N, _compressed, _point_add, _point_from_compressed, _scalar_mul
from .sparrow_h2 import _bech32_encode

G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def derive_pubkey(ks: Keystore, branch: int, index: int) -> bytes:
    if not ks.xpub or branch not in (0, 1) or not 0 <= index < 2**31:
        raise ExchangeError("Cannot derive a public wallet address")
    payload = b58decode_check(ks.xpub)
    if len(payload) != 78 or payload[45] not in (2, 3):
        raise ExchangeError("Invalid public extended key")
    chaincode, pub = payload[13:45], payload[45:78]
    for child in (branch, index):
        digest = hmac.new(chaincode, pub + child.to_bytes(4, "big"), hashlib.sha512).digest()
        scalar = int.from_bytes(digest[:32], "big")
        if not 0 < scalar < N:
            raise ExchangeError("Invalid BIP32 public derivation child")
        point = _point_add(_point_from_compressed(pub), _scalar_mul(scalar, G))
        if point is None:
            raise ExchangeError("Invalid BIP32 derived public point")
        pub, chaincode = _compressed(point), digest[32:]
    return pub


def _hash160(data: bytes) -> bytes:
    return RIPEMD160.new(hashlib.sha256(data).digest()).digest()


def address_from_public_keys(
    ks: Sequence[Keystore], script_type: str, network: str, branch: int, index: int, threshold: int = 1
) -> str:
    pubs = [derive_pubkey(k, branch, index) for k in ks]
    main = network == "mainnet"
    hrp = "bc" if main else "bcrt" if network == "regtest" else "tb"
    if len(pubs) == 1:
        keyhash = _hash160(pubs[0])
        if script_type == "pkh":
            return b58encode_check((b"\x00" if main else b"\x6f") + keyhash)
        if script_type == "wpkh":
            return _bech32_encode(hrp, 0, keyhash)
        if script_type == "sh-wpkh":
            return b58encode_check((b"\x05" if main else b"\xc4") + _hash160(b"\x00\x14" + keyhash))
        raise ExchangeError("Unsupported singlesig address type for public verification")
    if not 1 <= threshold <= len(pubs) <= 15:
        raise ExchangeError("Invalid multisig public policy")
    redeem = (
        bytes([0x50 + threshold])
        + b"".join(b"\x21" + p for p in sorted(pubs))
        + bytes([0x50 + len(pubs), 0xAE])
    )
    if script_type == "pkh":  # legacy multisig's script was sh(sortedmulti), not pkh
        return b58encode_check((b"\x05" if main else b"\xc4") + _hash160(redeem))
    if script_type == "wsh":
        return _bech32_encode(hrp, 0, hashlib.sha256(redeem).digest())
    if script_type == "sh-wsh":
        witness_script_hash = hashlib.sha256(redeem).digest()
        return b58encode_check((b"\x05" if main else b"\xc4") + _hash160(b"\x00\x20" + witness_script_hash))
    raise ExchangeError("Unsupported multisig script for public verification")
