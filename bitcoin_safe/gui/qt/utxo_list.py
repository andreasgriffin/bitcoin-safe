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


from __future__ import annotations

import enum
import logging
from functools import partial
from typing import Any

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.util import clean_list, time_logger
from bitcoin_safe_lib.util_os import webopen
from PyQt6.QtCore import QModelIndex, QPoint, Qt
from PyQt6.QtGui import QStandardItem
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QWidget
from typing_extensions import Self

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.tx import short_tx_id

from ...config import UserConfig
from ...i18n import translate
from ...pythonbdk_types import OutPoint, PythonUtxo, TxOut
from ...signals import UpdateFilter, UpdateFilterReason, WalletFunctions
from ...wallet import TxStatus, Wallet, get_wallets
from .my_treeview import (
    MyItemDataRole,
    MySortModel,
    MyStandardItemModel,
    MyTreeView,
    QItemSelectionModel,
    TreeViewWithToolbar,
    header_item,
    needs_frequent_flag,
)
from .util import ColorScheme, block_explorer_URL, category_color, sort_id_to_icon

logger = logging.getLogger(__name__)


def icon_of_utxo(is_spent_by_txid: str | None, chain_position: bdk.ChainPosition, sort_id: int) -> str:
    """Icon of utxo."""
    if is_spent_by_txid:
        return "bi--inputs.svg"
    return sort_id_to_icon(sort_id)


def tooltip_text_of_utxo(is_spent_by_txid: str | None, chain_position: bdk.ChainPosition) -> str:
    """Tooltip text of utxo."""
    if isinstance(chain_position, bdk.ChainPosition.UNCONFIRMED):
        if is_spent_by_txid:
            return translate(
                "utxo_list", "Unconfirmed UTXO is spent by transaction {is_spent_by_txid}"
            ).format(is_spent_by_txid=short_tx_id(is_spent_by_txid))
        else:
            return translate("utxo_list", "Unconfirmed UTXO")

    return translate("utxo_list", "Confirmed UTXO")


