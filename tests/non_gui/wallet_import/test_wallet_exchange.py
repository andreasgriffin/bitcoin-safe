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

import base64
import hashlib
import hmac
import json
import zlib

import pytest

from bitcoin_safe.wallet_import import (
    ExchangeError,
    WalletExchange,
    from_descriptor,
    from_green,
    from_ledger_account,
    from_sparrow_json,
    from_specter,
    import_bip329_jsonl,
    load_json_obj,
)
from bitcoin_safe.wallet_import.descriptors import (
    add_checksum,
    b58encode_check,
    combine_receive_change,
    descriptor_checksum,
    normalize_xpub,
)
from bitcoin_safe.wallet_import.sparrow_crypto import _compressed, _scalar_mul, decrypt_sprw1

# Validly encoded account-level extended public key with the secp256k1 base point.
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
G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def xpub(version=0x0488B21E):
    payload = (
        version.to_bytes(4, "big")
        + b"\x03"
        + b"\x00" * 4
        + b"\x80\x00\x00\x00"
        + b"\x12" * 32
        + _compressed(G)
    )
    assert len(payload) == 78
    return b58encode_check(payload)


def expressions():
    k = xpub()
    recv = f"wpkh([f00dbabe/84h/0h/0h]{k}/0/*)"
    change = f"wpkh([f00dbabe/84h/0h/0h]{k}/1/*)"
    both = f"wpkh([f00dbabe/84h/0h/0h]{k}/<0;1>/*)"
    return recv, change, both


def test_slip132_and_descriptor_checksum():
    x, network, prefix = normalize_xpub(xpub(0x04B24746))
    assert x == xpub()
    assert (network, prefix) == ("mainnet", "zpub")
    d = expressions()[2]
    assert len(descriptor_checksum(d)) == 8
    assert add_checksum(add_checksum(d)) == add_checksum(d)
    with pytest.raises(ExchangeError):
        add_checksum(d + "#aaaaaaaa")
    assert combine_receive_change(expressions()[0], expressions()[1]) == add_checksum(d)
    assert combine_receive_change(expressions()[0], expressions()[0]) is None


def test_descriptor_keystores():
    w = from_descriptor(expressions()[2], name="watch")
    assert w.network == "mainnet"
    assert w.keystores[0].fingerprint == "f00dbabe"
    assert w.keystores[0].key_origin == "m/84h/0h/0h"
    assert w.keystores[0].derivation_suffix == "/<0;1>/*"
    assert w.descriptor == add_checksum(expressions()[2])


def test_specter_wallet_and_companion_labels():
    recv, chg, both = expressions()
    data = {
        "name": "family",
        "recv_descriptor": recv,
        "change_descriptor": chg,
        "keys": [{"xpub": xpub(), "fingerprint": "f00dbabe", "derivation": "m/84h/0h/0h"}],
        "devices": ["trezor_alias"],
        "sigs_required": 1,
        "address_index": 7,
        "frozen_utxo": ["a" * 64 + ":1"],
        "labels": {"invoice 1": ["bc1qexample"]},
    }
    w = from_specter(data, address_csv="Address,Label\nbc1qexample,invoice 1\nbc1qexample2,new\n")
    assert w.descriptor == add_checksum(both)
    assert w.frozen_outpoints == ["a" * 64 + ":1"]
    assert next(x for x in w.labels if x.ref == "a" * 64 + ":1").spendable is False
    assert next(x for x in w.labels if x.ref == "bc1qexample2").label == "new"
    assert len([label_record for label_record in w.labels if label_record.ref == "bc1qexample"]) == 1


