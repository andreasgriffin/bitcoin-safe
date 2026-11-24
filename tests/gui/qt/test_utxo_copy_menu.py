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

from __future__ import annotations

import inspect
from datetime import datetime

import pytest
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from PyQt6.QtCore import QItemSelectionModel, QPoint
from PyQt6.QtGui import QStandardItem
from PyQt6.QtWidgets import QApplication, QMenu
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole, MyTreeView
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.pythonbdk_types import OutPoint, PythonUtxo, TxOut
from bitcoin_safe.tx import short_tx_id
from tests.gui.qt.helpers import Shutter, main_window_context, setup_single_sig_wallet
from tests.helpers import TestConfig as ConfigForTest
from tests.non_gui.test_foreign_utxo import transaction
from tests.non_gui.test_signers import test_seeds


def submenu(menu: QMenu, title: str) -> QMenu | None:
    return next((action.menu() for action in menu.actions() if action.text() == title), None)


def select_rows(view: MyTreeView, rows: list[int]) -> QPoint:
    selection = view.selectionModel()
    assert selection
    selection.clearSelection()
    column = next(iter(view.stretch_columns))
    index = view.proxy.mapFromSource(view._source_model.index(rows[0], column))
    for row in rows:
        source = view._source_model.index(row, column)
        selection.select(
            view.proxy.mapFromSource(source),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    view.scrollTo(index)
    return view.visualRect(index).center()


@pytest.mark.marker_qt_2
def test_copy_unspent_outpoints_from_transaction_and_address_lists(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: ConfigForTest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="copy_utxos",
            seed=test_seeds[0],
        )
        wallet = qt_wallet.wallet
        receiving = wallet.get_receiving_addresses()[0]
        change = wallet.get_change_addresses()[0]
        tx1 = transaction([b"\x00\x14" + b"\x11" * 20] * 4)
        tx2 = transaction([b"\x00\x14" + b"\x22" * 20])
        utxos = [
            PythonUtxo(
                address, OutPoint(txid=tx.compute_txid(), vout=vout), TxOut.from_bdk(tx.output()[vout])
            )
            for tx, vout, address in (
                (tx1, 0, receiving),
                (tx1, 1, receiving),
                (tx1, 2, change),
                (tx2, 0, receiving),
            )
        ]
        spent = PythonUtxo(
            receiving,
            OutPoint(txid=tx1.compute_txid(), vout=3),
            TxOut.from_bdk(tx1.output()[3]),
            is_spent_by_txid="ff" * 32,
        )
        wallet_outputs = utxos + [spent]
        monkeypatch.setattr(
            wallet,
            "get_all_utxos",
            lambda include_not_mine=False: [u for u in wallet_outputs if not u.is_spent_by_txid],
        )
        monkeypatch.setattr(Menu, "exec", lambda self, pos: None)
        amount = Satoshis(100_000, test_config.network).str_with_unit(
            color_formatting=None, btc_symbol=test_config.bitcoin_symbol.value
        )

        history = qt_wallet.history_list_with_toolbar.hist_list
        monkeypatch.setattr(history, "indexAt", lambda pos: history.selectionModel().selectedIndexes()[0])
        for tx in (tx1, tx2):
            items = [QStandardItem() for _ in history.Columns]
            items[history.Columns.TXID].setText(str(tx.compute_txid()))
            items[history.Columns.TXID].setData(str(tx.compute_txid()), MyItemDataRole.ROLE_KEY)
            items[history.Columns.WALLET_ID].setText(wallet.id)
            history._source_model.appendRow(items)
        rows = [history.find_row_by_key(str(tx.compute_txid())) for tx in (tx1, tx2)]
        assert all(row is not None for row in rows)
        row1, row2 = rows
        assert row1 is not None and row2 is not None
        menu = history.create_menu(select_rows(history, [row1]))
        copy = submenu(menu, "Copy")
        assert copy
        receiving_menu = submenu(copy, "Receiving UTXO")
        change_menu = submenu(copy, "Change UTXO")
        assert receiving_menu and change_menu
        assert len(receiving_menu.actions()) == 3
        total = Satoshis(200_000, test_config.network).str_with_unit(
            color_formatting=None, btc_symbol=test_config.bitcoin_symbol.value
        )
        assert receiving_menu.actions()[0].text() == f"All entries - total: {total}"
        assert receiving_menu.actions()[1].text() == f"{short_tx_id(str(utxos[0].outpoint))} - {amount}"
        receiving_menu.actions()[1].trigger()
        assert qapp.clipboard().text() == str(utxos[0].outpoint)
        receiving_menu.actions()[0].trigger()
        assert qapp.clipboard().text() == "\n".join(str(utxo.outpoint) for utxo in utxos[:2])
        assert len(change_menu.actions()) == 1
        assert change_menu.actions()[0].text() == f"{short_tx_id(str(utxos[2].outpoint))} - {amount}"
        change_menu.actions()[0].trigger()
        assert qapp.clipboard().text() == str(utxos[2].outpoint)
        menu = history.create_menu(select_rows(history, [row1, row2]))
        copy = submenu(menu, "Copy")
        assert copy
        receiving_menu = submenu(copy, "Receiving UTXO")
        assert receiving_menu and len(receiving_menu.actions()) == 4

        addresses = qt_wallet.address_list
        addresses.force_full_ui_creation()
        receiving_row = addresses.find_row_by_key(receiving)
        change_row = addresses.find_row_by_key(change)
        assert receiving_row is not None and change_row is not None
        menu = addresses.create_menu(select_rows(addresses, [receiving_row]))
        copy = submenu(menu, "Copy")
        assert copy
        receiving_menu = submenu(copy, "Receiving UTXO")
        assert receiving_menu and len(receiving_menu.actions()) == 4
        assert not submenu(copy, "Change UTXO")
        receiving_menu.actions()[1].trigger()
        assert qapp.clipboard().text() in {str(utxo.outpoint) for utxo in utxos if utxo.address == receiving}
        menu = addresses.create_menu(select_rows(addresses, [change_row]))
        copy = submenu(menu, "Copy")
        assert copy and not submenu(copy, "Receiving UTXO")
        change_menu = submenu(copy, "Change UTXO")
        assert change_menu and len(change_menu.actions()) == 1
        menu = addresses.create_menu(select_rows(addresses, [receiving_row, change_row]))
        copy = submenu(menu, "Copy")
        assert copy and submenu(copy, "Receiving UTXO") and submenu(copy, "Change UTXO")
        monkeypatch.setattr(wallet, "get_all_utxos", lambda include_not_mine=False: [])
        menu = addresses.create_menu(select_rows(addresses, [receiving_row]))
        copy = submenu(menu, "Copy")
        assert copy and not submenu(copy, "Receiving UTXO") and not submenu(copy, "Change UTXO")
        menu = history.create_menu(select_rows(history, [row1, row2]))
        assert not submenu(menu, "Copy")
