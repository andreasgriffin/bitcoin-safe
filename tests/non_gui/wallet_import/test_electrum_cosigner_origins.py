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

"""Electrum multisig origins must come from the original signing devices."""

import bdkpython as bdk
import pytest
from hwilib._base58 import encode_check as b58encode_check

from bitcoin_safe.wallet_import.bitcoin_safe_bridge import make_protowallet
from bitcoin_safe.wallet_import.descriptors import b58decode_check
from bitcoin_safe.wallet_import.electrum import complete_cosigner_origins, from_electrum
from bitcoin_safe.wallet_import.model import ExchangeError
from tests.non_gui.wallet_import.test_wallet_exchange import xpub


def electrum_multisig() -> dict:
    keys = []
    for number in range(1, 4):
        payload = bytearray(b58decode_check(xpub(0x02575483)))
        payload[13:45] = bytes([number]) * 32
        keys.append(b58encode_check(bytes(payload)))
    return {
        "wallet_type": "2of3",
        "x1": {"type": "bip32", "xpub": keys[0], "root_fingerprint": "abcdef12", "derivation": "m/48h/1h/0h"},
        "x2": {"type": "bip32", "xpub": keys[1]},
        "x3": {"type": "bip32", "xpub": keys[2]},
    }


def test_missing_origins_block_import_and_user_origins_preserve_policy() -> None:
    wallet = from_electrum(electrum_multisig())
    with pytest.raises(ExchangeError, match=r"signer\(s\) 2, 3"):
        make_protowallet(wallet, "imported", bdk.Network.TESTNET)
    original_keys = [key.xpub for key in wallet.keystores]
    complete_cosigner_origins(wallet, {2: ("deadbeef", "m/48h/1h/0h"), 3: ("12345678", "m/48h/1h/0h")})
    assert "[deadbeef/48h/1h/0h]" in wallet.descriptor
    assert "[12345678/48h/1h/0h]" in wallet.descriptor
    assert [key.xpub for key in wallet.keystores] == original_keys
    proto = make_protowallet(wallet, "imported", bdk.Network.TESTNET)
    assert proto.to_multipath_descriptor() is not None


@pytest.mark.parametrize(
    "origins, message",
    [
        ({2: ("bad", "m/48h/1h/0h")}, "fingerprint"),
        ({2: ("00000000", "m/48h/1h/0h")}, "genuine"),
        ({2: ("deadbeef", "m/48h/1h/0h/2h")}, "depth"),
        ({2: ("deadbeef", "m/48h/1h/1h")}, "does not match"),
        ({2: ("deadbeef", "m/48h/0h/0h")}, "network"),
        ({1: ("deadbeef", "m/48h/1h/0h")}, "disagrees"),
        ({4: ("deadbeef", "m/48h/1h/0h")}, "number"),
    ],
)
def test_invalid_origins_are_rejected(origins: dict[int, tuple[str, str]], message: str) -> None:
    wallet = from_electrum(electrum_multisig())
    with pytest.raises(ExchangeError, match=message):
        complete_cosigner_origins(wallet, origins)


def test_zero_fingerprint_is_replaced_and_duplicate_fingerprints_rejected() -> None:
    source = electrum_multisig()
    source["x2"]["root_fingerprint"] = "00000000"
    wallet = from_electrum(source)
    complete_cosigner_origins(wallet, {2: ("deadbeef", "m/48h/1h/0h"), 3: ("deadbeef", "m/48h/1h/0h")})
    assert wallet.keystores[1].fingerprint == "deadbeef"
    with pytest.raises(ExchangeError, match="same master fingerprint"):
        make_protowallet(wallet, "imported", bdk.Network.TESTNET)


@pytest.mark.parametrize(
    "missing", [("root_fingerprint",), ("derivation",), ("root_fingerprint", "derivation")]
)
def test_standard_wallet_origins_can_be_completed(missing: tuple[str, ...]) -> None:
    keystore = {
        "type": "bip32",
        "xpub": xpub(0x045F1CF6),
        "root_fingerprint": "abcdef12",
        "derivation": "m/84h/1h/0h",
    }
    for field in missing:
        del keystore[field]
    wallet = from_electrum({"wallet_type": "standard", "keystore": keystore})
    with pytest.raises(ExchangeError, match="lack a master fingerprint or derivation path"):
        make_protowallet(wallet, "imported", bdk.Network.TESTNET)
    complete_cosigner_origins(wallet, {1: ("abcdef12", "m/84h/1h/0h")})
    assert wallet.descriptor.startswith("wpkh([abcdef12/84h/1h/0h]")
    assert make_protowallet(wallet, "imported", bdk.Network.TESTNET).to_multipath_descriptor() is not None
