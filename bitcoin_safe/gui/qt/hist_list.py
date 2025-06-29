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

import enum
import logging
import os
import tempfile
from enum import IntEnum
from functools import partial
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.util import confirmation_wait_formatted
from bitcoin_safe_lib.util import time_logger
from PyQt6.QtCore import QMimeData, QModelIndex, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QStandardItem,
)
from PyQt6.QtWidgets import QAbstractItemView, QFileDialog, QPushButton, QWidget

from bitcoin_safe.config import MIN_RELAY_FEE, UserConfig
from bitcoin_safe.execute_config import GENERAL_RBF_AVAILABLE
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.tx_tools import TxTools
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.mempool import MempoolData
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import Balance, Recipient, TransactionDetails
from bitcoin_safe.tx import short_tx_id
from bitcoin_safe.typestubs import TypedPyQtSignal
from bitcoin_safe.util_os import webopen

from ...i18n import translate
from ...signals import Signals, UpdateFilter, UpdateFilterReason
from ...wallet import ToolsTxUiInfo, TxStatus, Wallet, get_wallets
from .category_list import CategoryEditor
from .my_treeview import (
    MyItemDataRole,
    MySortModel,
    MyStandardItemModel,
    MyTreeView,
    TreeViewWithToolbar,
    needs_frequent_flag,
)
from .taglist import AddressDragInfo
from .util import Message, MessageType, block_explorer_URL, sort_id_to_icon

logger = logging.getLogger(__name__)


class AddressUsageStateFilter(IntEnum):
    ALL = 0
    UNUSED = 1
    FUNDED = 2
    USED_AND_EMPTY = 3
    FUNDED_OR_UNUSED = 4

    def ui_text(self) -> str:
        return {
            self.ALL: translate("hist_list", "All status"),
            self.UNUSED: translate("hist_list", "Unused"),
            self.FUNDED: translate("hist_list", "Funded"),
            self.USED_AND_EMPTY: translate("hist_list", "Used"),
            self.FUNDED_OR_UNUSED: translate("hist_list", "Funded or Unused"),
        }[self]


class AddressTypeFilter(IntEnum):
    ALL = 0
    RECEIVING = 1
    CHANGE = 2

    def ui_text(self) -> str:
        return {
            self.ALL: translate("hist_list", "All types"),
            self.RECEIVING: translate("hist_list", "Receiving"),
            self.CHANGE: translate("hist_list", "Change"),
        }[self]


