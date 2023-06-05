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
logger = logging.getLogger(__name__)


from typing import Optional, List, Dict, Sequence, Set, TYPE_CHECKING
import enum
import copy

from PySide2.QtCore import Qt
from PySide2.QtGui import QStandardItemModel, QStandardItem, QFont
from PySide2.QtWidgets import QAbstractItemView, QMenu, QLabel, QHBoxLayout, QApplication
from .category_list import CategoryEditor

from bitcoin_safe.wallet import Wallet

from ...i18n import _
from ...util import is_address, Satoshis, format_satoshis

from .util import ColorScheme, MONOSPACE_FONT, EnterButton,    MessageBoxMixin
from .my_treeview import MyTreeView
import bdkpython as bdk
from ...signals import Signals

PartialTxInput =PartialTxOutput = bdk.PartiallySignedTransaction


class UTXOList(MyTreeView, MessageBoxMixin):
    _spend_set: Set[str]  # coins selected by the user to spend from
    _utxo_dict: Dict[str, PartialTxInput]  # coin name -> coin

    class Columns(MyTreeView.BaseColumnsEnum):
        WALLET_ID = enum.auto()
        OUTPOINT = enum.auto()
        ADDRESS = enum.auto()
        CATEGORY = enum.auto()
        LABEL = enum.auto()
        AMOUNT = enum.auto()
        PARENTS = enum.auto()

    headers = {
        Columns.WALLET_ID: _('Wallet'),
        Columns.OUTPOINT: _('Output point'),
        Columns.ADDRESS: _('Address'),
        Columns.PARENTS: _('Parents'),
        Columns.CATEGORY: _('Category'),
        Columns.LABEL: _('Label'),
        Columns.AMOUNT: _('Amount'),
    }
    filter_columns = [Columns.ADDRESS, Columns.CATEGORY, Columns.LABEL, Columns.OUTPOINT]
    stretch_column = Columns.LABEL

    ROLE_PREVOUT_STR = Qt.UserRole + 1000
    key_role = ROLE_PREVOUT_STR

    def __init__(self, config, wallet:Wallet, signals:Signals, hidden_columns=None):
        super().__init__(
            config=config,
            stretch_column=self.stretch_column,
            editable_columns=[],
            )
        self.config = config
        self.hidden_columns = hidden_columns if hidden_columns else []
        self.signals = signals
        self._spend_set = set()
        self._utxo_dict = {}
        self.wallet = wallet
        self.std_model = QStandardItemModel(self)
        self.setModel(self.std_model)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)
        
        signals.utxos_updated.connect(self.update)


    def create_toolbar(self, config):
        toolbar, menu = self.create_toolbar_with_menu('')
        self.num_coins_label = toolbar.itemAt(0).widget()
        return toolbar

    def update(self):
        # not calling maybe_defer_update() as it interferes with coincontrol status bar
        utxos = self.wallet.get_utxos()
        # utxos.sort(key=lambda x: x.block_height, reverse=True)
        self._utxo_dict = {}
        self.model().clear()
        self.update_headers(self.__class__.headers)
        for idx, utxo in enumerate(utxos):
            name = self.wallet.get_utxo_name( utxo)
            self._utxo_dict[name] = utxo
            labels = [""] * len(self.Columns)
            labels[self.Columns.OUTPOINT] = str(name)
            labels[self.Columns.ADDRESS] = self.wallet.get_utxo_address(utxo).as_string()
            labels[self.Columns.AMOUNT] = format_satoshis(utxo.txout.value)
            utxo_item = [QStandardItem(x) for x in labels]
            self.set_editability(utxo_item)
            utxo_item[self.Columns.OUTPOINT].setData(name, self.ROLE_PREVOUT_STR)
            utxo_item[self.Columns.ADDRESS].setFont(QFont(MONOSPACE_FONT))
            utxo_item[self.Columns.AMOUNT].setFont(QFont(MONOSPACE_FONT))
            utxo_item[self.Columns.PARENTS].setFont(QFont(MONOSPACE_FONT))
            utxo_item[self.Columns.OUTPOINT].setFont(QFont(MONOSPACE_FONT))
            self.model().insertRow(idx, utxo_item)
            self.refresh_row(name, idx)
        self.filter()
        if hasattr(self, 'num_coins_label'):
            self.num_coins_label.setText(_('{} unspent transaction outputs').format(len(utxos)))
        for hidden_column in self.hidden_columns:
            self.hideColumn(hidden_column)

    def refresh_row(self, key, row):
        assert row is not None
        utxo = self._utxo_dict[key]
        utxo_item = [self.std_model.item(row, col) for col in self.Columns]
        utxo_item[self.Columns.WALLET_ID].setText(self.wallet.id)
        txid = utxo.outpoint.txid
        parents = self.wallet.get_tx_parents(txid)
        utxo_item[self.Columns.PARENTS].setText('%6s'%len(parents))
        address = self.wallet.get_utxo_address( utxo).as_string()
        category = self.wallet.get_category_for_address(address)
        utxo_item[self.Columns.CATEGORY].setText(category)        
        label = self.wallet.get_label_for_txid(txid) or ''
        utxo_item[self.Columns.LABEL].setText(label)
        SELECTED_TO_SPEND_TOOLTIP = _('Coin selected to be spent')
        if key in self._spend_set:
            tooltip = key + "\n" + SELECTED_TO_SPEND_TOOLTIP
            color = ColorScheme.GREEN.as_color(True)
        else:
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


    def get_spend_list(self) -> Optional[Sequence[PartialTxInput]]:
        if not bool(self._spend_set):
            return None
        utxos = [self._utxo_dict[x] for x in self._spend_set]
        return copy.deepcopy(utxos)  # copy so that side-effects don't affect utxo_dict



    def pay_to_clipboard_address(self, coins):
        addr = QApplication.clipboard().text()
        outputs = [PartialTxOutput.from_address_and_value(addr, '!')]
        self.main_window.send_tab.pay_onchain_dialog(outputs)

    def on_double_click(self, idx):
        outpoint = idx.sibling(idx.row(), self.Columns.OUTPOINT).data(self.ROLE_PREVOUT_STR)
        utxo = self._utxo_dict[outpoint]
        self.signals.show_utxo(utxo)

    def create_menu(self, position):
        selected = self.get_selected_outpoints()
        menu = QMenu()
        menu.setSeparatorsCollapsible(True)  # consecutive separators are merged together
        coins = [self._utxo_dict[name] for name in selected]
        if not coins:
            return
        if len(coins) == 1:
            idx = self.indexAt(position)
            if not idx.isValid():
                return
            utxo = coins[0]
            txid = utxo.prevout.txid.hex()
            # "Details"
            tx = self.wallet.adb.get_transaction(txid)
            if tx:
                label = self.wallet.get_label_for_txid(txid)
                menu.addAction(_("Privacy analysis"), lambda: self.signals.show_utxo(utxo))
            cc = self.add_copy_menu(menu, idx)
            cc.addAction(_("Long Output point"), lambda: self.place_text_on_clipboard(utxo.prevout.to_str(), title="Long Output point"))
        # fully spend
        menu_spend = menu.addMenu(_("Fully spend") + '…')
        m = menu_spend.addAction(_("send to address in clipboard"), lambda: self.pay_to_clipboard_address(coins))
        m.setEnabled(self.clipboard_contains_address())
        # coin control
        # Freeze menu
        if len(coins) == 1:
            utxo = coins[0]
            addr = utxo.address
        elif len(coins) > 1:  # multiple items selected
            menu.addSeparator()
            addrs = [utxo.address for utxo in coins]
            # is_coin_frozen = [self.wallet.is_frozen_coin(utxo) for utxo in coins]
            # is_addr_frozen = [self.wallet.is_frozen_address(utxo.address) for utxo in coins]
            # menu_freeze = menu.addMenu(_("Freeze"))
            # if not all(is_coin_frozen):
            #     menu_freeze.addAction(_("Freeze Coins"), lambda: self.wallet.set_frozen_state_of_coins(coins, True))
            # if any(is_coin_frozen):
            #     menu_freeze.addAction(_("Unfreeze Coins"), lambda: self.wallet.set_frozen_state_of_coins(coins, False))
            # if not all(is_addr_frozen):
            #     menu_freeze.addAction(_("Freeze Addresses"), lambda: self.wallet.set_frozen_state_of_addresses(addrs, True))
            # if any(is_addr_frozen):
            #     menu_freeze.addAction(_("Unfreeze Addresses"), lambda: self.wallet.set_frozen_state_of_addresses(addrs, False))

        menu.exec_(self.viewport().mapToGlobal(position))

    def get_filter_data_from_coordinate(self, row, col):
        if col == self.Columns.OUTPOINT:
            return self.get_role_data_from_coordinate(row, col, role=self.ROLE_PREVOUT_STR)
        return super().get_filter_data_from_coordinate(row, col)
