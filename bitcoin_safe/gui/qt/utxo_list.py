#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2015 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
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

import logging

from ...pythonbdk_types import OutPoint

logger = logging.getLogger(__name__)


from typing import Optional, List, Dict, Tuple, Sequence, Set, TYPE_CHECKING
import enum
import copy

from PySide2.QtCore import Qt, QPersistentModelIndex
from PySide2.QtGui import QStandardItemModel, QStandardItem, QFont, QIcon
from PySide2.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QLabel,
    QHBoxLayout,
    QApplication,
    QHeaderView,
)
from .category_list import CategoryEditor

from ...wallet import TxStatus, Wallet

from ...i18n import _
from ...util import is_address, Satoshis, format_satoshis

from .util import (
    ColorScheme,
    MONOSPACE_FONT,
    EnterButton,
    MessageBoxMixin,
    read_QIcon,
    TX_ICONS,
    sort_id_to_icon,
)
from .my_treeview import MyTreeView, MySortModel, MyStandardItemModel
import bdkpython as bdk
from ...signals import Signals


class UTXOList(MyTreeView, MessageBoxMixin):
    class Columns(MyTreeView.BaseColumnsEnum):
        WALLET_ID = enum.auto()
        OUTPOINT = enum.auto()
        ADDRESS = enum.auto()
        CATEGORY = enum.auto()
        LABEL = enum.auto()
        AMOUNT = enum.auto()
        SATOSHIS = enum.auto()
        PARENTS = enum.auto()

    headers = {
        Columns.WALLET_ID: _("Wallet"),
        Columns.OUTPOINT: _("Outpoint"),
        Columns.ADDRESS: _("Address"),
        Columns.PARENTS: _("Parents"),
        Columns.CATEGORY: _("Category"),
        Columns.LABEL: _("Label"),
        Columns.AMOUNT: _("Amount"),
        Columns.SATOSHIS: _("SATOSHIS"),
    }
    filter_columns = [
        Columns.ADDRESS,
        Columns.CATEGORY,
        Columns.LABEL,
        Columns.OUTPOINT,
    ]
    column_alignments = {
        Columns.WALLET_ID: Qt.AlignCenter,
        Columns.OUTPOINT: Qt.AlignLeft,
        Columns.ADDRESS: Qt.AlignLeft,
        Columns.CATEGORY: Qt.AlignCenter,
        Columns.LABEL: Qt.AlignLeft,
        Columns.AMOUNT: Qt.AlignRight,
        Columns.SATOSHIS: Qt.AlignRight,
        Columns.PARENTS: Qt.AlignCenter,
    }

    stretch_column = Columns.LABEL
    key_column = Columns.OUTPOINT

    def __init__(
        self,
        config,
        signals: Signals,
        get_outpoints,
        hidden_columns=None,
    ):
        super().__init__(
            config=config,
            stretch_column=self.stretch_column,
            editable_columns=[],
        )
        self.config = config
        self.hidden_columns = hidden_columns if hidden_columns else []
        self.signals = signals
        self.get_outpoints = get_outpoints
        self._tx_dict: Dict[
            OutPoint, bdk.TransactionDetails
        ] = {}  # outpoint --> txdetails
        self._wallet_dict: Dict[OutPoint, Wallet] = {}  # outpoint --> wallet

        self.std_model = MyStandardItemModel(self, drag_key="outpoints")
        self.proxy = MySortModel(self, sort_role=self.ROLE_SORT_ORDER)
        self.proxy.setSourceModel(self.std_model)
        self.setModel(self.proxy)

        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)

        self.update()
        self.sortByColumn(self.Columns.ADDRESS, Qt.AscendingOrder)

        signals.utxos_updated.connect(self.update)

        # self.setDragEnabled(True)
        # self.setAcceptDrops(True)
        # self.viewport().setAcceptDrops(True)
        # self.setDropIndicatorShown(True)
        # self.setDragDropMode(QAbstractItemView.InternalMove)
        # self.setDefaultDropAction(Qt.MoveAction)

    def create_toolbar(self, config):
        toolbar, menu = self.create_toolbar_with_menu("")
        self.num_coins_label = toolbar.itemAt(0).widget()
        return toolbar

    def update(self):
        if self.maybe_defer_update():
            return

        current_key = self.get_role_data_for_current_item(
            col=self.key_column, role=self.ROLE_KEY
        )

        wallets_dict: Dict[str, Wallet] = self.signals.get_wallets()

        # build dicts to look up the outpoints later (fast)
        self._tx_dict = {}  # outpoint --> txdetails
        self._wallet_dict = {}  # outpoint --> wallet
        for wallet in wallets_dict.values():
            tx_dict = wallet.get_outpoint_dict(
                wallet.get_list_transactions(), must_be_mine=True
            )
            self._tx_dict.update(tx_dict)
            self._wallet_dict.update(dict.fromkeys(tx_dict.keys(), wallet))

        self.model().clear()
        self.update_headers(self.__class__.headers)
        set_idx = None
        for outpoint in self.get_outpoints():
            outpoint = OutPoint.from_bdk(outpoint)
            txdetails = self._tx_dict.get(outpoint, None)

            txout = txdetails.transaction.output()[outpoint.vout] if txdetails else None

            labels = [""] * len(self.Columns)
            labels[self.Columns.OUTPOINT] = str(outpoint)
            labels[self.Columns.ADDRESS] = (
                bdk.Address.from_script(
                    txout.script_pubkey, self.config.network_settings.network
                ).as_string()
                if txout
                else "unknown"
            )
            labels[self.Columns.AMOUNT] = (
                format_satoshis(txout.value) if txout else "unknown"
            )
            labels[self.Columns.SATOSHIS] = str(txout.value) if txout else "unknown"
            items = [QStandardItem(x) for x in labels]
            self.set_editability(items)
            items[self.Columns.OUTPOINT].setData(outpoint, self.ROLE_KEY)
            items[self.Columns.OUTPOINT].setData(
                str(outpoint), self.ROLE_CLIPBOARD_DATA
            )
            items[self.Columns.OUTPOINT].setToolTip(str(outpoint))

            items[self.Columns.ADDRESS].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.ADDRESS].setData(
                labels[self.Columns.ADDRESS], self.ROLE_CLIPBOARD_DATA
            )
            items[self.Columns.ADDRESS].setToolTip(labels[self.Columns.ADDRESS])
            items[self.Columns.AMOUNT].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.AMOUNT].setData(
                txout.value if txout else "unknown", self.ROLE_CLIPBOARD_DATA
            )
            items[self.Columns.PARENTS].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.OUTPOINT].setFont(QFont(MONOSPACE_FONT))

            # add item
            count = self.std_model.rowCount()
            self.std_model.insertRow(count, items)
            self.refresh_row(outpoint, count, wallet)
            idx = self.std_model.index(count, self.Columns.LABEL)
            if outpoint == current_key:
                set_idx = QPersistentModelIndex(idx)
        if set_idx:
            self.set_current_idx(set_idx)

        if hasattr(self, "num_coins_label"):
            self.num_coins_label.setText(_("{} transaction outpoints").format(len(idx)))

        self.header().setSectionResizeMode(
            self.Columns.OUTPOINT, QHeaderView.Interactive
        )
        self.header().resizeSection(self.Columns.OUTPOINT, 50)

        self.header().setSectionResizeMode(
            self.Columns.ADDRESS, QHeaderView.Interactive
        )
        self.header().resizeSection(self.Columns.ADDRESS, 50)

        # show/hide self.Columns
        self.filter()
        self.proxy.setDynamicSortFilter(True)
        for hidden_column in self.hidden_columns:
            self.hideColumn(hidden_column)

    def refresh_row(self, key: bdk.OutPoint, row, wallet):
        assert row is not None

        outpoint = OutPoint.from_bdk(key)
        txdetails: bdk.TransactionDetails = self._tx_dict.get(outpoint, None)
        wallet: Wallet = self._wallet_dict.get(outpoint, None)
        txout = txdetails.transaction.output()[outpoint.vout] if txdetails else None

        items = [self.std_model.item(row, col) for col in self.Columns]

        sort_id = wallet.get_tx_status(txdetails).sort_id if txdetails else -1
        items[self.Columns.ADDRESS].setData(sort_id, self.ROLE_SORT_ORDER)

        items[self.Columns.ADDRESS].setIcon(
            read_QIcon(sort_id_to_icon(sort_id) if txdetails else None)
        )

        items[self.Columns.WALLET_ID].setText(wallet.id if wallet else "unknown")
        items[self.Columns.WALLET_ID].setData(
            wallet.id if wallet else "unknown", self.ROLE_CLIPBOARD_DATA
        )
        txid = outpoint.txid
        parents = wallet.get_tx_parents(txid) if wallet else []
        items[self.Columns.PARENTS].setText("%6s" % len(parents))
        items[self.Columns.PARENTS].setData(len(parents), self.ROLE_CLIPBOARD_DATA)

        address = (
            bdk.Address.from_script(
                txout.script_pubkey, self.config.network_settings.network
            ).as_string()
            if txout
            else "unknown"
        )
        category = wallet.get_category_for_address(address) if wallet else ""

        items[self.Columns.CATEGORY].setText(category)
        items[self.Columns.CATEGORY].setData(category, self.ROLE_CLIPBOARD_DATA)
        label = wallet.get_label_for_txid(txid) or "" if wallet else ""
        items[self.Columns.LABEL].setText(label)
        items[self.Columns.LABEL].setData(label, self.ROLE_CLIPBOARD_DATA)
        color = self._default_bg_brush
        for col in items:
            col.setBackground(color)

        items[self.Columns.CATEGORY].setBackground(CategoryEditor.color(category))
        if txout and wallet.bdkwallet.is_mine(txout.script_pubkey):
            color = (
                ColorScheme.YELLOW.as_color(background=True)
                if wallet.is_change(address)
                else ColorScheme.GREEN.as_color(background=True)
            )
            items[self.Columns.ADDRESS].setBackground(color)

    def get_selected_outpoints(self) -> List[str]:
        if not self.model():
            return []
        items = self.selected_in_column(self.Columns.OUTPOINT)
        return [x.data(self.ROLE_KEY) for x in items]

    def pay_to_clipboard_address(self, coins):
        addr = QApplication.clipboard().text()
        outputs = [bdk.LocalUtxo.from_address_and_value(addr, "!")]
        self.main_window.send_tab.pay_onchain_dialog(outputs)

    def on_double_click(self, idx):
        outpoint = idx.sibling(idx.row(), self.Columns.OUTPOINT).data(self.ROLE_KEY)
        (wallet, utxo, _) = self._tx_dict[outpoint]
        self.signals.show_utxo.emit(utxo)

    def get_filter_data_from_coordinate(self, row, col):
        if col == self.Columns.OUTPOINT:
            return self.get_role_data_from_coordinate(row, col, role=self.ROLE_KEY)
        return super().get_filter_data_from_coordinate(row, col)