class UTXOList(MyTreeView[OutPoint]):
    class Columns(MyTreeView.BaseColumnsEnum):
        STATUS = enum.auto()
        WALLET_ID = enum.auto()
        OUTPOINT = enum.auto()
        ADDRESS = enum.auto()
        CATEGORY = enum.auto()
        LABEL = enum.auto()
        AMOUNT = enum.auto()
        # PARENTS = enum.auto()
        FIAT_BALANCE = enum.auto()

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
        # Columns.PARENTS: Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.FIAT_BALANCE: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    }

    column_widths: dict[MyTreeView.BaseColumnsEnum, int] = {
        Columns.STATUS: 15,
        Columns.ADDRESS: 100,
        Columns.AMOUNT: 100,
        Columns.WALLET_ID: 100,
        Columns.OUTPOINT: 100,
        Columns.FIAT_BALANCE: 110,
    }
    stretch_column = Columns.LABEL
    key_column = Columns.OUTPOINT

    @staticmethod
    def cls_kwargs(
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
    ):
        return {
            "config": config,
            "wallet_functions": wallet_functions,
            "fx": fx,
        }

    def __init__(
        self,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        fx: FX,
        outpoints: list[OutPoint] | None = None,
        txout_dict: dict[str, bdk.TxOut] | dict[str, TxOut] | None = None,
        sort_column: int | None = None,
        sort_order: Qt.SortOrder | None = None,
        hidden_columns: list[int] | None = None,
        selected_ids: list[str] | None = None,
        _scroll_position=0,
    ):
        """_summary_

        Args:
            config (UserConfig): _description_
        signals (WalletFunctions): _description_
            outpoints (List[OutPoint]): _description_
            hidden_columns (_type_, optional): _description_. Defaults to None.
            txout_dict (Dict[str, bdk.TxOut], optional): Can be used to augment
                the list with infos, if the utxo is not from the own wallet.
                Defaults to None.
        """
        super().__init__(
            config=config,
            stretch_column=self.stretch_column,
            column_widths=self.column_widths,
            editable_columns=[],
            signals=wallet_functions.signals,
            sort_column=sort_column if sort_column is not None else UTXOList.Columns.ADDRESS,
            sort_order=sort_order if sort_order is not None else Qt.SortOrder.AscendingOrder,
            hidden_columns=hidden_columns,
            selected_ids=selected_ids,
            _scroll_position=_scroll_position,
        )
        self.fx = fx
        self.outpoints = outpoints if outpoints else []
        self.wallet_functions = wallet_functions
        self.txout_dict: dict[str, bdk.TxOut] | dict[str, TxOut] = txout_dict if txout_dict else {}
        self._pythonutxo_dict: dict[str, PythonUtxo] = {}  # outpoint --> txdetails
        self._wallet_dict: dict[str, Wallet] = {}  # outpoint --> wallet
        self.current_categories_filter: set[str] | None = None

        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._source_model = MyStandardItemModel(
            key_column=self.key_column,
            parent=self,
        )
        self.proxy = MySortModel(
            Columns=self.Columns,
            drag_key="outpoints",
            key_column=self.key_column,
            parent=self,
            source_model=self._source_model,
            sort_role=MyItemDataRole.ROLE_SORT_ORDER,
        )
        self.setModel(self.proxy)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)  # Allow user to sort by clicking column headers

        self.update_content()

        # signals
        wallet_functions.signals.any_wallet_updated.connect(self.update_with_filter)
        self.fx.signal_data_updated.connect(self.on_update_fx_rates)

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def on_update_fx_rates(self):
        """On update fx rates."""
        self.update_with_filter(update_filter=UpdateFilter(outpoints=self.outpoints))

    def set_outpoints(self, outpoints: list[OutPoint]):
        """Set outpoints."""
        self.outpoints = outpoints
        self.update_content()

    def create_menu(self, position: QPoint) -> Menu:
        """Create menu."""
        menu = Menu()
        # is_multisig = isinstance(self.wallet, Multisig_Wallet)
        selected = self.selected_in_column(self.key_column)
        if not selected:
            return menu
        multi_select = len(selected) > 1

        _selected_items = [self.item_from_index(item) for item in selected]
        selected_items = [item for item in _selected_items if item]

        if not selected:
            current_row = self.current_row_in_column(self.Columns.OUTPOINT)
            if current_row:
                selected = [current_row]

        outpoints: list[OutPoint] = [item.data(role=MyItemDataRole.ROLE_KEY) for item in selected]

        if not multi_select:
            idx = self._p2s(self.indexAt(position))
            if not idx.isValid():
                return menu
            item = self.item_from_index(source_idx=idx)
            if not item:
                return menu

            if str(outpoints[0]) in self._wallet_dict:
                menu.add_action(
                    translate("utxo_list", "Open transaction"),
                    partial(self.signals.open_tx_like.emit, outpoints[0].txid_str),
                )

            txid_URL = block_explorer_URL(self.config.network_config.mempool_url, "tx", outpoints[0].txid_str)
            if txid_URL:
                menu.add_action(
                    translate("utxo_list", "View on block explorer"),
                    partial(webopen, txid_URL),
                    icon=svg_tools.get_QIcon("block-explorer.svg"),
                )

            wallet_ids: list[str] = clean_list(
                [
                    item.data(role=MyItemDataRole.ROLE_CLIPBOARD_DATA)
                    for item in self.selected_in_column(self.Columns.WALLET_ID)
                ]
            )
            addresses: list[str] = clean_list(
                [
                    item.data(role=MyItemDataRole.ROLE_CLIPBOARD_DATA)
                    for item in self.selected_in_column(self.Columns.ADDRESS)
                ]
            )
            if wallet_ids and addresses:
                menu.add_action(
                    translate("utxo_list", "Open Address Details"),
                    partial(
                        self.wallet_functions.wallet_signals[wallet_ids[0]].show_address.emit,
                        addresses[0],
                        wallet_ids[0],
                    ),
                )

            self.add_copy_menu(menu, idx, include_columns_even_if_hidden=[self.Columns.OUTPOINT])

        menu.add_action(
            translate("utxo_list", "Copy as csv"),
            partial(
                self.copyRowsToClipboardAsCSV,
                [item.data(MySortModel.role_drag_key) for item in selected_items if item],
            ),
            icon=svg_tools.get_QIcon("bi--filetype-csv.svg"),
        )

        # run_hook('receive_menu', menu, addrs, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    def get_wallet_address_satoshis(
        self, outpoint: OutPoint
    ) -> tuple[Wallet | None, PythonUtxo | None, str | None, Satoshis | None]:
        """Get wallet address satoshis."""
        wallet = self._wallet_dict.get(str(outpoint))
        python_utxo = self._pythonutxo_dict.get(str(outpoint))
        address = None
        satoshis = None
        if python_utxo:
            satoshis = Satoshis(python_utxo.value, self.config.network)
            address = python_utxo.address
        else:
            txout = self.txout_dict.get(str(outpoint))
            if txout:
                satoshis = Satoshis(txout.value.to_sat(), self.config.network)
                address = str(bdk.Address.from_script(txout.script_pubkey, self.config.network))
        return wallet, python_utxo, address, satoshis

    def get_headers(self) -> dict[MyTreeView.BaseColumnsEnum, QStandardItem]:
        """Get headers."""
        currency_symbol = self.fx.get_currency_symbol()
        return {
            self.Columns.STATUS: header_item(self.tr("Tx"), tooltip=self.tr("Transaction status")),
            self.Columns.WALLET_ID: header_item(self.tr("Wallet")),
            self.Columns.OUTPOINT: header_item(self.tr("Outpoint")),
            self.Columns.ADDRESS: header_item(self.tr("Address")),
            self.Columns.CATEGORY: header_item(self.tr("Category")),
            self.Columns.LABEL: header_item(self.tr("Label")),
            self.Columns.AMOUNT: header_item(self.tr("Amount")),
            # self.Columns.PARENTS: self.tr("Parents"),
            self.Columns.FIAT_BALANCE: header_item(currency_symbol + " " + self.tr("Value")),
        }

    @time_logger
    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        """Update with filter."""
        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if (
            should_update
            or (update_filter.categories or update_filter.addresses)
            and update_filter.reason != UpdateFilterReason.UnusedAddressesCategorySet
        ):
            should_update = True

        if should_update:
            return self.update_content()

        logger.debug(f"{self.__class__.__name__} update_with_filter")

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
                log_info.append((row, str(outpoint)[:4]))  # no sensitive info
                self.refresh_row(outpoint, row)

        logger.debug(f"Updated  {log_info}")

        self._after_update_content()

    def update_content(self):
        """Update content."""
        if self.maybe_defer_update():
            return

        def str_format(v):
            """Str format."""
            return str(v) if v else "Unknown"

        self._before_update_content()

        # build dicts to look up the outpoints later (fast)

        self._wallet_dict = {}  # outpoint_str:Wallet
        self._pythonutxo_dict = {}  # outpoint_str:PythonUTXO
        for wallet_ in get_wallets(self.wallet_functions):
            txos_dict = wallet_.get_all_txos_dict(include_not_mine=True)
            self._pythonutxo_dict.update(txos_dict)
            self._wallet_dict.update({outpoint_str: wallet_ for outpoint_str in txos_dict.keys()})

        self._source_model.clear()
        self.update_headers(self.get_headers())
        for i, outpoint in enumerate(self.outpoints):
            outpoint = OutPoint.from_bdk(outpoint)
            wallet, python_utxo, address, satoshis = self.get_wallet_address_satoshis(outpoint)

            labels = [""] * len(self.Columns)
            labels[self.Columns.OUTPOINT] = str(outpoint)
            labels[self.Columns.ADDRESS] = str_format(address)
            labels[self.Columns.AMOUNT] = str_format(satoshis)
            items = [QStandardItem(x) for x in labels]
            self.set_editability(items)
            items[self.Columns.OUTPOINT].setText(str(outpoint))
            items[self.Columns.OUTPOINT].setData(i, MyItemDataRole.ROLE_SORT_ORDER)
            items[self.Columns.OUTPOINT].setData(outpoint, MyItemDataRole.ROLE_KEY)
            items[self.Columns.OUTPOINT].setData(str(outpoint), MyItemDataRole.ROLE_CLIPBOARD_DATA)
            items[self.Columns.OUTPOINT].setToolTip(str(outpoint))

            # items[self.Columns.ADDRESS].setFont(QFont(MONOSPACE_FONT))
            items[self.Columns.ADDRESS].setData(
                labels[self.Columns.ADDRESS], MyItemDataRole.ROLE_CLIPBOARD_DATA
            )
            items[self.Columns.ADDRESS].setData(i, MyItemDataRole.ROLE_SORT_ORDER)
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

        self.update_base_hidden_rows()
        self._after_update_content()
        super().update_content()

    def refresh_row(self, key: bdk.OutPoint, row: int):
        """Refresh row."""
        assert row is not None

        outpoint = OutPoint.from_bdk(key)
        wallet, python_utxo, address, satoshis = self.get_wallet_address_satoshis(outpoint)

        txdetails = wallet.get_tx(outpoint.txid_str) if wallet else None
        status = TxStatus.from_wallet(txdetails.txid, wallet) if txdetails and wallet else None
        sort_id = status.sort_id() if status else -1

        _items = [self._source_model.item(row, col) for col in self.Columns]
        items = [entry for entry in _items if entry]

        # unconfirmed txos might be confirmed, and need to be updated more often
        items[self.key_column].setData(
            needs_frequent_flag(status=status), role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG
        )
        if python_utxo:
            items[self.Columns.STATUS].setData(str(sort_id), role=MyItemDataRole.ROLE_SORT_ORDER)
            items[self.Columns.STATUS].setIcon(
                svg_tools.get_QIcon(
                    icon_of_utxo(python_utxo.is_spent_by_txid, txdetails.chain_position, sort_id)
                    if txdetails
                    else None
                )
            )
            if txdetails:
                items[self.Columns.STATUS].setToolTip(
                    tooltip_text_of_utxo(python_utxo.is_spent_by_txid, txdetails.chain_position)
                )

            wallet_id = wallet.id if wallet and address and wallet.is_my_address(address) else ""
            items[self.Columns.WALLET_ID].setText(wallet_id)
            items[self.Columns.WALLET_ID].setData(wallet_id, MyItemDataRole.ROLE_CLIPBOARD_DATA)
            txid = outpoint.txid_str

            category = wallet.labels.get_category(address) if wallet and address else ""

            items[self.Columns.CATEGORY].setText(category if category else "")
            items[self.Columns.CATEGORY].setData(category, MyItemDataRole.ROLE_CLIPBOARD_DATA)
            label = wallet.get_label_for_txid(txid) or "" if wallet else ""
            items[self.Columns.LABEL].setText(label)
            items[self.Columns.LABEL].setData(label, MyItemDataRole.ROLE_CLIPBOARD_DATA)
            color = self._default_bg_brush
            for col in items:
                col.setBackground(color)

            if category:
                items[self.Columns.CATEGORY].setBackground(category_color(category))

            if python_utxo.txout and wallet and address and wallet.is_my_address(python_utxo.address):
                color = (
                    ColorScheme.YELLOW.as_color(background=True)
                    if wallet.is_change(address)
                    else ColorScheme.GREEN.as_color(background=True)
                )
                items[self.Columns.ADDRESS].setBackground(color)

        balance = satoshis.value if satoshis else (python_utxo.value if python_utxo else None)
        if balance is not None:
            fiat_value = self.fx.btc_to_fiat(balance)
            fiat_balance_str = (
                self.fx.fiat_to_str(fiat_value, use_currency_symbol=False) if fiat_value is not None else ""
            )
            items[self.Columns.FIAT_BALANCE].setText(fiat_balance_str)
            items[self.Columns.FIAT_BALANCE].setData(fiat_value, MyItemDataRole.ROLE_CLIPBOARD_DATA)
            items[self.Columns.FIAT_BALANCE].setData(fiat_value, MyItemDataRole.ROLE_SORT_ORDER)

    def get_selected_outpoints(self) -> list[OutPoint]:
        """Get selected outpoints."""
        items = self.selected_in_column(self.Columns.OUTPOINT)
        return [x.data(MyItemDataRole.ROLE_KEY) for x in items]

    def get_selected_values(self) -> list[int]:
        """Get selected values."""
        items = self.selected_in_column(self.Columns.AMOUNT)
        return [x.data(MyItemDataRole.ROLE_CLIPBOARD_DATA) for x in items]

    def on_double_click(self, source_idx: QModelIndex):
        """On double click."""
        outpoint = source_idx.sibling(source_idx.row(), self.Columns.OUTPOINT).data(MyItemDataRole.ROLE_KEY)
        wallets = get_wallets(self.wallet_functions)
        for wallet in wallets:
            python_utxo = wallet.get_python_txo(str(outpoint))
            if python_utxo:
                self.wallet_functions.wallet_signals[wallet.id].show_utxo.emit(outpoint)

    def set_filter_categories(self, categories: set[str] | None) -> None:
        """Set filter categories."""
        if categories == self.current_categories_filter:
            return
        self.current_categories_filter = categories
        self.update_base_hidden_rows()
        self.filter()

    def update_base_hidden_rows(self):
        """Update base hidden rows."""
        self.base_hidden_rows.clear()

        hidden_rows_category = set()

        model = self._source_model
        for row in range(model.rowCount()):
            category = model.data(model.index(row, self.Columns.CATEGORY))

            if self.current_categories_filter is not None and category not in self.current_categories_filter:
                hidden_rows_category.add(row)

        self.base_hidden_rows.update(hidden_rows_category)


