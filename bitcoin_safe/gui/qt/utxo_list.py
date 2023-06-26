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

from bitcoin_safe.pythonbdk_types import OutPoint

logger = logging.getLogger(__name__)


from typing import Optional, List, Dict, Sequence, Set, TYPE_CHECKING
import enum
import copy

from PySide2.QtCore import Qt
from PySide2.QtGui import QStandardItemModel, QStandardItem, QFont
from PySide2.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QLabel,
    QHBoxLayout,
    QApplication,
)
from .category_list import CategoryEditor

from ...wallet import Wallet

from ...i18n import _
from ...util import is_address, Satoshis, format_satoshis

from .util import ColorScheme, MONOSPACE_FONT, EnterButton, MessageBoxMixin
from .my_treeview import MyTreeView
import bdkpython as bdk
from ...signals import Signals


class UTXOList(MyTreeView, MessageBoxMixin):
    _utxo_dict: Dict[str, bdk.LocalUtxo]  # coin name -> coin

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
        Columns.OUTPOINT: _("Output point"),
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
    stretch_column = Columns.LABEL

    ROLE_PREVOUT_STR = Qt.UserRole + 1000
    key_role = ROLE_PREVOUT_STR
    key_column = Columns.OUTPOINT

    def __init__(
        self,
        config,
        signals: Signals,
        wallet_id=None,
        outpoint_domain=None,
        hidden_columns=None,
    ):
        super().__init__(
            config=config,
            stretch_column=self.stretch_column,
            editable_columns=[],
        )
        self.config = config
        self.wallet_id = wallet_id
        self.hidden_columns = hidden_columns if hidden_columns else []
        self.signals = signals
        self.outpoint_domain = outpoint_domain
        self._utxo_dict = {}
        self.std_model = QStandardItemModel(self)
        self.setModel(self.std_model)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)

        signals.utxos_updated.connect(self.update)

    def create_toolbar(self, config):
        toolbar, menu = self.create_toolbar_with_menu("")
        self.num_coins_label = toolbar.itemAt(0).widget()
        return toolbar

    def update(self):
        wallets_dict: Dict[str, Wallet] = self.signals.get_wallets()

        # not calling maybe_defer_update() as it interferes with coincontrol status bar
        utxos_dict = {
            wallet_id: wallet.get_utxos() for wallet_id, wallet in wallets_dict.items()
        }
        # utxos.sort(key=lambda x: x.block_height, reverse=True)
        self._utxo_dict = {}
        self.model().clear()
        self.update_headers(self.__class__.headers)
        idx = 0
        for wallet_id, utxos in utxos_dict.items():
            wallet: Wallet = wallets_dict[wallet_id]
            for utxo in utxos:
                if (
                    self.outpoint_domain is not None
                    and OutPoint.from_bdk(utxo.outpoint) not in self.outpoint_domain
                ):
                    continue
                name = wallet.get_utxo_name(utxo)
                self._utxo_dict[name] = utxo
                labels = [""] * len(self.Columns)
                labels[self.Columns.OUTPOINT] = str(name)
                labels[self.Columns.ADDRESS] = wallet.get_utxo_address(utxo).as_string()
                labels[self.Columns.AMOUNT] = format_satoshis(utxo.txout.value)
                labels[self.Columns.SATOSHIS] = str(utxo.txout.value)
                utxo_item = [QStandardItem(x) for x in labels]
                self.set_editability(utxo_item)
                utxo_item[self.Columns.OUTPOINT].setData(name, self.ROLE_PREVOUT_STR)
                utxo_item[self.Columns.OUTPOINT].setData(name, self.ROLE_CLIPBOARD_DATA)
                utxo_item[self.Columns.ADDRESS].setFont(QFont(MONOSPACE_FONT))
                utxo_item[self.Columns.ADDRESS].setData(
                    labels[self.Columns.ADDRESS], self.ROLE_CLIPBOARD_DATA
                )
                utxo_item[self.Columns.AMOUNT].setFont(QFont(MONOSPACE_FONT))
                utxo_item[self.Columns.AMOUNT].setData(
                    utxo.txout.value, self.ROLE_CLIPBOARD_DATA
                )
                utxo_item[self.Columns.PARENTS].setFont(QFont(MONOSPACE_FONT))
                utxo_item[self.Columns.OUTPOINT].setFont(QFont(MONOSPACE_FONT))
                self.model().insertRow(idx, utxo_item)
                self.refresh_row(name, idx, wallet)
                idx += 1
        self.filter()
        if hasattr(self, "num_coins_label"):
            self.num_coins_label.setText(
                _("{} unspent transaction outputs").format(len(utxos))
            )
        for hidden_column in self.hidden_columns:
            self.hideColumn(hidden_column)

    def refresh_row(self, key, row, wallet):
        assert row is not None
        utxo = self._utxo_dict[key]
        utxo_item = [self.std_model.item(row, col) for col in self.Columns]
        utxo_item[self.Columns.WALLET_ID].setText(wallet.id)
        utxo_item[self.Columns.WALLET_ID].setData(wallet.id, self.ROLE_CLIPBOARD_DATA)
        txid = utxo.outpoint.txid
        parents = wallet.get_tx_parents(txid)
        utxo_item[self.Columns.PARENTS].setText("%6s" % len(parents))
        utxo_item[self.Columns.PARENTS].setData(len(parents), self.ROLE_CLIPBOARD_DATA)
        address = wallet.get_utxo_address(utxo).as_string()
        category = wallet.get_category_for_address(address)
        utxo_item[self.Columns.CATEGORY].setText(category)
        utxo_item[self.Columns.CATEGORY].setData(category, self.ROLE_CLIPBOARD_DATA)
        label = wallet.get_label_for_txid(txid) or ""
        utxo_item[self.Columns.LABEL].setText(label)
        utxo_item[self.Columns.LABEL].setData(label, self.ROLE_CLIPBOARD_DATA)
        SELECTED_TO_SPEND_TOOLTIP = _("Coin selected to be spent")
        tooltip = key
        color = self._default_bg_brush
        for col in utxo_item:
            col.setBackground(color)
            col.setToolTip(tooltip)

        utxo_item[self.Columns.CATEGORY].setBackground(CategoryEditor.color(category))

    def get_selected_outpoints(self) -> List[str]:
        if not self.model():
            return []
        items = self.selected_in_column(self.Columns.OUTPOINT)
        return [x.data(self.ROLE_PREVOUT_STR) for x in items]

    def pay_to_clipboard_address(self, coins):
        addr = QApplication.clipboard().text()
        outputs = [bdk.LocalUtxo.from_address_and_value(addr, "!")]
        self.main_window.send_tab.pay_onchain_dialog(outputs)

    def on_double_click(self, idx):
        outpoint = idx.sibling(idx.row(), self.Columns.OUTPOINT).data(
            self.ROLE_PREVOUT_STR
        )
        utxo = self._utxo_dict[outpoint]
        self.signals.show_utxo.emit(utxo)

    def get_filter_data_from_coordinate(self, row, col):
        if col == self.Columns.OUTPOINT:
            return self.get_role_data_from_coordinate(
                row, col, role=self.ROLE_PREVOUT_STR
            )
        return super().get_filter_data_from_coordinate(row, col)
