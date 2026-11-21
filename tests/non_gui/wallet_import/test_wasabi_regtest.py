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

"""Synthetic regression tests for PR #942 Wasabi regtest fix.

Run from a Bitcoin Safe checkout after copying additional.py:
    pytest -q tests/non_gui/wallet_import/test_wasabi_regtest.py
The well-known 12-word BIP39 test vector is deliberately public.
"""

import pytest

from bitcoin_safe.wallet_import.additional import _taproot_bip86_address, from_wasabi
from bitcoin_safe.wallet_import.model import ExchangeError, Keystore
from bitcoin_safe.wallet_import.sparrow_seed_public import _derived_account_pub
from bitcoin_safe.wallet_import.verification import derive_pubkey

TEST_VECTOR = "abandon " * 11 + "about"


def _make_regtest_input():
    rows = []
    sample = {
        "BlockchainState": {"Network": "RegTest"},
        "MasterFingerprint": "aabbccdd",
        "HdPubKeys": rows,
    }
    for name, purpose, index in [("ExtPubKey", 84, 0), ("TaprootExtPubKey", 86, 1)]:
        path = f"m/{purpose}h/0h/0h"
        xpub, _ = _derived_account_pub(TEST_VECTOR, path, mainnet=True)
        sample[name] = xpub
        sample["AccountKeyPath" if purpose == 84 else "TaprootAccountKeyPath"] = path
        k = Keystore(xpub=xpub)
        rows.append(
            {
                "FullKeyPath": f"{purpose}h/0h/0h/0/{index}",
                "PubKey": derive_pubkey(k, 0, index).hex(),
                "Label": "Synthetic regtest label",
            }
        )
    return sample


def test_wasabi_regtest_coin_type_zero_and_xpub_is_reserialized_as_tpub():
    wallets = from_wasabi(_make_regtest_input())
    assert len(wallets) == 2
    for i, w in enumerate(wallets):
        assert w.network == "regtest"
        assert w.keystores[0].xpub.startswith("tpub")
        assert w.keystores[0].key_origin == f"m/{84 if i == 0 else 86}h/0h/0h"
        assert w.descriptor and "tpub" in w.descriptor
        assert w.keystores[0].extra["wasabi_regtest_xpub_version_normalized"] is True
        assert len(w.labels) == 1
        assert w.labels[0].ref.startswith("bcrt1q" if i == 0 else "bcrt1p")
        assert w.extra.get("unresolved_path_labels") is None


def test_bip86_reference_vector_matches_official_address():
    xpub, _ = _derived_account_pub(TEST_VECTOR, "m/86h/0h/0h", True)
    assert _taproot_bip86_address(Keystore(xpub=xpub), "mainnet", 0, 0) == (
        "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
    )


def test_tampered_wasabi_labeled_pubkey_is_not_imported():
    sample = _make_regtest_input()
    sample["HdPubKeys"][1]["PubKey"] = "02" + "00" * 32
    accounts = from_wasabi(sample)
    assert len(accounts[0].labels) == 1
    assert not accounts[1].labels
    assert len(accounts[1].extra["unresolved_path_labels"]) == 1


def test_regtest_unsupported_account_origin_is_still_rejected():
    obj = _make_regtest_input()
    obj["AccountKeyPath"] = "84'/1'/0'"  # wrong coin for Wasabi RegTest
    with pytest.raises(ExchangeError, match="wallet network"):
        from_wasabi(obj)


def test_mainnet_xpub_not_accepted_on_testnet():
    obj = _make_regtest_input()
    obj["BlockchainState"]["Network"] = "TestNet"
    obj["AccountKeyPath"] = "84'/1'/0'"
    obj["TaprootAccountKeyPath"] = "86'/1'/0'"
    with pytest.raises(ExchangeError, match="Network conflicts"):
        from_wasabi(obj)


def test_testnet_tpub_and_coin_type_one_are_allowed():
    obj = _make_regtest_input()
    obj["BlockchainState"]["Network"] = "TestNet"
    # Need synthetic account keys for 1' coin rather than re-serializing 0' xpubs.
    obj["HdPubKeys"] = []
    for purpose, key, pathkey in [
        (84, "ExtPubKey", "AccountKeyPath"),
        (86, "TaprootExtPubKey", "TaprootAccountKeyPath"),
    ]:
        obj[pathkey] = f"m/{purpose}h/1h/0h"
        obj[key], _ = _derived_account_pub(TEST_VECTOR, obj[pathkey], False)
    wallets = from_wasabi(obj)
    assert all(w.network == "testnet" and w.keystores[0].xpub.startswith("tpub") for w in wallets)
    assert all(w.keystores[0].key_origin.endswith("/1h/0h") for w in wallets)