def test_sparrow_json_utxo_and_policies():
    k = xpub()
    p = {
        "name": "MyWallet",
        "network": "MAINNET",
        "scriptType": "P2WPKH",
        "keystores": [
            {
                "label": "Trezor",
                "source": "HW_USB",
                "walletModel": "TREZOR_T",
                "keyDerivation": {"masterFingerprint": "f00dbabe", "derivationPath": "m/84'/0'/0'"},
                "extendedPublicKey": k,
            }
        ],
        "defaultPolicy": {"miniscript": {"script": "wpkh(Trezor)"}},
        "purposeNodes": [
            {
                "derivationPath": "m/0",
                "children": [
                    {
                        "derivationPath": "m/0/3",
                        "address": "bc1qtest",
                        "label": "rent",
                        "transactionOutputs": [
                            {
                                "hash": "b" * 64,
                                "index": 2,
                                "status": "FROZEN",
                                "value": 12345,
                                "label": "inbound",
                            }
                        ],
                    }
                ],
            }
        ],
        "transactions": {"c" * 64: {"label": "tx note"}},
    }
    w = from_sparrow_json(p)
    assert w.network == "mainnet"
    assert w.descriptor.startswith("wpkh([f00dbabe/84h/0h/0h]")
    assert w.utxos[0].frozen and w.utxos[0].value_sats == 12345
    assert len(w.frozen_outpoints) == 1
    assert any(label_record.type == "tx" and label_record.label == "tx note" for label_record in w.labels)
    assert any(label_record.type == "addr" and label_record.ref == "bc1qtest" for label_record in w.labels)
    assert "seed" not in w.to_json().lower()


def test_sparrow_multisig_not_guessed_without_policy():
    raw = {
        "name": "Multisig",
        "scriptType": "P2WSH",
        "network": "MAINNET",
        "purposeNodes": [],
        "keystores": [
            {"label": "A", "extendedPublicKey": xpub()},
            {"label": "B", "extendedPublicKey": xpub()},
        ],
    }
    w = from_sparrow_json(raw)
    assert w.descriptor is None
    assert any("descriptor" in x for x in w.warnings)
    raw["defaultPolicy"] = {"miniscript": {"script": "wsh(multi(2,A,B))"}}
    w = from_sparrow_json(raw)
    assert w.descriptor.startswith("wsh(multi(2,")


def test_ledger_models():
    label_record = from_ledger_account(
        {
            "type": "Account",
            "name": "BTC 1",
            "xpub": xpub(),
            "derivationMode": "native_segwit",
            "freshAddressPath": "m/84'/0'/0'/0/4",
            "freshAddressIndex": 4,
            "currency": {"id": "bitcoin"},
            "bitcoinResources": {"utxos": [["a" * 64, 1, 200, "bc1qabc", "1500", 0, 0]]},
        }
    )
    assert label_record.descriptor.startswith("wpkh(")
    assert label_record.keystores[0].key_origin == "m/84h/0h/0h"
    assert label_record.utxos[0].value_sats == 1500


def test_green_login_record_not_descriptor():
    w = from_green({"name": "Green", "deployment": "mainnet", "xpub_hash_id": "abc"})
    assert w.descriptor is None and w.warnings


def test_bip329_preserves_optional_and_freeze_state():
    w = WalletExchange("test", "Wallet", network="testnet")
    import_bip329_jsonl(
        w,
        '{"type":"output", "ref":"' + "f" * 64 + ':4","spendable":false,"label":"cold"}\n'
        '{"type":"tx", "ref":"' + "a" * 64 + '","label":"payday"}\n',
    )
    assert w.frozen_outpoints == ["f" * 64 + ":4"]
    assert w.labels_jsonl().count("\n") == 2
    assert w.labels[0].to_bip329()["spendable"] is False
    with pytest.raises(ExchangeError):
        import_bip329_jsonl(w, '{"type":"addr", "ref":"foo", "spendable":false}')


def test_seed_never_serialized_even_nonmainnet():
    w = WalletExchange("test", "Testnet", network="testnet")
    w.attach_non_mainnet_seed("word " * 12)
    assert "word" not in w.to_json()
    assert "word" not in repr(w)
    with pytest.raises(ExchangeError):
        WalletExchange("test", "main", network="mainnet", non_mainnet_seed="sensitive")
    w.extra["private_key"] = "oops"
    with pytest.raises(ExchangeError):
        w.to_json()


