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

from ...config import UserConfig
from ...pythonbdk_types import OutPoint, PythonUtxo

logger = logging.getLogger(__name__)


import enum
from typing import Dict, List, Optional, Tuple

import bdkpython as bdk
from PySide2.QtCore import (
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QSortFilterProxyModel,
    Qt,
)
from PySide2.QtGui import QFont, QStandardItem
from PySide2.QtWidgets import QAbstractItemView, QHeaderView, QMenu

from ...i18n import _
from ...signals import Signals, UpdateFilter
from ...util import Satoshis, block_explorer_URL
from ...wallet import TxStatus, Wallet, get_wallets
from .category_list import CategoryEditor
from .my_treeview import MySortModel, MyStandardItemModel, MyTreeView
from .util import MONOSPACE_FONT, ColorScheme, read_QIcon, sort_id_to_icon, webopen


def icon_of_utxo(is_spent_by_txid: Optional[str], confirmation_time: bdk.BlockTime, sort_id: int) -> str:
    if not confirmation_time and is_spent_by_txid:
        return "unconfirmed_child.svg"
    return sort_id_to_icon(sort_id)


def tooltip_text_of_utxo(is_spent_by_txid: Optional[str], confirmation_time: bdk.BlockTime) -> str:
    if not confirmation_time:
        if is_spent_by_txid:
            return f"Unconfirmed UTXO is spent by transaction {is_spent_by_txid}"
        else:
            return "Unconfirmed UTXO"

    return f"Confirmed UTXO"


