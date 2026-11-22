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

"""Modern Sparrow H2 converter tests using synthetic public rows.

No real user wallet, seed, or private key is involved.
"""

import pytest

from bitcoin_safe.wallet_import.adapters import load_file
from bitcoin_safe.wallet_import.model import ExchangeError
from bitcoin_safe.wallet_import.sparrow_h2 import (
    H2_MAGIC,
    H2_SPRW_MAGIC,
    address_from_h2_data,
    from_sparrow_h2_rows,
    is_sparrow_h2,
    sparrow_h2_file_password,
)

from .test_wallet_exchange import xpub


def synthetic_h2_rows(two_wallets=False):
    section = {
        "schema": "wallet_master",
        "wallet": [
            {
                "id": 1,
                "name": "TestH2",
                "label": "Vault",
                "network": 0,
                "scriptType": 6,
                "policyType": 0,
                "gapLimit": 30,
                "watchLast": 42,
                "birthHeight": 100000,
                "defaultPolicy": 123,
            }
        ],
        "policy": [{"id": 123, "script": "wpkh(Ledger)", "name": "Default"}],
        "keystore": [
            {
                "id": 10,
                "index": 0,
                "wallet": 1,
                "label": "Ledger",
                "source": 0,
                "walletModel": 7,
                "masterFingerprint": "f00dbabe",
                "derivationPath": "m/84'/0'/0'",
                "extendedPublicKey": xpub(),
                "seed": None,
                "masterPrivateExtendedKey": None,
            }
        ],
        "walletNode": [
            {"id": 2, "wallet": 1, "parent": None, "derivationPath": "m/0", "label": None},
            {
                "id": 3,
                "wallet": 1,
                "parent": 2,
                "derivationPath": "m/0/1",
                "label": "rent",
                "addressData": "12" * 20,
            },
            {"id": 4, "wallet": 1, "parent": 2, "derivationPath": "m/0/2", "label": "lost address"},
        ],
        "blockTransactionHashIndex": [
            {
                "id": 50,
                "node": 3,
                "hash": "a" * 64,
                "index": 4,
                "outputValue": 2500,
                "label": "invoice",
                "status": 0,
                "spentBy": None,
            },
            {
                "id": 51,
                "node": 3,
                "hash": "b" * 64,
                "index": 2,
                "outputValue": 3000,
                "label": "already spent",
                "status": None,
                "spentBy": 52,
            },
            {
                "id": 52,
                "node": 3,
                "hash": "c" * 64,
                "index": 1,
                "outputValue": 3000,
                "label": "input label",
                "status": None,
                "spentBy": None,
            },
        ],
        "blockTransaction": [{"wallet": 1, "txid": "d" * 64, "label": "salary"}],
        "detachedLabel": [{"entry": "e" * 64, "label": "detached tx"}],
        "externalOutputLabel": [{"txid": "f" * 64, "index": 0, "label": "payee output"}],
    }
    second = {k: v for k, v in section.items()}
    if two_wallets:
        second = dict(section)
        second["schema"] = "wallet_child named - BIP86"
    return {"format": "sparrow-h2-rows-v1", "schemas": [section] + ([second] if two_wallets else [])}


def test_h2_converter_wallet_labels_and_freezes():
    w = from_sparrow_h2_rows(synthetic_h2_rows())[0]
    assert w.source_wallet == "sparrow-h2"
    assert w.name == "Vault"
    assert w.network == "mainnet"
    assert w.descriptor.startswith("wpkh([f00dbabe/84h/0h/0h]")
    assert w.keystores[0].device_type == "LEDGER_NANO_S"
    assert w.gap_limit == 30
    assert w.birth_height == 100000
    assert w.extra["watch_last"] == 42
    assert w.frozen_outpoints == ["a" * 64 + ":4"]
    assert len(w.utxos) == 2  # exclude synthetic spentBy input record
    frozen = next(u for u in w.utxos if u.frozen)
    assert frozen.address.startswith("bc1q")
    assert any(label_record.type == "addr" and label_record.label == "rent" for label_record in w.labels)
    assert any(
        label_record.type == "tx" and label_record.ref == "d" * 64 and label_record.label == "salary"
        for label_record in w.labels
    )
    assert any(
        label_record.type == "tx" and label_record.ref == "e" * 64 and label_record.label == "detached tx"
        for label_record in w.labels
    )
    assert any(
        label_record.type == "input" and label_record.ref == "c" * 64 + ":1" for label_record in w.labels
    )
    assert any(
        label_record.type == "output" and label_record.ref == "f" * 64 + ":0" for label_record in w.labels
    )
    assert w.extra["unresolved_node_labels"][0]["derivationPath"] == "m/0/2"
    assert "xprv" not in w.to_json() and '"seed"' not in w.to_json()


