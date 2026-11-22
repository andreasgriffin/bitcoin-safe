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

"""Public-only password support, with BIP38 synthetic tests.

No real passwords, seeds or wallet private keys are stored in test artifacts.
"""

import hashlib
import json

import pytest
from Crypto.Hash import RIPEMD160
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bitcoin_safe.wallet_import import ExchangeError, from_wasabi, load_file, load_json_obj
from bitcoin_safe.wallet_import.descriptors import b58encode_check
from bitcoin_safe.wallet_import.passwords import verify_wasabi_password

from .test_wallet_exchange import xpub


def _test_bip38(
    password: str, secret_scalar: int = 7, compressed: bool = True, network: str = "Main"
) -> tuple[str, str]:
    """Build BIP38 non-EC encrypted synthetic test material independently."""
    private = ec.derive_private_key(secret_scalar, ec.SECP256K1())
    pub = private.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.CompressedPoint
        if compressed
        else serialization.PublicFormat.UncompressedPoint,
    )
    address = b58encode_check(
        bytes([0 if network == "Main" else 111]) + RIPEMD160.new(hashlib.sha256(pub).digest()).digest()
    )
    address_hash = hashlib.sha256(hashlib.sha256(address.encode()).digest()).digest()[:4]
    kdf = hashlib.scrypt(
        password.encode(), salt=address_hash, n=16384, r=8, p=8, dklen=64, maxmem=128 * 1024 * 1024
    )
    payload = secret_scalar.to_bytes(32, "big")
    enc = Cipher(algorithms.AES(kdf[32:]), modes.ECB()).encryptor()
    blob = enc.update(bytes(a ^ b for a, b in zip(payload, kdf[:32], strict=True))) + enc.finalize()
    root = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint
    )
    fp = RIPEMD160.new(hashlib.sha256(root).digest()).digest()[:4].hex()
    return b58encode_check(b"\x01\x42" + (b"\xe0" if compressed else b"\xc0") + address_hash + blob), fp


@pytest.mark.parametrize("network,compressed", [("Main", True), ("Main", False), ("TestNet4", True)])
def test_wasabi_validates_real_bip38_password(network, compressed):
    encrypted, fp = _test_bip38("correct horse", network=network, compressed=compressed)
    data = {
        "ExtPubKey": xpub(0x0488B21E if network == "Main" else 0x043587CF),
        "EncryptedSecret": encrypted,
        "MasterFingerprint": fp,
        "BlockchainState": {"Network": network},
    }
    wallets = from_wasabi(data, password="correct horse")
    assert len(wallets) == 1
    assert wallets[0].keystores[0].recovery_material == "PRIVATE_KEY_REDACTED"
    assert any("password verified" in w for w in wallets[0].warnings)
    assert encrypted not in wallets[0].to_json()
    assert "correct horse" not in wallets[0].to_json()
    with pytest.raises(ExchangeError, match="Incorrect Wasabi BIP38 password"):
        verify_wasabi_password(data, "wrong password")


def test_bip38_official_public_test_vector():
    # BIP-0038's published (non-EC/non-compressed) test vector.
    verify_wasabi_password(
        {
            "EncryptedSecret": "6PRVWUbkzzsbcVac2qwfssoUJAN1Xhrg6bNk8J7Nzm5H7kxEbn2Nh2ZoGg",
            "BlockchainState": {"Network": "Main"},
        },
        "TestingOneTwoThree",
    )


def test_wasabi_fingerprint_mismatch_fails_closed():
    encrypted, fp = _test_bip38("test")
    with pytest.raises(ExchangeError, match="fingerprint"):
        verify_wasabi_password(
            {
                "EncryptedSecret": encrypted,
                "MasterFingerprint": "badcafe0",
                "BlockchainState": {"Network": "Main"},
            },
            "test",
        )


@pytest.mark.parametrize("account_path", [None, "m/84h/0h/0h"])
def test_wasabi_watch_only_rejects_unused_password(account_path: str | None) -> None:
    data = {"ExtPubKey": xpub(), "BlockchainState": {"Network": "Main"}}
    if account_path:
        data["AccountKeyPath"] = account_path
    descriptor = from_wasabi(data)[0].descriptor
    assert bool(descriptor) == bool(account_path)
    if descriptor:
        assert descriptor.startswith("wpkh(")
    with pytest.raises(ExchangeError, match="watch-only"):
        from_wasabi(data, password="unused")


def test_plaintext_other_exports_reject_ignored_password(tmp_path):
    examples = [
        ({"name": "S", "recv_descriptor": "wpkh(" + xpub() + "/0/*)", "keys": []}, "specter"),
        ({"type": "Account", "derivationMode": "native_segwit", "xpub": xpub()}, "ledger"),
    ]
    for i, (obj, format_name) in enumerate(examples):
        f = tmp_path / f"example{i}.json"
        f.write_text(json.dumps(obj), encoding="utf8")
        with pytest.raises(ExchangeError, match="plaintext"):
            load_file(f, password="password", hint=format_name)
        with pytest.raises(ExchangeError, match="plaintext"):
            load_json_obj(obj, password="password", hint=format_name)


def test_wasabi_regtest_uses_test_network_account_origin():
    data = {"ExtPubKey": xpub(0x043587CF), "BlockchainState": {"Network": "RegTest"}}
    wallet = from_wasabi(data)[0]
    assert wallet.network == "regtest"
    # No path is present in the source. Never invent a signing origin.
    assert wallet.keystores[0].key_origin is None


def test_gnupg_wallet_wrapper_is_not_a_native_import_format(tmp_path):
    source = tmp_path / "accounts.json.gpg"
    source.write_bytes(b"\x8c\x0d" + b"not a native wallet format")
    with pytest.raises(ExchangeError, match="Binary wallet format not recognized"):
        load_file(source, password="unused", hint="specter")