class UtxoListWithToolbar(TreeViewWithToolbar):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        UTXOList.__name__: UTXOList,
    }

    @staticmethod
    def cls_kwargs(
        config: UserConfig,
    ):
        return {
            "config": config,
        }

    def __init__(self, utxo_list: UTXOList, config: UserConfig, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(utxo_list, config, parent=parent)
        self.default_export_csv_filename = "utxo_export.csv"
        self.utxo_list = utxo_list
        selection_model = self.utxo_list.selectionModel()
        if not selection_model:
            selection_model = QItemSelectionModel(self.utxo_list.model())
            self.utxo_list.setSelectionModel(selection_model)
        self.utxo_list.signal_selection_changed.connect(self.update_labels)
        self.create_layout()
        self.utxo_list.signals.language_switch.connect(self.updateUi)
        self.utxo_list.signals.any_wallet_updated.connect(self.update_with_filter)
        self.balance_label.setHidden(False)

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["utxo_list"] = self.utxo_list
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> Self:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        """Update with filter."""
        self.updateUi()

    def updateUi(self):
        """UpdateUi."""
        super().updateUi()

        self.update_labels()

    def update_labels(self):
        """Update labels."""
        try:
            selected_values = self.utxo_list.get_selected_values()
            amount = sum(selected_values)
            self.balance_label.setText(
                self.tr("{amount} selected ({number} UTXOs)").format(
                    amount=Satoshis(amount, network=self.config.network).str_with_unit(
                        btc_symbol=self.config.bitcoin_symbol.value
                    ),
                    number=len(selected_values),
                )
            )
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            self.balance_label.setText("")