class UTXOList(MyTreeView):
    class Columns(MyTreeView.BaseColumnsEnum):
        STATUS = enum.auto()
        WALLET_ID = enum.auto()
        OUTPOINT = enum.auto()
        ADDRESS = enum.auto()
        CATEGORY = enum.auto()
        LABEL = enum.auto()
        AMOUNT = enum.auto()
        PARENTS = enum.auto()

    headers = {
        Columns.STATUS: _(""),
        Columns.WALLET_ID: _("Wallet"),
        Columns.OUTPOINT: _("Outpoint"),
        Columns.ADDRESS: _("Address"),
        Columns.CATEGORY: _("Category"),
        Columns.LABEL: _("Label"),
        Columns.AMOUNT: _("Amount"),
        Columns.PARENTS: _("Parents"),
    }
    filter_columns = [
        Columns.WALLET_ID,
        Columns.OUTPOINT,
        Columns.ADDRESS,
        Columns.CATEGORY,
        Columns.LABEL,
        Columns.AMOUNT,
    ]
    column_alignments = {
        Columns.STATUS: Qt.AlignHCenter | Qt.AlignVCenter,
        Columns.WALLET_ID: Qt.AlignHCenter | Qt.AlignVCenter,
        Columns.OUTPOINT: Qt.AlignLeft | Qt.AlignVCenter,
        Columns.ADDRESS: Qt.AlignLeft | Qt.AlignVCenter,
        Columns.CATEGORY: Qt.AlignCenter | Qt.AlignVCenter,
        Columns.LABEL: Qt.AlignLeft | Qt.AlignVCenter,
        Columns.AMOUNT: Qt.AlignRight | Qt.AlignVCenter,
        Columns.PARENTS: Qt.AlignCenter | Qt.AlignVCenter,
    }

    column_widths = {Columns.STATUS: 15, Columns.ADDRESS: 100, Columns.AMOUNT: 100}
    stretch_column = Columns.LABEL
    key_column = Columns.OUTPOINT

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        get_outpoints,
        hidden_columns=None,
        txout_dict: Optional[Dict[str, bdk.TxOut]] = None,
        keep_outpoint_order=False,
    ):
        """_summary_

        Args:
            config (UserConfig): _description_
            signals (Signals): _description_
            get_outpoints (_type_): _description_
            hidden_columns (_type_, optional): _description_. Defaults to None.
            txout_dict (Dict[str, bdk.TxOut], optional): Can be used to augment the list with infos, if the utxo is not from the own wallet. Defaults to None.
            keep_outpoint_order (bool, optional): _description_. Defaults to False.
        """
        super().__init__(
            config=config,
            stretch_column=self.stretch_column,
            column_widths=self.column_widths,
            editable_columns=[],
        )
        self.config: UserConfig = config
        self.keep_outpoint_order = keep_outpoint_order
        self.hidden_columns = hidden_columns if hidden_columns else []
        self.signals = signals
        self.get_outpoints = get_outpoints
        self.txout_dict: Dict[str, bdk.TxOut] = txout_dict if txout_dict else {}
        self._pythonutxo_dict: Dict[str, PythonUtxo] = {}  # outpoint --> txdetails
        self._wallet_dict: Dict[str, Wallet] = {}  # outpoint --> wallet

        self.setTextElideMode(Qt.ElideMiddle)
        self.std_model = MyStandardItemModel(self, drag_key="outpoints")
        self.proxy: QSortFilterProxyModel = MySortModel(self, sort_role=self.ROLE_SORT_ORDER)
        self.proxy.setSourceModel(self.std_model)
        self.setModel(self.proxy)

        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)

        self.update()
        self.sortByColumn(self.Columns.ADDRESS, Qt.AscendingOrder)

        signals.utxos_updated.connect(self.update)
        self.selectionModel().selectionChanged.connect(self.update_labels)

        # self.setDragEnabled(True)
        # self.setAcceptDrops(True)
        # self.viewport().setAcceptDrops(True)
        # self.setDropIndicatorShown(True)
        # self.setDragDropMode(QAbstractItemView.InternalMove)
        # self.setDefaultDropAction(Qt.MoveAction)

    def update_labels(self):
        try:
            amount = sum(self.get_selected_values())
            self.uxto_selected_label.setText(
                f"{Satoshis(amount, self.signals.get_network()).str_with_unit()} selected"
            )
        except:
            self.uxto_selected_label.setText(f"")

    def create_toolbar(self, config):
        toolbar, menu, self.uxto_selected_label, search_edit = self._create_toolbar_with_menu("")
        return toolbar

    def create_menu(self, position: QPoint) -> None:
        selected = self.selected_in_column(self.Columns.OUTPOINT)
        if not selected:
            selected = [self.current_row_in_column(self.Columns.OUTPOINT)]
        menu = QMenu()

        multi_select = len(selected) > 1
        outpoints: List[OutPoint] = [
            OutPoint.from_str(self.model().data(item, role=self.ROLE_KEY)) for item in selected
        ]
        menu = QMenu()
        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return
            item = self.item_from_index(idx)
            if not item:
                return

            if str(outpoints[0]) in self._wallet_dict:
                menu.addAction(
                    _("Open transaction"),
                    lambda: self.signals.open_tx_like.emit(outpoints[0].txid),
                )

            addr_URL = block_explorer_URL(self.config.network_config.mempool_url, "tx", outpoints[0].txid)
            if addr_URL:
                menu.addAction(_("View on block explorer"), lambda: webopen(addr_URL))

            menu.addAction(
                _("Copy txid:out"),
                lambda: self.copyKeyRoleToClipboard([idx.row()]),
            )

        menu.addAction(
            _("Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
        )

        # run_hook('receive_menu', menu, addrs, self.wallet)
        menu.exec_(self.viewport().mapToGlobal(position))

    def get_wallet_address_satoshis(
        self, outpoint: OutPoint
    ) -> Tuple[Optional[Wallet], Optional[PythonUtxo], Optional[str], Optional[Satoshis]]:
        wallet = self._wallet_dict.get(str(outpoint))
        python_utxo = self._pythonutxo_dict.get(str(outpoint))
        address = None
        satoshis = None
        if python_utxo:
            satoshis = Satoshis(python_utxo.txout.value, self.config.network_config.network)
            address = python_utxo.address
        else:
            txout = self.txout_dict.get(str(outpoint))
            if txout:
                satoshis = Satoshis(txout.value, self.config.network_config.network)
                address = bdk.Address.from_script(
                    txout.script_pubkey, self.config.network_config.network
                ).as_string()
        return wallet, python_utxo, address, satoshis

    def update(self, update_filter: UpdateFilter = None):
        if self.maybe_defer_update():
            return

        def str_format(v):
            return str(v) if v else "Unknown"

        current_key = self.get_role_data_for_current_item(col=self.key_column, role=self.ROLE_KEY)

        # build dicts to look up the outpoints later (fast)

        self._wallet_dict = {}  # outpoint_str:Wallet
        self._pythonutxo_dict = {}  # outpoint_str:PythonUTXO
        for wallet_ in get_wallets(self.signals):
            txos = wallet_.get_all_txos(include_not_mine=True)
            self._pythonutxo_dict.update({str(python_txo.outpoint): python_txo for python_txo in txos})
            self._wallet_dict.update({str(python_txo.outpoint): wallet_ for python_txo in txos})

        self.std_model.clear()
        self.update_headers(self.__class__.headers.values())
        set_idx = None
        for i, outpoint in enumerate(self.get_outpoints()):
            outpoint = OutPoint.from_bdk(outpoint)
            wallet, python_utxo, address, satoshis = self.get_wallet_address_satoshis(outpoint)

            labels = [""] * len(self.Columns)
            labels[self.Columns.OUTPOINT] = str(outpoint)
            labels[self.Columns.ADDRESS] = str_format(address)
            labels[self.Columns.AMOUNT] = str_format(satoshis)
            items = [QStandardItem(x) for x in labels]
            self.set_editability(items)
            items[self.Columns.OUTPOINT].setText(str(outpoint))
            items[self.Columns.OUTPOINT].setData(str(outpoint), self.ROLE_KEY)
            items[self.Columns.OUTPOINT].setData(str(outpoint), self.ROLE_CLIPBOARD_DATA)
            items[self.Columns.OUTPOINT].setToolTip(str(outpoint))

            items[self.Columns.ADDRESS].setData(i, self.ROLE_SORT_ORDER)
            items[self.Columns.ADDRESS].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.ADDRESS].setData(labels[self.Columns.ADDRESS], self.ROLE_CLIPBOARD_DATA)
            items[self.Columns.ADDRESS].setToolTip(labels[self.Columns.ADDRESS])
            items[self.Columns.AMOUNT].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.AMOUNT].setData(
                satoshis.value if satoshis else str_format(satoshis), self.ROLE_CLIPBOARD_DATA
            )
            items[self.Columns.PARENTS].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.OUTPOINT].setFont(QFont(MONOSPACE_FONT))

            # add item
            count = self.std_model.rowCount()
            self.std_model.insertRow(count, items)
            self.refresh_row(outpoint, count)
            idx = self.std_model.index(count, self.Columns.LABEL)
            if outpoint == current_key:
                set_idx = QPersistentModelIndex(idx)
        if set_idx:
            self.set_current_idx(set_idx)

        self.header().setSectionResizeMode(self.Columns.ADDRESS, QHeaderView.Interactive)

        # show/hide self.Columns
        self.filter()
        self.proxy.setDynamicSortFilter(True)
        for hidden_column in self.hidden_columns:
            self.hideColumn(hidden_column)

    def refresh_row(self, key: bdk.OutPoint, row):
        assert row is not None

        outpoint = OutPoint.from_bdk(key)
        wallet, python_utxo, address, satoshis = self.get_wallet_address_satoshis(outpoint)
        if not python_utxo:
            return

        txdetails = wallet.get_tx(outpoint.txid) if wallet else None
        sort_id = TxStatus.from_wallet(txdetails.txid, wallet).sort_id() if txdetails and wallet else -1

        items = [self.std_model.item(row, col) for col in self.Columns]

        items[self.Columns.STATUS].setIcon(
            read_QIcon(
                icon_of_utxo(python_utxo.is_spent_by_txid, txdetails.confirmation_time, sort_id)
                if txdetails
                else None
            )
        )
        if txdetails:
            items[self.Columns.STATUS].setToolTip(
                tooltip_text_of_utxo(python_utxo.is_spent_by_txid, txdetails.confirmation_time)
            )

        wallet_id = wallet.id if wallet and address and wallet.is_my_address(address) else ""
        items[self.Columns.WALLET_ID].setText(wallet_id)
        items[self.Columns.WALLET_ID].setData(wallet_id, self.ROLE_CLIPBOARD_DATA)
        txid = outpoint.txid

        category = wallet.labels.get_category(address) if wallet else ""

        items[self.Columns.CATEGORY].setText(category)
        items[self.Columns.CATEGORY].setData(category, self.ROLE_CLIPBOARD_DATA)
        label = wallet.get_label_for_txid(txid) or "" if wallet else ""
        items[self.Columns.LABEL].setText(label)
        items[self.Columns.LABEL].setData(label, self.ROLE_CLIPBOARD_DATA)
        color = self._default_bg_brush
        for col in items:
            col.setBackground(color)

        items[self.Columns.CATEGORY].setBackground(CategoryEditor.color(category))
        if (
            python_utxo
            and python_utxo.txout
            and wallet
            and address
            and wallet.is_my_address(python_utxo.address)
        ):
            color = (
                ColorScheme.YELLOW.as_color(background=True)
                if wallet.is_change(address)
                else ColorScheme.GREEN.as_color(background=True)
            )
            items[self.Columns.ADDRESS].setBackground(color)

    def get_selected_outpoints(self) -> List[OutPoint]:
        if not self.model():
            return []
        items = self.selected_in_column(self.Columns.OUTPOINT)
        return [OutPoint.from_str(x.data(self.ROLE_KEY)) for x in items]

    def get_selected_values(self) -> List[OutPoint]:
        if not self.model():
            return []
        items = self.selected_in_column(self.Columns.AMOUNT)
        return [x.data(self.ROLE_CLIPBOARD_DATA) for x in items]

    def on_double_click(self, idx: QModelIndex):
        outpoint = idx.sibling(idx.row(), self.Columns.OUTPOINT).data(self.ROLE_KEY)
        self.signals.show_utxo.emit(outpoint)
