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

from unittest.mock import Mock

import bdkpython as bdk
import pytest

from bitcoin_safe.wallet_import.adapters import from_descriptor
from bitcoin_safe.wallet_import.bitcoin_safe_bridge import (
    apply_bip329_labels,
    label_import_data,
    make_protowallet,
)
from bitcoin_safe.wallet_import.model import ExchangeError, Label, WalletExchange

from .test_wallet_exchange import expressions, xpub


def test_bridge_preserves_descriptor_and_wallet_name() -> None:
    exchange = from_descriptor(expressions()[2])
    exchange.gap_limit = 37
    proto = make_protowallet(exchange, "Imported", bdk.Network.BITCOIN)
    assert proto.id == "Imported"
    assert proto.gap == 37
    assert proto.to_multipath_descriptor() is not None


def test_bridge_rejects_partial_and_changed_policy() -> None:
    with pytest.raises(ExchangeError, match="complete receive and change"):
        make_protowallet(from_descriptor(expressions()[0]), "Partial", bdk.Network.BITCOIN)
    key = xpub()
    second = xpub(0x0488B21E)
    descriptor = f"wsh(multi(2,[f00dbabe/48h/0h/0h/2h]{key}/<0;1>/*,[abcd1234/48h/0h/0h/2h]{second}/<0;1>/*))"
    with pytest.raises(ExchangeError, match="Unsupported wallet descriptor"):
        make_protowallet(from_descriptor(descriptor), "Unsorted", bdk.Network.BITCOIN)


def test_bridge_filters_ambiguous_labels_and_warns_about_freezes() -> None:
    exchange = WalletExchange("test", "Test")
    exchange.labels = [
        Label("tx", "a", "First"),
        Label("addr", "a", "Second"),
        Label("tx", "b", "Keep"),
        Label("wallet", "c", "Unsupported"),
    ]
    exchange.frozen_outpoints = ["a" * 64 + ":0"]
    data, warnings = label_import_data(exchange)
    assert '"ref": "b"' in data
    assert '"ref": "a"' not in data
    assert any("ambiguous" in warning for warning in warnings)
    assert any("not protected" in warning for warning in warnings)
    wallet = Mock()
    assert apply_bip329_labels(wallet, exchange) == warnings
    wallet.labels.import_bip329_jsonlines.assert_called_once_with(data)


def test_labels_survive_wallet_serialization(test_config, loop_in_thread) -> None:
    from bitcoin_safe.wallet import Wallet

    key = xpub(0x043587CF)
    exchange = from_descriptor(f"wpkh([f00dbabe/84h/1h/0h]{key}/<0;1>/*)")
    exchange.labels = [Label("tx", "a" * 64, "Imported label")]
    proto = make_protowallet(exchange, "Imported", test_config.network)
    wallet = Wallet.from_protowallet(proto, test_config, loop_in_thread=loop_in_thread)
    apply_bip329_labels(wallet, exchange)
    assert "Imported label" in wallet.labels.dumps()


def test_source_network_inference_survives_import_metadata() -> None:
    key = xpub(0x043587CF)
    exchange = from_descriptor(f"wpkh([f00dbabe/84h/1h/0h]{key}/<0;1>/*)")
    assert exchange.network == "testnet"
    assert exchange.extra["network_inferred_from_keys"] is True
