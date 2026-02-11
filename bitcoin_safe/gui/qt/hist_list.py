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

from __future__ import annotations

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
from collections.abc import Iterable
from datetime import datetime
from enum import IntEnum
from functools import partial
from typing import Any, cast

from bitcoin_qr_tools.data import Data
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from bitcoin_safe_lib.gui.qt.util import confirmation_wait_formatted
from bitcoin_safe_lib.util import time_logger
from bitcoin_safe_lib.util_os import webopen
from PyQt6.QtCore import QMimeData, QModelIndex, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QStandardItem
from PyQt6.QtWidgets import QAbstractItemView, QFileDialog, QWidget
from typing_extensions import Self

from bitcoin_safe.client import ProgressInfo, SyncStatus
from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import MIN_RELAY_FEE
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.tx_tools import TxTools
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.mempool_manager import MempoolManager
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import Recipient, TransactionDetails
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.tx import short_tx_id

from ...i18n import translate
from ...signals import UpdateFilter, UpdateFilterReason, WalletFunctions
from ...wallet import LOCAL_TX_LAST_SEEN, ToolsTxUiInfo, TxStatus, Wallet, get_wallets
from .cbf_progress_bar import CBFProgressBar
from .drag_info import AddressDragInfo
from .my_treeview import (
    MyItemDataRole,
    MySortModel,
    MyStandardItemModel,
    MyTreeView,
    TreeViewWithToolbar,
    header_item,
    needs_frequent_flag,
)
from .util import (
    ButtonInfoType,
    Message,
    MessageType,
    block_explorer_URL,
    button_info,
    category_color,
    sort_id_to_icon,
)

logger = logging.getLogger(__name__)


class AddressUsageStateFilter(IntEnum):
    ALL = 0
    UNUSED = 1
    FUNDED = 2
    USED_AND_EMPTY = 3
    FUNDED_OR_UNUSED = 4

    def ui_text(self) -> str:
        """Ui text."""
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
        """Ui text."""
        return {
            self.ALL: translate("hist_list", "All types"),
            self.RECEIVING: translate("hist_list", "Receiving"),
            self.CHANGE: translate("hist_list", "Change"),
        }[self]


