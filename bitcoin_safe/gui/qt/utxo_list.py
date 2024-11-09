#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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


# Original Version from:
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

from bitcoin_safe.gui.qt.wrappers import Menu

from ...config import UserConfig
from ...pythonbdk_types import OutPoint, PythonUtxo, TxOut

logger = logging.getLogger(__name__)


import enum
from typing import Dict, List, Optional, Tuple, Union

import bdkpython as bdk
from PyQt6.QtCore import QModelIndex, QPoint, Qt
from PyQt6.QtGui import QStandardItem
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QWidget

from ...i18n import translate
from ...signals import Signals, UpdateFilter, UpdateFilterReason
from ...util import Satoshis, block_explorer_URL, clean_list, time_logger
from ...wallet import TxStatus, Wallet, get_wallets
from .category_list import CategoryEditor
from .my_treeview import (
    MyItemDataRole,
    MySortModel,
    MyStandardItemModel,
    MyTreeView,
    QItemSelectionModel,
    TreeViewWithToolbar,
    needs_frequent_flag,
)
from .util import ColorScheme, read_QIcon, sort_id_to_icon, webopen


def icon_of_utxo(is_spent_by_txid: Optional[str], confirmation_time: bdk.BlockTime, sort_id: int) -> str:
    if not confirmation_time and is_spent_by_txid:
        return "unconfirmed_child.svg"
    return sort_id_to_icon(sort_id)