def test_legacy_sparrow_sprw1_decryption_synthetic():
    from argon2.low_level import Type, hash_secret_raw
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    password = "test password"
    salt = b"1234567890abcdef"
    key = hash_secret_raw(
        password.encode(), salt, time_cost=1, memory_cost=1024, parallelism=1, hash_len=32, type=Type.ID
    )
    privkey = int.from_bytes(key, "big")
    pub = _scalar_mul(privkey, G)
    ephemeral_priv = 7
    ephemeral_pub = _compressed(_scalar_mul(ephemeral_priv, G))
    shared = _compressed(_scalar_mul(ephemeral_priv, pub))
    km = hashlib.sha512(shared).digest()
    iv, ek, mk = km[:16], km[16:32], km[32:64]
    raw = zlib.compress(json.dumps({"name": "Wallet"}).encode())
    padder = PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    enc = Cipher(algorithms.AES(ek), modes.CBC(iv)).encryptor()
    cipher = enc.update(padded) + enc.finalize()
    msg = b"BIE1" + ephemeral_pub + cipher
    payload = base64.b64encode(msg + hmac.new(mk, msg, hashlib.sha256).digest())
    header = base64.b64encode(b"SPRW1" + salt)
    assert len(header) == 28
    encrypted = header + payload
    assert (
        decrypt_sprw1(encrypted, password, _test_costs=(1, 1024, 1))
        == json.dumps({"name": "Wallet"}).encode()
    )
    with pytest.raises(ExchangeError, match="password"):
        decrypt_sprw1(encrypted, "not the password", _test_costs=(1, 1024, 1))


def test_dispatch():
    wallets = load_json_obj(
        {"type": "Account", "xpub": xpub(), "derivationMode": "native_segwit", "currency": {"id": "bitcoin"}}
    )
    assert len(wallets) == 1 and wallets[0].source_wallet == "ledger-live"
    with pytest.raises(ExchangeError):
        load_json_obj({"random": "object"})


def test_exchange_roundtrip_and_non_mainnet_keystore_seed_guard():
    w = from_descriptor(expressions()[2])
    original = w.to_dict()
    restored = WalletExchange.from_dict(original)
    assert restored.to_dict() == original
    restored.add_frozen_outpoint("f" * 64 + ":2")
    restored = WalletExchange.from_dict(restored.to_dict())
    assert restored.frozen_outpoints == ["f" * 64 + ":2"]
    with pytest.raises(ExchangeError):
        w.attach_keystore_seed(0, "test only")
    test = from_descriptor(f"wpkh([f00dbabe/84h/1h/0h]{xpub(0x043587CF)}/<0;1>/*)", network="testnet")
    seed = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    test.attach_keystore_seed(0, seed)
    assert seed not in repr(test)
    assert seed in test.to_json()
    assert WalletExchange.from_dict(test.to_dict()).keystores[0].non_mainnet_seed == seed
    compromised = test.to_dict()
    compromised["keystores"][0]["non_mainnet_seed"] = "secret"
    with pytest.raises(ExchangeError):
        WalletExchange.from_dict(compromised)


def test_multi_account_export_and_inconsistent_keys():
    src = {
        "accounts": [
            {"symbol": "btc", "accountType": "normal", "descriptor": xpub(), "path": "m/84h/0h/0h"},
            {"symbol": "btc", "accountType": "taproot", "descriptor": xpub(), "path": "m/86h/0h/0h"},
        ]
    }
    wallets = load_json_obj(src)
    assert len(wallets) == 2 and all(wallet.descriptor for wallet in wallets)
    mismatch = {
        "name": "Bad",
        "keys": [{"xpub": xpub(0x043587CF)}],
        "recv_descriptor": expressions()[0],
        "change_descriptor": expressions()[1],
    }
    wallet = from_specter(mismatch)
    assert wallet.descriptor is None
    assert any("conflict" in msg for msg in wallet.warnings)


def test_sparrow_bare_p2sh_not_guessed():
    data = {
        "name": "old",
        "network": "mainnet",
        "scriptType": "P2SH",
        "keystores": [{"extendedPublicKey": xpub()}],
        "purposeNodes": [],
    }
    assert from_sparrow_json(data).descriptor is None


def test_sparrow_multisig_policy_uses_sanitized_keystore_script_names():
    data = {
        "name": "vault",
        "network": "mainnet",
        "scriptType": "P2WSH",
        "keystores": [
            {"label": "BitBox 02", "extendedPublicKey": xpub()},
            {"label": "My Trezor", "extendedPublicKey": xpub()},
        ],
        "defaultPolicy": {"miniscript": {"script": "wsh(sortedmulti(2,MyTrezor,BitBox02))"}},
        "purposeNodes": [],
    }
    wallet = from_sparrow_json(data)
    assert wallet.descriptor is not None
    assert wallet.descriptor.startswith("wsh(sortedmulti(2,")
    assert [k.label for k in wallet.keystores] == ["My Trezor", "BitBox 02"]
