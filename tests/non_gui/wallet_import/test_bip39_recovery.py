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

"""Import explicitly identified BIP39 signers without inventing origins."""

import bdkpython as bdk
import pytest

from bitcoin_safe.wallet_import.adapters import from_sparrow_json
from bitcoin_safe.wallet_import.bitcoin_safe_bridge import make_protowallet
from bitcoin_safe.wallet_import.electrum import from_electrum
from bitcoin_safe.wallet_import.model import ExchangeError, WalletExchange
from bitcoin_safe.wallet_import.sparrow_seed_public import _derived_account_pub
from tests.non_gui.wallet_import.test_sparrow_seed_public import SYNTHETIC_WORDS


def sparrow_seed(network: str) -> dict:
    coin = 0 if network == "mainnet" else 1
    return {
        "network": network,
        "scriptType": "P2WPKH",
        "keystores": [
            {
                "label": "signer",
                "source": "SW_SEED",
                "keyDerivation": {"derivationPath": f"m/84h/{coin}h/0h"},
                "seed": {"type": "BIP39", "mnemonicString": SYNTHETIC_WORDS},
            }
        ],
        "defaultPolicy": {"miniscript": {"script": "wpkh(signer)"}},
    }


def test_sparrow_testnet_seed_roundtrip_and_signer_transfer() -> None:
    exchange = from_sparrow_json(sparrow_seed("testnet"))
    assert exchange.keystores[0].non_mainnet_seed == SYNTHETIC_WORDS
    restored = WalletExchange.from_dict(exchange.to_dict())
    proto = make_protowallet(restored, "test", bdk.Network.TESTNET)
    assert proto.keystores[0].mnemonic == SYNTHETIC_WORDS
    assert SYNTHETIC_WORDS not in repr(exchange)
    with pytest.raises(ExchangeError):
        make_protowallet(restored, "test", bdk.Network.BITCOIN)
    restored.keystores[0].fingerprint = "deadbeef"
    with pytest.raises(ExchangeError, match="fingerprint disagree"):
        make_protowallet(restored, "test", bdk.Network.TESTNET)


def test_mainnet_seed_is_used_for_public_metadata_only() -> None:
    exchange = from_sparrow_json(sparrow_seed("mainnet"))
    assert exchange.keystores[0].xpub
    assert exchange.keystores[0].non_mainnet_seed is None
    assert SYNTHETIC_WORDS not in exchange.to_json()
    obj = exchange.to_dict()
    obj["keystores"][0]["bip39_mnemonic"] = SYNTHETIC_WORDS
    with pytest.raises(ExchangeError, match="mainnet"):
        WalletExchange.from_dict(obj)


def test_seed_conflict_fails_and_passphrase_seed_is_not_assumed() -> None:
    source = sparrow_seed("testnet")
    signer = source["keystores"][0]
    signer["extendedPublicKey"] = _derived_account_pub(SYNTHETIC_WORDS, "m/84h/1h/1h", False)[0]
    with pytest.raises(ExchangeError, match="disagree"):
        from_sparrow_json(source)
    signer["seed"]["needsPassphrase"] = True
    assert from_sparrow_json(source).keystores[0].non_mainnet_seed is None


def test_electrum_bip39_infers_only_matching_origin() -> None:
    xpub, fingerprint = _derived_account_pub(SYNTHETIC_WORDS, "m/84h/1h/0h", False)
    source = {
        "wallet_type": "standard",
        "keystore": {
            "type": "bip32",
            "seed_type": "bip39",
            "seed": SYNTHETIC_WORDS,
            "xpub": xpub,
        },
    }
    key = from_electrum(source).keystores[0]
    assert (key.key_origin, key.fingerprint, key.non_mainnet_seed) == (
        "m/84h/1h/0h",
        fingerprint,
        SYNTHETIC_WORDS,
    )
    source["keystore"]["seed_type"] = "electrum"
    assert from_electrum(source).keystores[0].fingerprint is None


def test_bip39_passphrase_changes_public_derivation() -> None:
    assert _derived_account_pub(SYNTHETIC_WORDS, "m/84h/1h/0h", False) != _derived_account_pub(
        SYNTHETIC_WORDS, "m/84h/1h/0h", False, "hidden"
    )