class HistList(MyTreeView[str]):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    signal_tag_dropped = cast(SignalProtocol[[AddressDragInfo]], pyqtSignal(AddressDragInfo))

    show_change: AddressTypeFilter
    show_used: AddressUsageStateFilter

    @staticmethod
    def cls_kwargs(
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        mempool_manager: MempoolManager,
    ):
        return {
            "config": config,
            "wallet_functions": wallet_functions,
            "mempool_manager": mempool_manager,
            "fx": fx,
        }

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
        Columns.AMOUNT: Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        Columns.BALANCE: Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
    }

    column_widths: dict[MyTreeView.BaseColumnsEnum, int] = {Columns.TXID: 100, Columns.WALLET_ID: 100}

    def __init__(
        self,
        fx: FX,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        mempool_manager: MempoolManager,
        wallets: list[Wallet] | None = None,
        address_domain: list[str] | None = None,
        hidden_columns: list[int] | None = None,
        selected_ids: list[str] | None = None,
        _scroll_position=0,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            config=config,
            stretch_column=HistList.Columns.LABEL,
            editable_columns=[HistList.Columns.LABEL],
            column_widths=self.column_widths,
            signals=wallet_functions.signals,
            sort_column=HistList.Columns.STATUS,
            sort_order=Qt.SortOrder.DescendingOrder,
            hidden_columns=hidden_columns,
            selected_ids=selected_ids,
            _scroll_position=_scroll_position,
        )
        self.fx = fx
        self._signal_tracker_wallet_signals = SignalTracker()
        self.mempool_manager = mempool_manager
        self.address_domain = address_domain
        self.wallet_functions = wallet_functions
        self.wallets = wallets if wallets else []
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
        self.set_wallets(self.wallets)

    def set_wallets(self, wallets: list[Wallet]):
        """Set wallets."""
        self._signal_tracker_wallet_signals.disconnect_all()
        self.wallets = wallets

        for wallet in self.wallets:
            self._signal_tracker_wallet_signals.connect(
                self.wallet_functions.wallet_signals[wallet.id].updated, self.update_with_filter
            )

        self.update_content()

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["address_domain"] = self.address_domain
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> Self:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def get_file_data(self, txid: str) -> Data | None:
        """Get file data."""
        for wallet in get_wallets(self.wallet_functions):
            txdetails = wallet.get_tx(txid)
            if txdetails:
                return Data.from_tx(txdetails.transaction, network=wallet.network)
        return None

    def drag_keys_to_file_paths(
        self, drag_keys: Iterable[str], save_directory: str | None = None
    ) -> list[str]:
        """Drag keys to file paths."""
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
                    suffix=".tx",
                    prefix=f"{key} ",
                )

            data.write_to_filedescriptor(file_descriptor)

            # Add the file URL to the list
            file_urls.append(file_path)

        return file_urls

    def _acceptable_mime_data(self, mime_data: QMimeData) -> bool:
        """Acceptable mime data."""
        if mime_data and self.get_json_mime_data(mime_data) is not None:
            return True
        if mime_data and mime_data.hasUrls():
            return True
        return False

    def on_double_click(self, source_idx: QModelIndex) -> None:
        """On double click."""
        txid = self.get_role_data_for_current_item(col=self.key_column, role=MyItemDataRole.ROLE_KEY)
        wallet = self.get_wallet(txid=txid)
        if not wallet:
            return
        tx_details = wallet.get_tx(txid=txid)
        if not tx_details:
            return
        self.signals.open_tx_like.emit(tx_details)

    def toggle_change(self, state: int) -> None:
        """Toggle change."""
        if state == self.show_change:
            return
        self.show_change = AddressTypeFilter(state)
        self.update_content()

    def toggle_used(self, state: int) -> None:
        """Toggle used."""
        if state == self.show_used:
            return
        self.show_used = AddressUsageStateFilter(state)
        self.update_content()

    @time_logger
    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        """Update with filter."""
        if update_filter.refresh_all:
            return self.update_content()
        logger.debug(f"{self.__class__.__name__} update_with_filter")

        def categories_intersect(model: MyStandardItemModel, row) -> set:
            """Categories intersect."""
            return set(model.data(model.index(row, self.Columns.CATEGORIES))).intersection(
                set(update_filter.categories)
            )

        def tx_involves_address(txid) -> set[str]:
            """Tx involves address."""
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

    def get_headers(self) -> dict[MyTreeView.BaseColumnsEnum, QStandardItem]:
        """Get headers."""
        return {
            self.Columns.WALLET_ID: header_item(self.tr("Wallet")),
            self.Columns.STATUS: header_item(self.tr("Status")),
            self.Columns.CATEGORIES: header_item(self.tr("Category")),
            self.Columns.LABEL: header_item(self.tr("Label")),
            self.Columns.AMOUNT: header_item(self.tr("Δ"), tooltip=self.tr("Delta Balance")),
            self.Columns.BALANCE: header_item(self.tr("Balance")),
            self.Columns.TXID: header_item(self.tr("Txid"), tooltip=self.tr("Transaction id")),
        }

    def _init_row(
        self, wallet: Wallet, tx: TransactionDetails, status_sort_index: int, old_balance: int
    ) -> tuple[list[QStandardItem], int]:
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
        labels[self.Columns.AMOUNT] = Satoshis(amount, wallet.network).str_as_change(
            btc_symbol=self.config.bitcoin_symbol.value
        )

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
        """Update content."""
        if self.maybe_defer_update():
            return

        self._before_update_content()

        self._source_model.clear()
        self.update_headers(self.get_headers())

        num_shown = 0
        self.balance = 0
        for wallet in self.wallets:
            txid_domain: set[str] | None = None
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
        """Refresh row."""
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
            if status.is_in_mempool():
                status_text = confirmation_wait_formatted(
                    self.mempool_manager.fee_rate_to_projected_block_index(fee_rate)
                )
            else:
                status_text = self.tr("Local")

        if 1 <= status.confirmations() <= 6:
            status_tooltip = self.tr("{number} Confirmations").format(number=status.confirmations())
        elif status.confirmations() <= 0:
            if status.is_in_mempool():
                status_tooltip = self.tr("Waiting to be included in a block")
            else:
                status_tooltip = self.tr("Not broadcasted.")
        else:
            status_tooltip = status_text

        _item = [self._source_model.item(row, col) for col in self.Columns]
        item = [entry for entry in _item if entry]
        item[self.key_column].setData(
            needs_frequent_flag(status=status), role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG
        )
        item[self.Columns.STATUS].setText(status_text)
        item[self.Columns.STATUS].setData(status_text, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.STATUS].setIcon(svg_tools.get_QIcon(sort_id_to_icon(status.sort_id())))
        item[self.Columns.STATUS].setToolTip(status_tooltip)
        item[self.Columns.LABEL].setText(label)
        item[self.Columns.LABEL].setData(label, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORIES].setText(category)
        item[self.Columns.CATEGORIES].setData(categories, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORIES].setBackground(category_color(category))

    def create_menu(self, position: QPoint) -> Menu:
        """Create menu."""
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
            idx = self._p2s(self.indexAt(position))
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
            idx = self._p2s(self.indexAt(position))
            if not idx.isValid():
                return menu
            item = self.item_from_index(idx)
            if not item:
                return menu
            txid = txids[0]

            wallet = self.get_wallet(txid=txid)
            if wallet and (tx_details := wallet.get_tx(txid)):
                tx_status = TxStatus.from_wallet(txid, wallet)
                menu.addSeparator()
                if TxTools.can_cancel(tx_status=tx_status):
                    menu.add_action(
                        button_info(ButtonInfoType.cancel_with_rbf).text,
                        partial(self.cancel_tx, tx_details),
                        icon=button_info(ButtonInfoType.cancel_with_rbf).icon,
                    )
                if TxTools.can_edit_safely(tx_status=tx_status):
                    menu.add_action(
                        button_info(ButtonInfoType.rbf).text,
                        partial(self.edit_tx, tx_details, tx_status),
                        icon=button_info(ButtonInfoType.rbf).icon,
                    )
                if TxTools.can_rbf_safely(tx=tx_details.transaction, tx_status=tx_status):
                    menu.add_action(
                        button_info(ButtonInfoType.rbf).text,
                        partial(self.rbf_tx, tx_details, tx_status),
                        icon=button_info(ButtonInfoType.rbf).icon,
                    )

                if TxTools.can_cpfp(
                    wallet=wallet, tx_status=tx_status, wallet_functions=self.wallet_functions
                ):
                    menu.add_action(
                        button_info(ButtonInfoType.cpfp).text,
                        partial(self.cpfp_tx, tx_details),
                        icon=button_info(ButtonInfoType.cpfp).icon,
                    )

                menu.addSeparator()

                if tx_status.is_local():
                    menu.add_action(
                        self.tr("Remove"),
                        partial(
                            self.signals.evict_txs_from_wallet_id.emit, [txid], wallet.id, LOCAL_TX_LAST_SEEN
                        ),
                    )
                elif tx_status.is_unconfirmed():
                    menu.add_action(
                        self.tr("Remove"),
                        partial(
                            self.signals.evict_txs_from_wallet_id.emit,
                            [txid],
                            wallet.id,
                            int(datetime.now().timestamp()),
                        ),
                    )

        # run_hook('receive_menu', menu, txids, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    def get_wallet(self, txid: str) -> Wallet | None:
        """Get wallet."""
        for wallet in self.wallets:
            if wallet.get_tx(txid=txid):
                return wallet
        return None

    def cpfp_tx(self, tx_details: TransactionDetails) -> None:
        """Cpfp tx."""
        wallet = self.get_wallet(txid=tx_details.txid)
        if not wallet:
            return
        TxTools.cpfp_tx(
            tx_details=tx_details,
            wallet=wallet,
            wallet_functions=self.wallet_functions,
            parent=self,
        )

    def rbf_tx(
        self,
        tx_details: TransactionDetails,
        tx_status: TxStatus,
    ) -> None:
        """Rbf tx."""
        txinfos = ToolsTxUiInfo.from_tx(
            tx_details.transaction,
            FeeInfo.from_txdetails(tx_details),
            self.config.network,
            get_wallets(self.wallet_functions),
        )
        TxTools.rbf_tx(
            replace_tx=tx_details.transaction,
            tx_status=tx_status,
            txinfos=txinfos,
            wallet_functions=self.wallet_functions,
        )

    def edit_tx(
        self,
        tx_details: TransactionDetails,
        tx_status: TxStatus,
    ) -> None:
        """Edit tx."""
        txinfos = ToolsTxUiInfo.from_tx(
            tx_details.transaction,
            FeeInfo.from_txdetails(tx_details),
            self.config.network,
            get_wallets(self.wallet_functions),
        )
        TxTools.edit_tx(
            replace_tx=tx_details,
            tx_status=tx_status,
            txinfos=txinfos,
            wallet_functions=self.wallet_functions,
        )

    def cancel_tx(self, tx_details: TransactionDetails) -> None:
        """Cancel tx."""
        txinfos = ToolsTxUiInfo.from_tx(
            tx_details.transaction,
            FeeInfo.from_txdetails(tx_details),
            self.config.network,
            get_wallets(self.wallet_functions),
        )

        wallet = self.get_wallet(txid=tx_details.txid)
        if not wallet:
            Message(
                self.tr(
                    "Cannot find wallet for transaction {txid}. Please open the corresponding wallet first."
                ).format(txid=short_tx_id(tx_details.txid)),
                type=MessageType.Error,
                parent=self,
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
        """Export raw transactions."""
        if not folder:
            folder = QFileDialog.getExistingDirectory(None, "Select Folder")
            if not folder:
                logger.info("No file selected")
                return

        keys = [item.data(MyItemDataRole.ROLE_KEY) for item in selected_items]

        file_paths = self.drag_keys_to_file_paths(keys, save_directory=folder)

        logger.info(f"Saved {len(file_paths)} {self.proxy.drag_key} saved to {folder}")

    def get_edit_key_from_coordinate(self, row: int, col: int) -> Any:
        """Get edit key from coordinate."""
        if col != self.Columns.LABEL:
            return None
        return self.get_role_data_from_coordinate(row, self.key_column, role=MyItemDataRole.ROLE_KEY)

    def on_edited(self, source_idx: QModelIndex, edit_key: str, text: str) -> None:
        """On edited."""
        txid = edit_key

        wallet = self.get_wallet(txid=txid)
        if not wallet:
            return
        wallet.labels.set_tx_label(edit_key, text, timestamp="now")

        fulltxdetails = wallet.get_dict_fulltxdetail().get(txid)
        self.wallet_functions.wallet_signals[wallet.id].updated.emit(
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
        """Close."""
        self.setParent(None)
        self._signal_tracker_wallet_signals.disconnect_all()
        return super().close()


class HistListWithToolbar(TreeViewWithToolbar):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        HistList.__name__: HistList,
    }

    @staticmethod
    def cls_kwargs(
        config: UserConfig,
    ):
        return {
            "config": config,
        }

    signal_export_pdf_statement = cast(SignalProtocol[[str]], pyqtSignal(str))  #  wallet_id
    signal_disable_spinning_button = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, hist_list: HistList, config: UserConfig, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(hist_list, config, parent=parent)
        self.default_export_csv_filename = "history_export.csv"
        self.hist_list = hist_list
        self.create_layout()

        self.sync_button = SpinningButton(
            signal_stop_spinning=self.signal_disable_spinning_button,
            enabled_icon=svg_tools.get_QIcon("bi--arrow-clockwise.svg"),
            parent=self,
            timeout=60 * 60,
            text="",
            svg_tools=svg_tools,
        )
        self.sync_button.setFixedWidth(self.sync_button.height())
        self.sync_button.clicked.connect(self._on_sync_button_clicked)
        self.toolbar.insertWidget(0, self.sync_button)

        self.cbf_progress_bar = CBFProgressBar(config=config, parent=self)
        self.toolbar.insertWidget(1, self.cbf_progress_bar)

        # signals
        self.hist_list.signals.language_switch.connect(self.updateUi)
        for wallet in self.hist_list.wallets:
            self.hist_list.wallet_functions.wallet_signals[wallet.id].updated.connect(self.update_with_filter)

    def _on_sync_button_clicked(self):
        """On sync button clicked."""
        self.hist_list.signals.request_manual_sync.emit()

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["hist_list"] = self.hist_list
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> Self:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def update_with_filter(self, update_filter: UpdateFilter):
        """Update with filter."""
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        if self.balance_label:
            balance_total = Satoshis(self.hist_list.balance, self.config.network)
            self.balance_label.setText(
                balance_total.format_as_balance(btc_symbol=self.config.bitcoin_symbol.value)
            )
        self.action_export_pdf_statement.setText(self.tr("&Generate PDF balance Statement"))

    def _set_progress_info(self, progress_info: ProgressInfo) -> None:
        """Update progress information and the sync button animation."""
        self.cbf_progress_bar._set_progress_info(progress_info)
        if progress_info.sync_status == SyncStatus.syncing:
            self.sync_button.start_spin()
        else:
            self.sync_button.enable_button()

    def create_toolbar_with_menu(self, title) -> None:
        """Create toolbar with menu."""
        super().create_toolbar_with_menu(title=title)

        self.action_export_pdf_statement = self.menu.add_action(
            "", self._do_export_pdf_statement, icon=svg_tools.get_QIcon("bi--filetype-pdf.svg")
        )

        font = QFont()
        font.setPointSize(12)
        if self.balance_label:
            self.balance_label.setFont(font)

    def _do_export_pdf_statement(self):
        """Do export pdf statement."""
        for wallet in self.hist_list.wallets:
            self.signal_export_pdf_statement.emit(wallet.id)

    def on_hide_toolbar(self) -> None:
        """On hide toolbar."""
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        self.update()