def tooltip_text_of_utxo(is_spent_by_txid: Optional[str], confirmation_time: bdk.BlockTime) -> str:
    if not confirmation_time:
        if is_spent_by_txid:
            return translate(
                "utxo_list", "Unconfirmed UTXO is spent by transaction {is_spent_by_txid}"
            ).format(is_spent_by_txid=is_spent_by_txid)
        else:
            return translate("utxo_list", "Unconfirmed UTXO")

    return translate("utxo_list", f"Confirmed UTXO")


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

    filter_columns = [
        Columns.WALLET_ID,
        Columns.OUTPOINT,
        Columns.ADDRESS,
        Columns.CATEGORY,
        Columns.LABEL,
        Columns.AMOUNT,
    ]
    column_alignments = {
        Columns.STATUS: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.WALLET_ID: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.OUTPOINT: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.ADDRESS: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.CATEGORY: Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.LABEL: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.AMOUNT: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        Columns.PARENTS: Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
    }

    column_widths: Dict[MyTreeView.BaseColumnsEnum, int] = {
        Columns.STATUS: 15,
        Columns.ADDRESS: 100,
        Columns.AMOUNT: 100,
    }
    stretch_column = Columns.LABEL
    key_column = Columns.OUTPOINT

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        get_outpoints,
        hidden_columns: List[int] | None = None,
        txout_dict: Union[Dict[str, bdk.TxOut], Dict[str, TxOut]] | None = None,
        keep_outpoint_order=False,
        sort_column: int | None = None,
        sort_order: Qt.SortOrder | None = None,
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
            signals=signals,
            sort_column=sort_column if sort_column is not None else UTXOList.Columns.ADDRESS,
            sort_order=sort_order if sort_order is not None else Qt.SortOrder.AscendingOrder,
        )
        self.config: UserConfig = config
        self.keep_outpoint_order = keep_outpoint_order
        self.hidden_columns = hidden_columns if hidden_columns else []
        self.signals = signals
        self.get_outpoints = get_outpoints
        self.txout_dict: Union[Dict[str, bdk.TxOut], Dict[str, TxOut]] = txout_dict if txout_dict else {}
        self._pythonutxo_dict: Dict[str, PythonUtxo] = {}  # outpoint --> txdetails
        self._wallet_dict: Dict[str, Wallet] = {}  # outpoint --> wallet

        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._source_model = MyStandardItemModel(self, drag_key="outpoints")
        self.proxy = MySortModel(
            self, source_model=self._source_model, sort_role=MyItemDataRole.ROLE_SORT_ORDER
        )
        self.setModel(self.proxy)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)  # Allow user to sort by clicking column headers

        self.update_content()

        # signals
        signals.any_wallet_updated.connect(self.update_with_filter)
        self.signals.language_switch.connect(self.updateUi)

        # self.setDragEnabled(True)
        # self.setAcceptDrops(True)
        # self.viewport().setAcceptDrops(True)
        # self.setDropIndicatorShown(True)
        # self.setDragDropMode(QAbstractItemView.InternalMove)
        # self.setDefaultDropAction(Qt.MoveAction)

    def create_menu(self, position: QPoint) -> Menu:
        selected: List[QModelIndex] = self.selected_in_column(self.Columns.OUTPOINT)
        if not selected:
            current_row = self.current_row_in_column(self.Columns.OUTPOINT)
            if current_row:
                selected = [current_row]

        menu = Menu()

        multi_select = len(selected) > 1
        outpoints: List[OutPoint] = [
            self.model().data(item, role=MyItemDataRole.ROLE_KEY) for item in selected
        ]

        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return menu
            item = self.item_from_index(idx)
            if not item:
                return menu

            if str(outpoints[0]) in self._wallet_dict:
                menu.add_action(
                    translate("utxo_list", "Open transaction"),
                    lambda: self.signals.open_tx_like.emit(outpoints[0].txid),
                )

            txid_URL = block_explorer_URL(self.config.network_config.mempool_url, "tx", outpoints[0].txid)
            if txid_URL:
                menu.add_action(
                    translate("utxo_list", "View on block explorer"),
                    lambda: webopen(txid_URL),
                    icon=read_QIcon("link.svg"),
                )

            wallet_ids: List[str] = clean_list(
                [
                    self.model().data(item, role=MyItemDataRole.ROLE_CLIPBOARD_DATA)
                    for item in self.selected_in_column(self.Columns.WALLET_ID)
                ]
            )
            addresses: List[str] = clean_list(
                [
                    self.model().data(item, role=MyItemDataRole.ROLE_CLIPBOARD_DATA)
                    for item in self.selected_in_column(self.Columns.ADDRESS)
                ]
            )
            if wallet_ids and addresses:
                menu.add_action(
                    translate("utxo_list", "Open Address Details"),
                    lambda: self.signals.wallet_signals[wallet_ids[0]].show_address.emit(
                        addresses[0], wallet_ids[0]
                    ),
                )

            self.add_copy_menu(menu, idx, include_columns_even_if_hidden=[self.Columns.OUTPOINT])

        menu.add_action(
            translate("utxo_list", "Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
            icon=read_QIcon("csv-file.svg"),
        )

        # run_hook('receive_menu', menu, addrs, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    def get_wallet_address_satoshis(
        self, outpoint: OutPoint
    ) -> Tuple[Optional[Wallet], Optional[PythonUtxo], Optional[str], Optional[Satoshis]]:
        wallet = self._wallet_dict.get(str(outpoint))
        python_utxo = self._pythonutxo_dict.get(str(outpoint))
        address = None
        satoshis = None
        if python_utxo:
            satoshis = Satoshis(python_utxo.txout.value, self.config.network)
            address = python_utxo.address
        else:
            txout = self.txout_dict.get(str(outpoint))
            if txout:
                satoshis = Satoshis(txout.value, self.config.network)
                address = bdk.Address.from_script(txout.script_pubkey, self.config.network).as_string()
        return wallet, python_utxo, address, satoshis

    def get_headers(self):
        return {
            self.Columns.STATUS: (""),
            self.Columns.WALLET_ID: self.tr("Wallet"),
            self.Columns.OUTPOINT: self.tr("Outpoint"),
            self.Columns.ADDRESS: self.tr("Address"),
            self.Columns.CATEGORY: self.tr("Category"),
            self.Columns.LABEL: self.tr("Label"),
            self.Columns.AMOUNT: self.tr("Amount"),
            self.Columns.PARENTS: self.tr("Parents"),
        }

    @time_logger
    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.categories or update_filter.addresses:
            should_update = True

        if should_update:
            return self.update_content()

        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")

        self._before_update_content()

        log_info = []
        model = self._source_model
        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            outpoint: OutPoint = model.data(model.index(row, self.key_column))

            if (
                update_filter.reason == UpdateFilterReason.ChainHeightAdvanced
                and model.data(
                    model.index(row, self.key_column), role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG
                )
            ) or any([outpoint in update_filter.outpoints]):
                log_info.append((row, str(outpoint)))
                self.refresh_row(outpoint, row)

        logger.debug(f"Updated  {log_info}")

        self._after_update_content()

    def update_content(self):
        if self.maybe_defer_update():
            return

        def str_format(v):
            return str(v) if v else "Unknown"

        self._before_update_content()

        current_key = self.get_role_data_for_current_item(col=self.key_column, role=MyItemDataRole.ROLE_KEY)

        # build dicts to look up the outpoints later (fast)

        self._wallet_dict = {}  # outpoint_str:Wallet
        self._pythonutxo_dict = {}  # outpoint_str:PythonUTXO
        for wallet_ in get_wallets(self.signals):
            txos_dict = wallet_.get_all_txos_dict(include_not_mine=True)
            self._pythonutxo_dict.update(txos_dict)
            self._wallet_dict.update({outpoint_str: wallet_ for outpoint_str in txos_dict.keys()})

        self._source_model.clear()
        self.update_headers(self.get_headers())
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
            items[self.Columns.OUTPOINT].setData(outpoint, MyItemDataRole.ROLE_KEY)
            items[self.Columns.OUTPOINT].setData(str(outpoint), MyItemDataRole.ROLE_CLIPBOARD_DATA)
            items[self.Columns.OUTPOINT].setToolTip(str(outpoint))

            items[self.Columns.ADDRESS].setData(i, MyItemDataRole.ROLE_SORT_ORDER)
            # items[self.Columns.ADDRESS].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.ADDRESS].setData(
                labels[self.Columns.ADDRESS], MyItemDataRole.ROLE_CLIPBOARD_DATA
            )
            items[self.Columns.ADDRESS].setToolTip(labels[self.Columns.ADDRESS])
            # items[self.Columns.AMOUNT].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.AMOUNT].setData(
                satoshis.value if satoshis else str_format(satoshis), MyItemDataRole.ROLE_CLIPBOARD_DATA
            )

            # add item
            count = self._source_model.rowCount()
            self._source_model.insertRow(count, items)
            self.refresh_row(outpoint, count)

        if isinstance(header := self.header(), QHeaderView):
            header.setSectionResizeMode(self.Columns.ADDRESS, QHeaderView.ResizeMode.Interactive)

        self._after_update_content()
        super().update_content()

    def refresh_row(self, key: bdk.OutPoint, row: int):
        assert row is not None

        outpoint = OutPoint.from_bdk(key)
        wallet, python_utxo, address, satoshis = self.get_wallet_address_satoshis(outpoint)
        if not python_utxo:
            return

        txdetails = wallet.get_tx(outpoint.txid) if wallet else None
        status = TxStatus.from_wallet(txdetails.txid, wallet) if txdetails and wallet else None
        sort_id = status.sort_id() if status else -1

        _items = [self._source_model.item(row, col) for col in self.Columns]
        items = [entry for entry in _items if entry]

        if needs_frequent_flag(status=status):
            # unconfirmed txos might be confirmed, and need to be updated more often
            items[self.key_column].setData(True, role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG)
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
        items[self.Columns.WALLET_ID].setData(wallet_id, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        txid = outpoint.txid

        category = wallet.labels.get_category(address) if wallet and address else ""

        items[self.Columns.CATEGORY].setText(category if category else "")
        items[self.Columns.CATEGORY].setData(category, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        label = wallet.get_label_for_txid(txid) or "" if wallet else ""
        items[self.Columns.LABEL].setText(label)
        items[self.Columns.LABEL].setData(label, MyItemDataRole.ROLE_CLIPBOARD_DATA)
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
        return [x.data(MyItemDataRole.ROLE_KEY) for x in items]

    def get_selected_values(self) -> List[int]:
        if not self.model():
            return []
        items = self.selected_in_column(self.Columns.AMOUNT)
        return [x.data(MyItemDataRole.ROLE_CLIPBOARD_DATA) for x in items]

    def on_double_click(self, idx: QModelIndex):
        outpoint = idx.sibling(idx.row(), self.Columns.OUTPOINT).data(MyItemDataRole.ROLE_KEY)
        wallets = get_wallets(self.signals)
        for wallet in wallets:
            python_utxo = wallet.get_python_txo(str(outpoint))
            if python_utxo:
                self.signals.wallet_signals[wallet.id].show_utxo.emit(outpoint)


class UtxoListWithToolbar(TreeViewWithToolbar):
    def __init__(self, utxo_list: UTXOList, config: UserConfig, parent: QWidget | None = None) -> None:
        super().__init__(utxo_list, config, parent=parent)
        self.utxo_list = utxo_list
        selection_model = self.utxo_list.selectionModel()
        if not selection_model:
            selection_model = QItemSelectionModel(self.utxo_list.model())
            self.utxo_list.setSelectionModel(selection_model)
        self.utxo_list.signal_selection_changed.connect(self.update_labels)
        self.create_layout()
        self.utxo_list.signals.language_switch.connect(self.updateUi)
        self.utxo_list.signals.any_wallet_updated.connect(self.updateUi)

    def updateUi(self):
        super().updateUi()

        self.update_labels()

    def update_labels(self):
        try:
            selected_values = self.utxo_list.get_selected_values()
            amount = sum(selected_values)
            self.uxto_selected_label.setText(
                self.tr("{amount} selected ({number} UTXOs)").format(
                    amount=Satoshis(amount, self.utxo_list.signals.get_network()).str_with_unit(),
                    number=len(selected_values),
                )
            )
        except:
            self.uxto_selected_label.setText(f"")

    def create_toolbar_with_menu(self, title):
        super().create_toolbar_with_menu(title=title)
        self.uxto_selected_label = self.balance_label