class HistList(MyTreeView):
    signal_tag_dropped: TypedPyQtSignal[AddressDragInfo] = pyqtSignal(AddressDragInfo)  # type: ignore

    show_change: AddressTypeFilter
    show_used: AddressUsageStateFilter

    class Columns(MyTreeView.BaseColumnsEnum):
        TXID = enum.auto()
        WALLET_ID = enum.auto()
        STATUS = enum.auto()
        CATEGORIES = enum.auto()
        LABEL = enum.auto()
        AMOUNT = enum.auto()
        BALANCE = enum.auto()

    filter_columns = [
        Columns.WALLET_ID,
        Columns.STATUS,
        Columns.CATEGORIES,
        Columns.LABEL,
        Columns.AMOUNT,
        Columns.TXID,
    ]

    column_alignments = {
        Columns.WALLET_ID: Qt.AlignmentFlag.AlignCenter,
        Columns.STATUS: Qt.AlignmentFlag.AlignCenter,
        Columns.CATEGORIES: Qt.AlignmentFlag.AlignCenter,
        Columns.LABEL: Qt.AlignmentFlag.AlignVCenter,
        Columns.AMOUNT: Qt.AlignmentFlag.AlignRight,
        Columns.BALANCE: Qt.AlignmentFlag.AlignRight,
    }

    column_widths: Dict[MyTreeView.BaseColumnsEnum, int] = {Columns.TXID: 100, Columns.WALLET_ID: 100}

    def __init__(
        self,
        fx: FX,
        config: UserConfig,
        signals: Signals,
        mempool_data: MempoolData,
        wallets: List[Wallet],
        hidden_columns: List[int] | None = None,
        address_domain: List[str] | None = None,
    ) -> None:
        super().__init__(
            config=config,
            stretch_column=HistList.Columns.LABEL,
            editable_columns=[HistList.Columns.LABEL],
            column_widths=self.column_widths,
            signals=signals,
            sort_column=HistList.Columns.STATUS,
            sort_order=Qt.SortOrder.DescendingOrder,
            hidden_columns=hidden_columns,
        )
        self.fx = fx
        self.mempool_data = mempool_data
        self.address_domain = address_domain
        self.signals = signals
        self.wallets = wallets
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        self.balance = 0
        # self.change_button = QComboBox(self)
        # self.change_button.currentIndexChanged.connect(self.toggle_change)
        # for (
        #     addr_type
        # ) in AddressTypeFilter.__members__.values():  # type: AddressTypeFilter
        #     self.change_button.addItem(addr_type.ui_text())
        # self.used_button = QComboBox(self)
        # self.used_button.currentIndexChanged.connect(self.toggle_used)
        # for (
        #     addr_usage_state
        # ) in (
        #     AddressUsageStateFilter.__members__.values()
        # ):  # type: AddressUsageStateFilter
        #     self.used_button.addItem(addr_usage_state.ui_text())
        self._source_model = MyStandardItemModel(
            key_column=self.key_column,
            parent=self,
        )
        self.proxy = MySortModel(
            drag_key="txids",
            Columns=self.Columns,
            key_column=self.key_column,
            parent=self,
            source_model=self._source_model,
            sort_role=MyItemDataRole.ROLE_SORT_ORDER,
            custom_drag_keys_to_file_paths=self.drag_keys_to_file_paths,
        )
        self.setModel(self.proxy)
        self.update_content()
        for wallet in self.wallets:
            self.signals.wallet_signals[wallet.id].updated.connect(self.update_with_filter)
        self.signals.language_switch.connect(self.update)

    def get_file_data(self, txid: str) -> Optional[Data]:
        for wallet in get_wallets(self.signals):
            txdetails = wallet.get_tx(txid)
            if txdetails:
                return Data.from_tx(txdetails.transaction, network=wallet.network)
        return None

    def drag_keys_to_file_paths(
        self, drag_keys: Iterable[str], save_directory: Optional[str] = None
    ) -> List[str]:
        file_urls = []

        # Iterate through indexes to fetch serialized data using drag keys
        for key in drag_keys:
            # Fetch the serialized data using the drag_key
            data = self.get_file_data(key)
            if not data:
                continue

            if save_directory:
                file_path = os.path.join(save_directory, f"{key}.tx")
                file_descriptor = os.open(file_path, os.O_CREAT | os.O_WRONLY)
            else:
                # Create a temporary file
                file_descriptor, file_path = tempfile.mkstemp(
                    suffix=f".tx",
                    prefix=f"{key} ",
                )

            data.write_to_filedescriptor(file_descriptor)

            # Add the file URL to the list
            file_urls.append(file_path)

        return file_urls

    def _acceptable_mime_data(self, mime_data: QMimeData) -> bool:
        if mime_data and self.get_json_mime_data(mime_data) is not None:
            return True
        if mime_data and mime_data.hasUrls():
            return True
        return False

    def dragEnterEvent(self, e: QDragEnterEvent | None) -> None:
        super().dragEnterEvent(e)
        if not e or e.isAccepted():
            return

        mime_data = e.mimeData()
        if mime_data and self._acceptable_mime_data(mime_data):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent | None) -> None:
        super().dragMoveEvent(event)
        if not event or event.isAccepted():
            return

        mime_data = event.mimeData()
        if mime_data and self._acceptable_mime_data(mime_data):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, e: QDropEvent | None) -> None:
        # handle dropped files
        super().dropEvent(e)
        if not e or e.isAccepted():
            return

        index = self.indexAt(e.position().toPoint())
        if not index.isValid():
            # Handle the case where the drop is not on a valid index
            return

        mime_data = e.mimeData()
        if mime_data:
            json_mime_data = self.get_json_mime_data(mime_data)
            if json_mime_data is not None:
                model = self.model()
                hit_address = model.data(model.index(index.row(), self.key_column))
                if json_mime_data.get("type") == "drag_tag":
                    if hit_address is not None:
                        drag_info = AddressDragInfo([json_mime_data.get("tag")], [hit_address])
                        # logger.debug(f"drag_info {drag_info}")
                        self.signal_tag_dropped.emit(drag_info)
                    e.accept()
                    return

            elif mime_data.hasUrls():
                # Iterate through the list of dropped file URLs
                for url in mime_data.urls():
                    # Convert URL to local file path
                    self.signals.open_file_path.emit(url.toLocalFile())

        e.ignore()

    def on_double_click(self, idx: QModelIndex) -> None:
        txid = self.get_role_data_for_current_item(col=self.key_column, role=MyItemDataRole.ROLE_KEY)
        wallet = self.get_wallet(txid=txid)
        if not wallet:
            return
        tx_details = wallet.get_tx(txid=txid)
        if not tx_details:
            return
        self.signals.open_tx_like.emit(tx_details)

    def toggle_change(self, state: int) -> None:
        if state == self.show_change:
            return
        self.show_change = AddressTypeFilter(state)
        self.update_content()

    def toggle_used(self, state: int) -> None:
        if state == self.show_used:
            return
        self.show_used = AddressUsageStateFilter(state)
        self.update_content()

    @time_logger
    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        if update_filter.refresh_all:
            return self.update_content()
        logger.debug(f"{self.__class__.__name__} update_with_filter")

        def categories_intersect(model: MyStandardItemModel, row) -> Set:
            return set(model.data(model.index(row, self.Columns.CATEGORIES))).intersection(
                set(update_filter.categories)
            )

        def tx_involves_address(txid) -> Set[str]:
            wallet = self.get_wallet(txid=txid)
            if not wallet:
                return set()
            fulltxdetail = wallet.get_dict_fulltxdetail().get(txid)
            if not fulltxdetail:
                return set()
            return update_filter.addresses.intersection(fulltxdetail.involved_addresses())

        logger.debug(f"{self.__class__.__name__}  update_with_filter")
        self._before_update_content()

        log_info = []
        model = self._source_model
        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            txid = model.data(model.index(row, self.Columns.TXID))

            if (
                update_filter.reason == UpdateFilterReason.ChainHeightAdvanced
                and model.data(
                    model.index(row, self.key_column), role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG
                )
            ) or any(
                [txid in update_filter.txids, categories_intersect(model, row), tx_involves_address(txid)]
            ):
                log_info.append((row, str(txid)[:4]))  # no sensitive info in log
                self.refresh_row(txid, row)

        logger.debug(f"Updated  {log_info}")

        self._after_update_content()

    def get_headers(self) -> Dict["HistList.Columns", str]:
        return {
            self.Columns.WALLET_ID: self.tr("Wallet"),
            self.Columns.STATUS: self.tr("Status"),
            self.Columns.CATEGORIES: self.tr("Category"),
            self.Columns.LABEL: self.tr("Label"),
            self.Columns.AMOUNT: self.tr("Amount"),
            self.Columns.BALANCE: self.tr("Balance"),
            self.Columns.TXID: self.tr("Txid"),
        }

    def _init_row(
        self, wallet: Wallet, tx: TransactionDetails, status_sort_index: int, old_balance: int
    ) -> Tuple[List[QStandardItem], int]:
        """

        Returns:
            Tuple[List[QStandardItem] , int]: items, amount
        """

        # WALLET_ID = enum.auto()
        # AMOUNT = enum.auto()
        # BALANCE = enum.auto()
        # TXID = enum.auto()

        # calculate the amount
        if self.address_domain:
            fulltxdetail = wallet.get_dict_fulltxdetail().get(tx.txid)
            assert fulltxdetail, f"Could not find the transaction for {tx.txid}"
            amount = fulltxdetail.sum_outputs(self.address_domain) - fulltxdetail.sum_inputs(
                self.address_domain
            )
        else:
            amount = int(tx.received - tx.sent)

        new_balance = old_balance + amount

        labels = [""] * len(self.Columns)
        labels[self.Columns.WALLET_ID] = wallet.id
        labels[self.Columns.AMOUNT] = Satoshis(amount, wallet.network).str_as_change()

        labels[self.Columns.BALANCE] = str(Satoshis(new_balance, wallet.network))
        labels[self.Columns.TXID] = tx.txid
        items = [QStandardItem(e) for e in labels]

        items[self.Columns.STATUS].setData(status_sort_index, MyItemDataRole.ROLE_SORT_ORDER)
        items[self.Columns.WALLET_ID].setData(wallet.id, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        items[self.Columns.AMOUNT].setData(amount, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        if amount < 0:
            items[self.Columns.AMOUNT].setData(QBrush(QColor("red")), Qt.ItemDataRole.ForegroundRole)
        items[self.Columns.BALANCE].setData(new_balance, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        items[self.Columns.TXID].setData(tx.txid, MyItemDataRole.ROLE_CLIPBOARD_DATA)

        # align text and set fonts
        # for i, item in enumerate(items):
        #     item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter)
        #     if i in (self.Columns.TXID,):
        #         item.setFont(QFont(MONOSPACE_FONT))

        self.set_editability(items)

        items[self.key_column].setData(tx.txid, MyItemDataRole.ROLE_KEY)

        return items, amount

    def update_content(self) -> None:
        if self.maybe_defer_update():
            return

        self._before_update_content()

        self._source_model.clear()
        self.update_headers(self.get_headers())

        num_shown = 0
        self.balance = 0
        for wallet in self.wallets:

            txid_domain: Optional[Set[str]] = None
            if self.address_domain:
                txid_domain = set()
                for address in self.address_domain:
                    txid_domain = txid_domain.union(wallet.get_involved_txids(address))

            # always take sorted_delta_list_transactions().new as a start because it is correctly sorted
            for i, tx in enumerate(wallet.sorted_delta_list_transactions()):
                if txid_domain is not None:
                    if tx.txid not in txid_domain:
                        continue

                items, amount = self._init_row(wallet, tx, i, self.balance)
                self.balance += amount

                num_shown += 1
                # add item
                count = self._source_model.rowCount()
                self._source_model.insertRow(count, items)
                self.refresh_row(tx.txid, count)

        super().update_content()
        self._after_update_content()

    def refresh_row(self, key: str, row: int) -> None:
        assert row is not None
        wallet = self.get_wallet(txid=key)
        if not wallet:
            return
        if not (tx := wallet.get_tx(txid=key)):
            return
        # STATUS = enum.auto()
        # CATEGORIES = enum.auto()
        # LABEL = enum.auto()

        label = wallet.get_label_for_txid(tx.txid)
        categories = wallet.get_categories_for_txid(tx.txid)
        categories_without_default = set(categories) - set([wallet.labels.get_default_category()])
        category = (
            list(categories_without_default)[0]
            if categories_without_default
            else (categories[0] if categories else "")
        )
        status = TxStatus.from_wallet(tx.txid, wallet)

        fee_info = FeeInfo.from_txdetails(tx)
        fee_rate = fee_info.fee_rate() if fee_info else MIN_RELAY_FEE
        status_text = ""
        if tx.chain_position.is_confirmed():
            status_text = tx.get_datetime().strftime("%Y-%m-%d %H:%M")
        else:
            if status.is_in_mempool:
                status_text = confirmation_wait_formatted(
                    self.mempool_data.fee_rate_to_projected_block_index(fee_rate)
                )
            else:
                status_text = self.tr("Local")

        if 1 <= status.confirmations() <= 6:
            status_tooltip = self.tr("{number} Confirmations").format(number=status.confirmations())
        elif status.confirmations() <= 0:
            if status.is_in_mempool:
                status_tooltip = self.tr("Waiting to be included in a block")
            else:
                status_tooltip = self.tr("Not broadcasted.")
        else:
            status_tooltip = status_text

        _item = [self._source_model.item(row, col) for col in self.Columns]
        item = [entry for entry in _item if entry]
        if needs_frequent_flag(status=status):
            item[self.key_column].setData(True, role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG)
        item[self.Columns.STATUS].setText(status_text)
        item[self.Columns.STATUS].setData(status_text, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.STATUS].setIcon(svg_tools.get_QIcon(sort_id_to_icon(status.sort_id())))
        item[self.Columns.STATUS].setToolTip(status_tooltip)
        item[self.Columns.LABEL].setText(label)
        item[self.Columns.LABEL].setData(label, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORIES].setText(category)
        item[self.Columns.CATEGORIES].setData(categories, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORIES].setBackground(CategoryEditor.color(category))

    def create_menu(self, position: QPoint) -> Menu:
        menu = Menu()
        # is_multisig = isinstance(self.wallet, Multisig_Wallet)
        selected = self.selected_in_column(self.Columns.TXID)
        if not selected:
            return menu
        multi_select = len(selected) > 1

        _selected_items = [self.item_from_index(item) for item in selected]
        selected_items = [item for item in _selected_items if item]
        txids = [item.text() for item in selected_items if item]
        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return menu
            item = self.item_from_index(idx)
            if not item:
                return menu
            txid = txids[0]
            menu.add_action(self.tr("Details"), partial(self.signals.open_tx_like.emit, txid))

            addr_URL = block_explorer_URL(self.config.network_config.mempool_url, "tx", txid)
            if addr_URL:
                menu.add_action(
                    self.tr("View on block explorer"),
                    partial(webopen, addr_URL),
                    icon=svg_tools.get_QIcon("block-explorer.svg"),
                )
            menu.addSeparator()

            # addr_column_title = self._source_model.horizontalHeaderItem(
            #     self.Columns.LABEL
            # ).text()
            # addr_idx = idx.sibling(idx.row(), self.Columns.LABEL)
            self.add_copy_menu(menu, idx, include_columns_even_if_hidden=[self.Columns.TXID])
            # persistent = QPersistentModelIndex(addr_idx)
            # menu.add_action(
            #     self.tr(  "Edit {}").format(addr_column_title),
            #     lambda p=persistent: self.edit(QModelIndex(p)),
            # )
            # menu.add_action(self.tr(  "Request payment"), lambda: self.main_window.receive_at(txid))
            # if not is_multisig and not self.wallet.is_watching_only():
            #     menu.add_action(self.tr(  "Sign/verify message"), lambda: self.signals.sign_verify_message(txid))
            #     menu.add_action(self.tr(  "Encrypt/decrypt message"), lambda: self.signals.encrypt_message(txid))

        menu.add_action(
            self.tr("Copy as csv"),
            partial(
                self.copyRowsToClipboardAsCSV,
                [item.data(MySortModel.role_drag_key) for item in selected_items if item],
            ),
            icon=svg_tools.get_QIcon("bi--filetype-csv.svg"),
        )

        menu.add_action(
            self.tr("Save as file"),
            partial(self.export_raw_transactions, selected_items),
            icon=svg_tools.get_QIcon("bi--download.svg"),
        )

        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return menu
            item = self.item_from_index(idx)
            if not item:
                return menu
            txid = txids[0]

            wallet = self.get_wallet(txid=txid)
            if wallet and (tx_details := wallet.get_tx(txid=txid)):
                tx_status = TxStatus.from_wallet(txid, wallet)
                if tx_status and tx_status.can_rbf():
                    menu.addSeparator()
                    if GENERAL_RBF_AVAILABLE:
                        menu.add_action(
                            self.tr("Edit with higher fee (RBF)"),
                            partial(self.edit_tx, tx_details),
                        )
                        menu.add_action(
                            self.tr("Try cancel transaction (RBF)"),
                            partial(self.cancel_tx, tx_details),
                        )
                    else:
                        menu.add_action(self.tr("Increase fee (RBF)"), partial(self.edit_tx, tx_details))

                if tx_status and self.can_cpfp(tx=tx_details.transaction, tx_status=tx_status):
                    menu.add_action(self.tr("Receive faster (CPFP)"), partial(self.cpfp_tx, tx_details))

                menu.addSeparator()

                if tx_status.is_local():
                    is_exclude_tx_ids_in_saving = False
                    if txid in wallet.exclude_tx_ids_in_saving:
                        is_exclude_tx_ids_in_saving = True
                    action_exclude_tx_ids_in_saving = menu.add_action(
                        self.tr("Remove on restart"),
                        partial(
                            self.on_exclude_tx_ids_in_saving, txid, wallet, not is_exclude_tx_ids_in_saving
                        ),
                    )
                    action_exclude_tx_ids_in_saving.setCheckable(True)
                    action_exclude_tx_ids_in_saving.setChecked(is_exclude_tx_ids_in_saving)

        # run_hook('receive_menu', menu, txids, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    def on_exclude_tx_ids_in_saving(self, txid: str, wallet: Wallet, checked: bool):
        if checked:
            wallet.exclude_tx_ids_in_saving.add(txid)
        elif txid in wallet.exclude_tx_ids_in_saving:
            wallet.exclude_tx_ids_in_saving.remove(txid)

    def get_wallet(self, txid: str) -> Wallet | None:
        for wallet in self.wallets:
            if tx_detail := wallet.get_tx(txid=txid):
                return wallet
        return None

    def can_cpfp(self, tx: bdk.Transaction, tx_status: TxStatus) -> bool:
        wallet = self.get_wallet(txid=tx.compute_txid())
        if not wallet:
            return False
        return TxTools.can_cpfp(tx=tx, wallet=wallet, tx_status=tx_status)

    def cpfp_tx(self, tx_details: TransactionDetails) -> None:
        wallet = self.get_wallet(txid=tx_details.transaction.compute_txid())
        if not wallet:
            return
        TxTools.cpfp_tx(tx_details=tx_details, wallet=wallet, signals=self.signals)

    def edit_tx(self, tx_details: TransactionDetails) -> None:
        txinfos = ToolsTxUiInfo.from_tx(
            tx_details.transaction,
            FeeInfo.from_txdetails(tx_details),
            self.config.network,
            get_wallets(self.signals),
        )
        TxTools.edit_tx(replace_tx=tx_details, txinfos=txinfos, signals=self.signals)

    def cancel_tx(self, tx_details: TransactionDetails) -> None:
        txinfos = ToolsTxUiInfo.from_tx(
            tx_details.transaction,
            FeeInfo.from_txdetails(tx_details),
            self.config.network,
            get_wallets(self.signals),
        )

        txid = tx_details.transaction.compute_txid()
        wallet = self.get_wallet(txid=txid)
        if not wallet:
            Message(
                self.tr(
                    "Cannot find wallet for transaction {txid}. Please open the corresponding wallet first."
                ).format(txid=short_tx_id(txid)),
                type=MessageType.Error,
            )
            return

        assert txinfos.spend_all_utxos, "Eeror in input selection for the cancel transaction"
        # it is ok to set amount=0, because  checked_max_amount=True
        amount = 0
        txinfos.recipients = [
            Recipient(
                str(wallet.get_address().address),
                amount=amount,
                label=f"Cancel transaction {tx_details.txid}",
                checked_max_amount=True,
            )
        ]

        self.signals.open_tx_like.emit(txinfos)

    def export_raw_transactions(
        self, selected_items: Iterable[QStandardItem], folder: str | None = None
    ) -> None:
        if not folder:
            folder = QFileDialog.getExistingDirectory(None, "Select Folder")
            if not folder:
                logger.info("No file selected")
                return

        keys = [item.data(MyItemDataRole.ROLE_KEY) for item in selected_items]

        file_paths = self.drag_keys_to_file_paths(keys, save_directory=folder)

        logger.info(f"Saved {len(file_paths)} {self.proxy.drag_key} saved to {folder}")

    def get_edit_key_from_coordinate(self, row: int, col: int) -> Any:
        if col != self.Columns.LABEL:
            return None
        return self.get_role_data_from_coordinate(row, self.key_column, role=MyItemDataRole.ROLE_KEY)

    def on_edited(self, idx: QModelIndex, edit_key: str, *, text: str) -> None:
        txid = edit_key

        wallet = self.get_wallet(txid=txid)
        if not wallet:
            return
        wallet.labels.set_tx_label(edit_key, text, timestamp="now")

        fulltxdetails = wallet.get_dict_fulltxdetail().get(txid)
        self.signals.wallet_signals[wallet.id].updated.emit(
            UpdateFilter(
                txids=[txid],
                addresses=(
                    [pythonutxo.address for pythonutxo in fulltxdetails.outputs.values() if pythonutxo]
                    if fulltxdetails
                    else []
                ),
                reason=UpdateFilterReason.UserInput,
            )
        )

    def close(self) -> bool:
        self.setParent(None)
        return super().close()


class RefreshButton(QPushButton):
    def __init__(self, parent=None, height=20) -> None:
        super().__init__(parent)
        self.setText("")
        # Use the standard pixmap for the button icon
        self.setIconSize(QSize(height, height))  # Icon size can be adjusted as needed
        self.set_icon_allow_refresh()

    def set_icon_allow_refresh(self) -> None:
        icon = svg_tools.get_QIcon("bi--arrow-clockwise.svg")
        self.setIcon(icon)

    def set_icon_is_syncing(self) -> None:

        icon = svg_tools.get_QIcon("status_waiting.svg")
        self.setIcon(icon)


class HistListWithToolbar(TreeViewWithToolbar):
    def __init__(self, hist_list: HistList, config: UserConfig, parent: QWidget | None = None) -> None:
        super().__init__(hist_list, config, parent=parent)
        self.hist_list = hist_list
        self.create_layout()

        self.sync_button = RefreshButton(height=QFontMetrics(self.balance_label.font()).height())
        self.sync_button.clicked.connect(self.hist_list.signals.request_manual_sync.emit)
        self.toolbar.insertWidget(0, self.sync_button)
        self.hist_list.signals.language_switch.connect(self.updateUi)
        for wallet in self.hist_list.wallets:
            self.hist_list.signals.wallet_signals[wallet.id].updated.connect(self.update_with_filter)

    def update_with_filter(self, update_filter: UpdateFilter):
        self.updateUi()

    def updateUi(self) -> None:
        super().updateUi()
        if self.balance_label:
            balance_total = Satoshis(self.hist_list.balance, self.config.network)

            if self.hist_list.signals and not self.hist_list.address_domain:
                if self.hist_list.signals:
                    balance_total = Satoshis(value=0, network=self.config.network)
                    for wallet in self.hist_list.wallets:
                        display_balance = self.hist_list.signals.wallet_signals[
                            wallet.id
                        ].get_display_balance.emit()
                        if isinstance(display_balance, Balance):
                            balance_total += Satoshis(display_balance.total, self.config.network)

            self.balance_label.setText(balance_total.format_as_balance())

    def create_toolbar_with_menu(self, title) -> None:
        super().create_toolbar_with_menu(title=title)

        font = QFont()
        font.setPointSize(12)
        if self.balance_label:
            self.balance_label.setFont(font)

    def on_hide_toolbar(self) -> None:
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        self.update()