def test_h2_multi_schema_and_no_seed_material():
    rows = synthetic_h2_rows(two_wallets=True)
    rows["schemas"][1]["keystore"] = [
        dict(rows["schemas"][1]["keystore"][0], seed=99, extendedPublicKey=None)
    ]
    wallets = from_sparrow_h2_rows(rows)
    assert len(wallets) == 2
    w = wallets[1]
    assert w.keystores[0].extra["software_signer_present"] is True
    assert w.descriptor is None
    assert any("seed records" in msg.lower() for msg in w.warnings)
    assert w.keystores[0].extra["software_signer_present"] is True  # no underlying secret read


def test_h2_address_encoding():
    assert address_from_h2_data("P2WPKH", "mainnet", "11" * 20).startswith("bc1q")
    assert address_from_h2_data("P2TR", "testnet", "22" * 32).startswith("tb1p")
    assert address_from_h2_data("P2PKH", "mainnet", "11" * 20).startswith("1")
    assert address_from_h2_data("P2SH_P2WPKH", "mainnet", "11" * 20).startswith("3")
    assert address_from_h2_data("P2WPKH", "regtest", "11" * 20).startswith("bcrt1q")
    assert address_from_h2_data("P2WPKH", "mainnet", "11" * 19) is None


def test_h2_rejects_unknown_ordinals_and_bad_metadata():
    bad = synthetic_h2_rows()
    bad["schemas"][0]["wallet"][0]["scriptType"] = 77
    with pytest.raises(ExchangeError, match="enum ordinal"):
        from_sparrow_h2_rows(bad)
    with pytest.raises(ExchangeError, match="format"):
        from_sparrow_h2_rows({"format": "suspicious", "schemas": []})


def test_h2_password_derivation_costs_small_synthetic():
    salt = b"s" * 16
    header = H2_MAGIC + b"h" * 8 + H2_SPRW_MAGIC + salt + b"payload"
    key = sparrow_h2_file_password(header, "my-password", _test_costs=(1, 1024, 1))
    assert len(key) == 66 and key[:2] in ("02", "03")
    assert key == sparrow_h2_file_password(header, "my-password", _test_costs=(1, 1024, 1))
    assert key != sparrow_h2_file_password(header, "different", _test_costs=(1, 1024, 1))
    with pytest.raises(ExchangeError, match="non-empty"):
        sparrow_h2_file_password(header, "")
    with pytest.raises(ExchangeError, match="recognized"):
        sparrow_h2_file_password(H2_MAGIC + b"x" * 35, "password")


def test_modern_h2_detected_before_json_and_invalid_data_rejected(tmp_path):
    file = tmp_path / "vault.mv.db"
    file.write_bytes(b"H:2:" + b"x" * 40)
    assert is_sparrow_h2(file)
    with pytest.raises(ExchangeError, match="Truncated H2"):
        load_file(file, hint="sparrow")
    with pytest.raises(ExchangeError, match="must be sparrow"):
        load_file(file, hint="specter")


def test_encrypted_h2_prompt_required(tmp_path):
    file = tmp_path / "locked.mv.db"
    file.write_bytes(H2_MAGIC + b"h" * 8 + H2_SPRW_MAGIC + b"s" * 16 + b"x" * 20)
    with pytest.raises(ExchangeError, match="requires a password"):
        load_file(file)


def test_h2_multi_wallet_schema_omits_unassigned_labels():
    rows = synthetic_h2_rows()
    section = rows["schemas"][0]
    section["wallet"].append(dict(section["wallet"][0], id=2, name="Second", label="Second"))
    section["keystore"].append(dict(section["keystore"][0], id=11, wallet=2))
    section["blockTransaction"].append({"wallet": 2, "txid": "9" * 64, "label": "second tx"})
    first, second = from_sparrow_h2_rows(rows)
    assert any(label.label == "salary" for label in first.labels)
    assert any(label.label == "second tx" for label in second.labels)
    for wallet in (first, second):
        assert not any(label.label in {"detached tx", "payee output"} for label in wallet.labels)
        assert any("labels were omitted" in warning for warning in wallet.warnings)
