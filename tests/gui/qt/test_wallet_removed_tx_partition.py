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

from dataclasses import dataclass

import bitcoin_safe.gui.qt.qt_wallet as qt_wallet_module
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.wallet import Wallet


@dataclass
class _Tx:
    txid: str
    transaction: object
    sent: int = 0


@dataclass
class _PythonUtxo:
    is_spent_by_txid: str | None


class _DirectReplacementWalletHarness:
    def __init__(self, replacements_by_transaction: dict[object, list[_PythonUtxo]]) -> None:
        self.replacements_by_transaction = replacements_by_transaction

    def get_conflicting_python_txos(self, prev_outpoints: object) -> list[_PythonUtxo]:
        return self.replacements_by_transaction.get(prev_outpoints, [])

    def get_replacing_txids_for_outpoints(
        self, prev_outpoints: object, replaced_txid: str | None = None
    ) -> set[str]:
        return Wallet.get_replacing_txids_for_outpoints(
            self,
            prev_outpoints,
            replaced_txid=replaced_txid,
        )


def test_wallet_get_replacing_txids_for_outpoints_returns_conflicting_spenders() -> None:
    wallet = _DirectReplacementWalletHarness(
        replacements_by_transaction={
            "prev-outs": [
                _PythonUtxo(is_spent_by_txid="replacement-1"),
                _PythonUtxo(is_spent_by_txid="replacement-2"),
            ]
        }
    )

    replacing_txids = Wallet.get_replacing_txids_for_outpoints(wallet, "prev-outs")

    assert replacing_txids == {"replacement-1", "replacement-2"}


def test_wallet_get_replacing_txids_for_outpoints_excludes_removed_txid() -> None:
    wallet = _DirectReplacementWalletHarness(
        replacements_by_transaction={
            "prev-outs": [
                _PythonUtxo(is_spent_by_txid="removed-tx"),
                _PythonUtxo(is_spent_by_txid="replacement-1"),
            ]
        }
    )

    replacing_txids = Wallet.get_replacing_txids_for_outpoints(
        wallet,
        "prev-outs",
        replaced_txid="removed-tx",
    )

    assert replacing_txids == {"replacement-1"}


def test_wallet_get_replacing_txids_for_outpoints_returns_empty_for_no_conflicts() -> None:
    wallet = _DirectReplacementWalletHarness(replacements_by_transaction={"prev-outs": []})

    replacing_txids = Wallet.get_replacing_txids_for_outpoints(wallet, "prev-outs")

    assert replacing_txids == set()


class _DirectReplacementHarness:
    def __init__(self, wallet: _DirectReplacementWalletHarness) -> None:
        self.wallet = wallet


def test_get_replacing_txids_for_removed_tx_partitions_by_removed_tx(monkeypatch) -> None:
    tx_replaced = _Tx(txid="removed-replaced", transaction=object())
    tx_unreplaced = _Tx(txid="removed-unreplaced", transaction=object())
    harness = _DirectReplacementHarness(
        wallet=_DirectReplacementWalletHarness(
            replacements_by_transaction={
                tx_replaced.transaction: [_PythonUtxo(is_spent_by_txid="replacement-1")],
                tx_unreplaced.transaction: [],
            }
        )
    )
    monkeypatch.setattr(qt_wallet_module, "get_prev_outpoints", lambda tx: tx)

    unreplaced_txs, replacement_txids_by_removed_txid = QTWallet._get_replacing_txids_for_removed_tx(
        harness, [tx_replaced, tx_unreplaced]
    )

    assert [tx.txid for tx in unreplaced_txs] == ["removed-unreplaced"]
    assert replacement_txids_by_removed_txid == {"removed-replaced": {"replacement-1"}}


class _LikelyReplacementWalletHarness:
    def __init__(self, address_amounts_by_transaction: dict[object, dict[str, int]]) -> None:
        self.address_amounts_by_transaction = address_amounts_by_transaction

    def get_addresses(self) -> list[str]:
        return ["wallet-addr"]

    def get_summed_output_address_and_amount_dict(self, transaction: object) -> dict[str, int]:
        return self.address_amounts_by_transaction.get(transaction, {})


class _LikelyReplacementHarness:
    def __init__(self, wallet: _LikelyReplacementWalletHarness) -> None:
        self.wallet = wallet


def test_get_txids_of_likely_receive_replacements_matches_single_removed_tx() -> None:
    tx_replaced = _Tx(txid="removed-replaced", transaction=object())
    tx_unreplaced = _Tx(txid="removed-unreplaced", transaction=object())
    appended_tx = _Tx(txid="replacement-2", transaction=object())
    harness = _LikelyReplacementHarness(
        wallet=_LikelyReplacementWalletHarness(
            address_amounts_by_transaction={
                tx_replaced.transaction: {"wallet-addr": 42},
                tx_unreplaced.transaction: {"wallet-addr": 21},
                appended_tx.transaction: {"wallet-addr": 42},
            }
        )
    )

    replaced_unreplaced_txs, replaced_txids_by_removed_txid = (
        QTWallet._get_txids_of_likely_receive_replacements(harness, [tx_replaced], [appended_tx])
    )

    assert replaced_unreplaced_txs == []
    assert replaced_txids_by_removed_txid == {"removed-replaced": {"replacement-2"}}

    unreplaced_txs, replacement_txids_by_removed_txid = QTWallet._get_txids_of_likely_receive_replacements(
        harness, [tx_unreplaced], [appended_tx]
    )

    assert [tx.txid for tx in unreplaced_txs] == ["removed-unreplaced"]
    assert replacement_txids_by_removed_txid == {}


def test_get_txids_of_likely_receive_replacements_returns_nothing_for_spends() -> None:
    tx_removed_send = _Tx(txid="removed-send", transaction=object(), sent=1)
    appended_tx = _Tx(txid="replacement-2", transaction=object(), sent=0)
    harness = _LikelyReplacementHarness(
        wallet=_LikelyReplacementWalletHarness(
            address_amounts_by_transaction={
                tx_removed_send.transaction: {"wallet-addr": 42},
                appended_tx.transaction: {"wallet-addr": 42},
            }
        )
    )

    unreplaced_txs, replacement_txids_by_removed_txid = QTWallet._get_txids_of_likely_receive_replacements(
        harness, [tx_removed_send], [appended_tx]
    )

    assert [tx.txid for tx in unreplaced_txs] == ["removed-send"]
    assert replacement_txids_by_removed_txid == {}
