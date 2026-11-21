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

"""Sparrow public-account derivation; never print real mnemonics."""

import hashlib
import hmac
import os
import unicodedata
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from bitcoin_safe.wallet_import import ExchangeError, load_file
from bitcoin_safe.wallet_import.descriptors import b58decode_check
from bitcoin_safe.wallet_import.sparrow_crypto import N
from bitcoin_safe.wallet_import.sparrow_h2 import SCRIPT_NAMES
from bitcoin_safe.wallet_import.sparrow_seed_public import _derived_account_pub, _seed_mnemonic

SYNTHETIC_WORDS = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)


def test_script_type_enums_match_drongo_persisted_ordinals():
    # Important: Drongo has MULTISIG at ordinal 2, even though this isn't an
    # allowed descriptor script type in our interchange model.
    assert SCRIPT_NAMES[2] == "MULTISIG"
    assert SCRIPT_NAMES[6] == "P2WPKH"
    assert SCRIPT_NAMES[7] == "P2WSH"
    assert SCRIPT_NAMES[8] == "P2TR"


def test_bip39_derived_account_public_key_matches_independent_cryptography():
    path = "m/48'/1'/0'/2'"
    tpub, fingerprint = _derived_account_pub(SYNTHETIC_WORDS, path, mainnet=False)
    payload = b58decode_check(tpub)
    assert len(payload) == 78 and payload[:4] == bytes.fromhex("043587cf")
    # Independent libcrypto elliptic-curve implementation, not Sparrow scalar
    # arithmetic used by the production key derivation function.
    seed = hashlib.pbkdf2_hmac(
        "sha512", unicodedata.normalize("NFKD", SYNTHETIC_WORDS).encode(), b"mnemonic", 2048
    )
    digest = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
    k, chain = int.from_bytes(digest[:32], "big"), digest[32:]
    master_pub = (
        ec.derive_private_key(k, ec.SECP256K1())
        .public_key()
        .public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    )
    master_fingerprint = hashlib.new("ripemd160", hashlib.sha256(master_pub).digest()).digest()[:4]
    assert fingerprint == master_fingerprint.hex()
    parent_fingerprint = b""
    for idx in (0x80000030, 0x80000001, 0x80000000, 0x80000002):
        parent_pub = (
            ec.derive_private_key(k, ec.SECP256K1())
            .public_key()
            .public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
        )
        parent_fingerprint = hashlib.new("ripemd160", hashlib.sha256(parent_pub).digest()).digest()[:4]
        digest = hmac.new(
            chain, b"\0" + k.to_bytes(32, "big") + idx.to_bytes(4, "big"), hashlib.sha512
        ).digest()
        k = (k + int.from_bytes(digest[:32], "big")) % N
        chain = digest[32:]
    actual_pub = (
        ec.derive_private_key(k, ec.SECP256K1())
        .public_key()
        .public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    )
    assert payload[5:9] == parent_fingerprint
    assert payload[13:45] == chain
    assert payload[45:78] == actual_pub


def test_private_seed_decryption(monkeypatch):
    from bitcoin_safe.wallet_import import sparrow_seed_public as mod

    monkeypatch.setattr(mod, "hash_secret_raw", lambda *args, **kwargs: b"k" * 32)
    iv = b"0" * 16
    padder = PKCS7(128).padder()
    padded = padder.update(SYNTHETIC_WORDS.encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(b"k" * 32), modes.CBC(iv)).encryptor()
    encrypted = enc.update(padded) + enc.finalize()
    synthetic_row = dict(
        type=0,
        needsPassphrase=False,
        deriver=4,
        crypter=1,
        encryptedBytes=encrypted,
        initialisationVector=iv,
        keySalt=b"x" * 16,
    )
    assert _seed_mnemonic(synthetic_row, "password") == SYNTHETIC_WORDS
    with pytest.raises(ExchangeError, match="passphrase"):
        _seed_mnemonic(dict(synthetic_row, needsPassphrase=True), "password")
    with pytest.raises(ExchangeError, match="BIP39 only"):
        _seed_mnemonic(dict(synthetic_row, type=1), "password")
    with pytest.raises(ExchangeError, match="variant"):
        _seed_mnemonic(dict(synthetic_row, crypter=0), "password")


