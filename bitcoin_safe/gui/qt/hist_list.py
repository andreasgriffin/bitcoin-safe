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
import os
import tempfile

from PyQt6.QtGui import QFont, QFontMetrics

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.mempool import MempoolData
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import Balance, Recipient

logger = logging.getLogger(__name__)

import datetime
import enum
from enum import IntEnum
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from PyQt6.QtCore import QMimeData, QModelIndex, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QStandardItem,
)
from PyQt6.QtWidgets import QAbstractItemView, QFileDialog, QPushButton, QStyle, QWidget

from ...i18n import translate
from ...signals import Signals, UpdateFilter, UpdateFilterReason
from ...util import (
    Satoshis,
    block_explorer_URL,
    confirmation_wait_formatted,
    time_logger,
)
from ...wallet import (
    ToolsTxUiInfo,
    TxConfirmationStatus,
    TxStatus,
    Wallet,
    get_wallet,
    get_wallets,
)
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
from .util import Message, MessageType, read_QIcon, sort_id_to_icon, webopen


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
    signal_tag_dropped = pyqtSignal(AddressDragInfo)

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

    def __init__(
        self,
        fx,
        config,
        signals: Signals,
        mempool_data: MempoolData,
        wallet_id: str,
        hidden_columns: List[int] | None = None,
        column_widths: Optional[Dict[MyTreeView.BaseColumnsEnum, int]] = None,
        address_domain: List[str] | None = None,
    ) -> None:
        super().__init__(
            config=config,
            stretch_column=HistList.Columns.LABEL,
            editable_columns=[HistList.Columns.LABEL],
            column_widths=column_widths,
            signals=signals,
            sort_column=HistList.Columns.STATUS,
            sort_order=Qt.SortOrder.DescendingOrder,
        )
        self.fx = fx
        self.mempool_data = mempool_data
        self.address_domain = address_domain
        self.hidden_columns = hidden_columns if hidden_columns else []
        self._tx_dict: Dict[str, Tuple[Wallet, bdk.TransactionDetails]] = {}  # txid -> wallet, tx
        self.signals = signals
        self.wallet_id = wallet_id
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
            self,
            drag_key="txids",
            drag_keys_to_file_paths=self.drag_keys_to_file_paths,
        )
        self.proxy = MySortModel(
            self, source_model=self._source_model, sort_role=MyItemDataRole.ROLE_SORT_ORDER
        )
        self.setModel(self.proxy)
        self.update_content()
        self.signals.wallet_signals[self.wallet_id].updated.connect(self.update_with_filter)
        self.signals.language_switch.connect(self.update)

    def get_file_data(self, txid: str) -> Optional[Data]:
        for wallet in get_wallets(self.signals):
            txdetails = wallet.get_tx(txid)
            if txdetails:
                return Data.from_tx(txdetails.transaction)
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

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        super().dragEnterEvent(event)
        if not event or event.isAccepted():
            return

        mime_data = event.mimeData()
        if mime_data and self._acceptable_mime_data(mime_data):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent | None) -> None:
        super().dragMoveEvent(event)
        if not event or event.isAccepted():
            return

        mime_data = event.mimeData()
        if mime_data and self._acceptable_mime_data(mime_data):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent | None) -> None:
        # handle dropped files
        super().dropEvent(event)
        if not event or event.isAccepted():
            return

        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            # Handle the case where the drop is not on a valid index
            return

        mime_data = event.mimeData()
        if mime_data:
            json_mime_data = self.get_json_mime_data(mime_data)
            if json_mime_data is not None:
                model = self.model()
                hit_address = model.data(model.index(index.row(), self.key_column))
                if json_mime_data.get("type") == "drag_tag":
                    if hit_address is not None:
                        drag_info = AddressDragInfo([json_mime_data.get("tag")], [hit_address])
                        logger.debug(f"drag_info {drag_info}")
                        self.signal_tag_dropped.emit(drag_info)
                    event.accept()
                    return

            elif mime_data.hasUrls():
                # Iterate through the list of dropped file URLs
                for url in mime_data.urls():
                    # Convert URL to local file path
                    self.signals.open_file_path.emit(url.toLocalFile())

        event.ignore()

    def on_double_click(self, idx: QModelIndex) -> None:
        txid = self.get_role_data_for_current_item(col=self.key_column, role=MyItemDataRole.ROLE_KEY)
        wallet, tx_details = self._tx_dict[txid]
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
        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")

        def categories_intersect(model: MyStandardItemModel, row) -> Set:
            return set(model.data(model.index(row, self.Columns.CATEGORIES))).intersection(
                set(update_filter.categories)
            )

        def tx_involves_address(txid) -> Set[str]:
            (wallet, tx) = self._tx_dict[txid]
            fulltxdetail = wallet.get_dict_fulltxdetail().get(txid)
            if not fulltxdetail:
                return set()
            return update_filter.addresses.intersection(fulltxdetail.involved_addresses())

        logger.debug(f"{self.__class__.__name__}  update_with_filter {update_filter}")
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
                log_info.append((row, txid))
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
        self, wallet: Wallet, tx: bdk.TransactionDetails, status_sort_index: int, old_balance: int
    ) -> Tuple[List[QStandardItem], int]:
        """

        Returns:
            Tuple[List[QStandardItem] , int]: items, amount
        """

        # WALLET_ID = enum.auto()
        # AMOUNT = enum.auto()
        # BALANCE = enum.auto()
        # TXID = enum.auto()
        self._tx_dict[tx.txid] = (wallet, tx)

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
        self._tx_dict = {}
        wallets = [
            wallet for wallet in get_wallets(self.signals) if self.wallet_id and wallet.id == self.wallet_id
        ]

        self._source_model.clear()
        self.update_headers(self.get_headers())

        num_shown = 0
        self.balance = 0
        for wallet in wallets:

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
        wallet, tx = self._tx_dict[key]
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
        estimated_duration_str = confirmation_wait_formatted(
            self.mempool_data.fee_rate_to_projected_block_index(fee_info.fee_rate())
        )
        status_text = (
            datetime.datetime.fromtimestamp(tx.confirmation_time.timestamp).strftime("%Y-%m-%d %H:%M")
            if tx.confirmation_time
            else estimated_duration_str
        )
        status_data = (
            datetime.datetime.fromtimestamp(tx.confirmation_time.height).strftime("%Y-%m-%d %H:%M")
            if tx.confirmation_time
            else TxConfirmationStatus.to_str(status.confirmation_status)
        )
        status_tooltip = (
            self.tr("{number} Confirmations").format(number=status.confirmations())
            if 1 <= status.confirmations() <= 6
            else status_text
        )

        _item = [self._source_model.item(row, col) for col in self.Columns]
        item = [entry for entry in _item if entry]
        if needs_frequent_flag(status=status):
            item[self.key_column].setData(True, role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG)
        item[self.Columns.STATUS].setText(status_text)
        item[self.Columns.STATUS].setData(status_data, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.STATUS].setIcon(read_QIcon(sort_id_to_icon(status.sort_id())))
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
            menu.add_action(translate("hist_list", "Details"), lambda: self.signals.open_tx_like.emit(txid))

            addr_URL = block_explorer_URL(self.config.network_config.mempool_url, "tx", txid)
            if addr_URL:
                menu.add_action(
                    translate("hist_list", "View on block explorer"),
                    lambda: webopen(addr_URL),
                    icon=read_QIcon("link.svg"),
                )
            menu.addSeparator()

            # addr_column_title = self._source_model.horizontalHeaderItem(
            #     self.Columns.LABEL
            # ).text()
            # addr_idx = idx.sibling(idx.row(), self.Columns.LABEL)
            self.add_copy_menu(menu, idx, include_columns_even_if_hidden=[self.Columns.TXID])
            # persistent = QPersistentModelIndex(addr_idx)
            # menu.add_action(
            #     translate("hist_list", "Edit {}").format(addr_column_title),
            #     lambda p=persistent: self.edit(QModelIndex(p)),
            # )
            # menu.add_action(translate("hist_list", "Request payment"), lambda: self.main_window.receive_at(txid))
            # if not is_multisig and not self.wallet.is_watching_only():
            #     menu.add_action(translate("hist_list", "Sign/verify message"), lambda: self.signals.sign_verify_message(txid))
            #     menu.add_action(translate("hist_list", "Encrypt/decrypt message"), lambda: self.signals.encrypt_message(txid))

        menu.add_action(
            translate("hist_list", "Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
            icon=read_QIcon("csv-file.svg"),
        )

        menu.add_action(
            translate("hist_list", "Save as file"),
            lambda: self.export_raw_transactions(selected_items),
            icon=(self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
        )

        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return menu
            item = self.item_from_index(idx)
            if not item:
                return menu
            txid = txids[0]

            wallet, tx_details = self._tx_dict[txid]
            tx_status = TxStatus.from_wallet(txid, wallet)
            if tx_status and tx_status.can_rbf():
                menu.addSeparator()
                menu.add_action(
                    translate("hist_list", "Edit with higher fee (RBF)"), lambda: self.edit_tx(tx_details)
                )

                menu.add_action(
                    translate("hist_list", "Try cancel transaction (RBF)"), lambda: self.cancel_tx(tx_details)
                )

        # run_hook('receive_menu', menu, txids, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    def edit_tx(self, tx_details: bdk.TransactionDetails) -> None:
        txinfos = ToolsTxUiInfo.from_tx(
            tx_details.transaction,
            FeeInfo.from_txdetails(tx_details),
            self.config.network,
            get_wallets(self.signals),
        )

        self.signals.open_tx_like.emit(txinfos)

    def cancel_tx(self, tx_details: bdk.TransactionDetails) -> None:
        txinfos = ToolsTxUiInfo.from_tx(
            tx_details.transaction,
            FeeInfo.from_txdetails(tx_details),
            self.config.network,
            get_wallets(self.signals),
        )

        wallet = get_wallet(self.wallet_id, self.signals)
        if not wallet:
            Message(
                self.tr("Cannot fetch wallet '{id}'. Please open the wallet first.").format(
                    id=self.wallet_id
                ),
                type=MessageType.Error,
            )
            return

        assert txinfos.spend_all_utxos, "Eeror in input selection for the cancel transaction"
        # it is ok to set amount=0, because  checked_max_amount=True
        amount = 0
        txinfos.recipients = [
            Recipient(
                wallet.get_address().address.as_string(),
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

        logger.info(f"Saved {len(file_paths)} {self._source_model.drag_key} saved to {folder}")

    def get_edit_key_from_coordinate(self, row: int, col: int) -> Any:
        if col != self.Columns.LABEL:
            return None
        return self.get_role_data_from_coordinate(row, self.key_column, role=MyItemDataRole.ROLE_KEY)

    def on_edited(self, idx: QModelIndex, edit_key: str, *, text: str) -> None:
        txid = edit_key
        wallet, tx = self._tx_dict[txid]

        wallet.labels.set_tx_label(edit_key, text, timestamp="now")

        fulltxdetails = wallet.get_dict_fulltxdetail().get(txid)
        self.signals.wallet_signals[self.wallet_id].updated.emit(
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


class RefreshButton(QPushButton):
    def __init__(self, parent=None, height=20) -> None:
        super().__init__(parent)
        self.setText("")
        # Use the standard pixmap for the button icon
        self.setIconSize(QSize(height, height))  # Icon size can be adjusted as needed
        self.set_icon_allow_refresh()

    def set_icon_allow_refresh(self) -> None:
        icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self.setIcon(icon)

    def set_icon_is_syncing(self) -> None:

        icon = read_QIcon("status_waiting.svg")
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
        self.hist_list.signals.wallet_signals[self.hist_list.wallet_id].updated.connect(self.updateUi)

    def updateUi(self) -> None:
        super().updateUi()
        if self.balance_label:
            balance_total = Satoshis(self.hist_list.balance, self.config.network)

            if self.hist_list.signals and not self.hist_list.address_domain:
                if self.hist_list.signals:
                    display_balance = (
                        self.hist_list.signals.wallet_signals[self.hist_list.wallet_id]
                        .get_display_balance.emit()
                        .get(self.hist_list.wallet_id)
                    )
                    if isinstance(display_balance, Balance):
                        balance_total = Satoshis(display_balance.total, self.config.network)

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
