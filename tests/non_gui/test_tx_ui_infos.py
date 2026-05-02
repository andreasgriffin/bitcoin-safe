#
# Bitcoin Safe
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

from __future__ import annotations

from types import SimpleNamespace

from bitcoin_safe.tx import HiddenTxUiInfos, TxUiInfos
from bitcoin_safe.wallet import Wallet


def test_tx_ui_infos_roundtrip_preserves_save_local_on_send() -> None:
    """Hidden tx flags should survive serialization roundtrips."""
    txinfos = TxUiInfos(hidden=HiddenTxUiInfos(save_local_on_send=True))

    restored = TxUiInfos._from_dumps(txinfos.dumps())

    assert restored.hidden.save_local_on_send is True


def test_create_bump_fee_psbt_preserves_hidden_tx_infos(monkeypatch) -> None:
    """RBF creation should forward hidden tx metadata to the next viewer step."""

    class FakeReplaceTx:
        def input(self) -> list[object]:
            return []

        def output(self) -> list[object]:
            return []

        def compute_txid(self) -> str:
            return "old-txid"

    class FakeExtractedTx:
        def compute_txid(self) -> str:
            return "new-txid"

    class FakePsbt:
        def extract_tx(self) -> FakeExtractedTx:
            return FakeExtractedTx()

    class FakeBumpFeeTxBuilder:
        def __init__(self, txid: str, fee_rate) -> None:
            self.txid = txid
            self.fee_rate = fee_rate

        def finish(self, _bdkwallet) -> FakePsbt:
            return FakePsbt()

    monkeypatch.setattr("bitcoin_safe.wallet.bdk.BumpFeeTxBuilder", FakeBumpFeeTxBuilder)

    labels: list[tuple[str, str, str]] = []
    wallet = SimpleNamespace(
        network=None,
        bdkwallet=object(),
        config=SimpleNamespace(bitcoin_symbol=SimpleNamespace(value="BTC")),
        labels=SimpleNamespace(
            set_tx_label=lambda txid, label, timestamp: labels.append((txid, label, timestamp))
        ),
        get_txo_of_utxos=lambda _inputs: [],
        get_receiving_addresses=lambda: [],
        persist=lambda: None,
        determine_recipient_category=lambda _utxos: None,
    )

    hidden = HiddenTxUiInfos(save_local_on_send=True, tx_label="draft tx")
    txinfos = TxUiInfos(fee_rate=2.0, hidden=hidden)
    txinfos.replace_tx = FakeReplaceTx()

    builder_infos = Wallet.create_bump_fee_psbt(wallet, txinfos)

    assert builder_infos.hidden_tx_infos is hidden
    assert labels == [("new-txid", "draft tx", "now")]
