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

"""Electrum BIE2 public-xpub USB unlock path; synthetic data, no private keys."""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from hwilib._base58 import encode_check

from bitcoin_safe.wallet_import.adapters import load_file
from bitcoin_safe.wallet_import.electrum import (
    ELECTRUM_STORAGE_XPUB_PATH,
    decrypt_electrum,
    electrum_storage_password_from_xpub,
)
from bitcoin_safe.wallet_import.model import ExchangeError

from .test_added_wallets import _encrypt_electrum
from .test_wallet_exchange import xpub


def synthetic_storage_xpub(scalar: int = 1, *, depth: int = 2, last_child: int = 1112098098) -> str:
    pubkey = (
        ec.derive_private_key(scalar, ec.SECP256K1())
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)
    )
    payload = (
        bytes.fromhex("0488b21e")
        + bytes([depth])
        + b"\x00" * 4
        + (last_child | 0x80000000).to_bytes(4, "big")
        + b"\x12" * 32
        + pubkey
    )
    return encode_check(payload)


def electrum_standard_wallet() -> dict:
    return {
        "wallet_type": "standard",
        "keystore": {
            "type": "bip32",
            "xpub": xpub(0x04B24746),
            "root_fingerprint": "beefcafe",
            "derivation": "m/84h/0h/0h",
        },
    }


def test_electrum_storage_uses_special_public_xpub_not_account_xpub() -> None:
    assert ELECTRUM_STORAGE_XPUB_PATH == "m/4541509'/1112098098'"
    special = synthetic_storage_xpub()
    pubkey = (
        ec.derive_private_key(1, ec.SECP256K1())
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)
    )
    assert electrum_storage_password_from_xpub(special) == pubkey.hex()
    with pytest.raises(ValueError, match="depth"):
        electrum_storage_password_from_xpub(synthetic_storage_xpub(depth=3))
    with pytest.raises(ValueError, match="final child"):
        electrum_storage_password_from_xpub(synthetic_storage_xpub(last_child=42))


def test_bie2_load_file_from_hardware_xpub_without_user_password(tmp_path) -> None:
    special = synthetic_storage_xpub()
    blob = _encrypt_electrum(
        electrum_standard_wallet(), electrum_storage_password_from_xpub(special), magic=b"BIE2"
    )
    path = tmp_path / "hardware-electrum"
    path.write_bytes(blob)
    wallets = load_file(path, hint="electrum", electrum_hw_xpub=special)
    assert len(wallets) == 1
    assert wallets[0].source_wallet == "electrum"
    assert wallets[0].descriptor and wallets[0].descriptor.startswith("wpkh(")
    assert "BIE2" not in wallets[0].to_json()
    assert json.loads(wallets[0].to_json())["source_wallet"] == "electrum"

    with pytest.raises(ExchangeError, match="USB hardware wallet"):
        load_file(path, hint="electrum", password="typed-password")
    with pytest.raises(ExchangeError, match="wrong device"):
        load_file(path, hint="electrum", electrum_hw_xpub=synthetic_storage_xpub(2))
    with pytest.raises(ExchangeError, match="not a typed password"):
        load_file(path, hint="electrum", password="x", electrum_hw_xpub=special)


def test_bie1_and_plaintext_reject_unrelated_hardware_unlock(tmp_path) -> None:
    special = synthetic_storage_xpub()
    data = electrum_standard_wallet()
    encrypted = _encrypt_electrum(data, "typed-password")
    with pytest.raises(ExchangeError, match="only unlock an Electrum BIE2"):
        decrypt_electrum(encrypted, None, electrum_hw_xpub=special)
    file = tmp_path / "plaintext-electrum"
    file.write_text(json.dumps(data))
    with pytest.raises(ExchangeError, match="only unlock an encrypted Electrum"):
        load_file(file, hint="electrum", electrum_hw_xpub=special)