@pytest.mark.skipif(
    not os.environ.get("SPARROW_H2_TEST_FILE"), reason="needs opt-in external wallet test fixture"
)
def test_real_encrypted_multisig_can_build_descriptor():
    path = Path(os.environ["SPARROW_H2_TEST_FILE"])
    pwd = os.environ["WALLET_TEST_PASSWORD"]
    w = load_file(path, hint="sparrow", password=pwd)[0]
    assert w.network == "regtest"
    assert w.address_type == "wsh"
    assert w.descriptor.startswith("wsh(sortedmulti(2,")
    assert len(w.keystores) == 3
    assert all(k.xpub.startswith("tpub") and k.fingerprint and k.key_origin for k in w.keystores)
    assert all(k.non_mainnet_seed is not None for k in w.keystores)
    assert "mnemonicString" not in w.to_json()
    assert "encryptedBytes" not in w.to_json()
    assert SYNTHETIC_WORDS not in w.to_json()


def test_seed_table_derivation_only_exposes_public_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from bitcoin_safe.wallet_import.h2_python import _MVStore
    from bitcoin_safe.wallet_import.sparrow_seed_public import augment_public_rows_from_seeds

    store = object.__new__(_MVStore)
    store.meta = {"name.table.0": "1", "name.table.7": "2"}
    seed_sql = 'CREATE TABLE "wallet_test"."seed"(\n"id" BIGINT,\n"type" INT,\n"mnemonicString" VARCHAR\n)'

    def map_id(self: _MVStore, map_id: int, key_kind: str, value_kind: str, columns: int | None = None):
        if map_id == 1:
            return [(1, [7, None, None, seed_sql])]
        return [(1, [42, 0, SYNTHETIC_WORDS])]

    monkeypatch.setattr(_MVStore, "map_id", map_id)
    data = {
        "schemas": [
            {
                "schema": "wallet_test",
                "wallet": [{"network": 0}],
                "keystore": [
                    {"seed": 42, "source": 2, "derivationPath": "m/84h/0h/0h", "extendedPublicKey": None}
                ],
            }
        ]
    }
    assert augment_public_rows_from_seeds(store, data, "password") == 1
    key = data["schemas"][0]["keystore"][0]
    expected, fingerprint = _derived_account_pub(SYNTHETIC_WORDS, "m/84h/0h/0h", mainnet=True)
    assert key["extendedPublicKey"] == expected
    assert key["masterFingerprint"] == fingerprint
    assert SYNTHETIC_WORDS not in str(data)
    key["extendedPublicKey"] = "invalid"
    with pytest.raises(ExchangeError):
        augment_public_rows_from_seeds(store, data, "password")


def test_testnet_h2_seed_recovery_and_passphrase_guard(monkeypatch):
    from bitcoin_safe.wallet_import.h2_python import _MVStore
    from bitcoin_safe.wallet_import.sparrow_seed_public import augment_public_rows_from_seeds

    store = object.__new__(_MVStore)
    store.meta = {"name.table.0": "1", "name.table.7": "2"}
    sql = 'CREATE TABLE "wallet_test"."seed"(\n"id" BIGINT,\n"type" INT,\n"mnemonicString" VARCHAR,\n"needsPassphrase" BOOLEAN\n)'
    seed = [42, 0, SYNTHETIC_WORDS, False]

    def map_id(self, map_id, key_kind, value_kind, columns=None):
        return [(1, [7, None, None, sql])] if map_id == 1 else [(1, seed)]

    monkeypatch.setattr(_MVStore, "map_id", map_id)
    key = {"seed": 42, "source": 2, "derivationPath": "m/84h/1h/0h"}
    data = {"schemas": [{"schema": "wallet_test", "wallet": [{"network": 1}], "keystore": [key]}]}
    assert augment_public_rows_from_seeds(store, data, None) == 1
    assert key["bip39Mnemonic"] == SYNTHETIC_WORDS
    seed[3] = True
    key.clear()
    key.update({"seed": 42, "source": 2, "derivationPath": "m/84h/1h/0h"})
    assert augment_public_rows_from_seeds(store, data, None) == 0
    assert key["bip39PassphraseRequired"]
    assert "bip39Mnemonic" not in key
    assert augment_public_rows_from_seeds(store, data, None, "hidden") == 1
    assert (
        key["extendedPublicKey"] == _derived_account_pub(SYNTHETIC_WORDS, "m/84h/1h/0h", False, "hidden")[0]
    )
    assert "bip39Mnemonic" not in key
