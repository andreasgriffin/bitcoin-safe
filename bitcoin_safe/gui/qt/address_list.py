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
from enum import IntEnum
from functools import partial
from typing import Any, cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.util import time_logger
from bitcoin_safe_lib.util_os import webopen
from PyQt6.QtCore import QMimeData, QModelIndex, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDropEvent, QFont, QStandardItem
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTreeView,
    QWidget,
)

from bitcoin_safe.category_info import CategoryInfo
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.gui.qt.category_manager.category_manager import AddressDragInfo
from bitcoin_safe.gui.qt.category_manager.category_menu import CategoryComboBox
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.pythonbdk_types import Balance, PythonUtxo
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init

from ...config import UserConfig
from ...i18n import translate
from ...labels import LabelSnapshot, LabelSnapshotReason
from ...network_config import BlockchainType
from ...rpc import send_rpc_command
from ...signals import (
    UpdateFilter,
    UpdateFilterReason,
    WalletFunctions,
    WalletSignals,
)
from ...tx import TxUiInfos
from ...wallet import TxStatus, Wallet
from .my_treeview import (
    DropRule,
    MyItemDataRole,
    MySortModel,
    MyStandardItemModel,
    MyTreeView,
    TreeViewWithToolbar,
    header_item,
    needs_frequent_flag,
)
from .util import (
    ColorScheme,
    Message,
    MessageType,
    block_explorer_URL,
    category_color,
    create_color_circle,
    do_copy,
    sort_id_to_icon,
)

logger = logging.getLogger(__name__)


class ImportLabelMenu(Menu):
    def __init__(self, wallet_signals: WalletSignals) -> None:
        """Initialize instance."""
        super().__init__()
        self.wallet_signals = wallet_signals

        self.action_import = self.add_action(
            "", self.wallet_signals.import_labels.emit, icon=svg_tools.get_QIcon("bi--upload.svg")
        )
        self.action_bip329_import = self.add_action(
            "", self.wallet_signals.import_bip329_labels.emit, icon=svg_tools.get_QIcon("bi--upload.svg")
        )
        self.action_electrum_import = self.add_action(
            "",
            self.wallet_signals.import_electrum_wallet_labels.emit,
            icon=svg_tools.get_QIcon("bi--upload.svg"),
        )
        self.action_nostr_import = self.add_action(
            "",
            self.import_nostr_labels,
            icon=svg_tools.get_QIcon("bi--cloud.svg"),
        )
        self.updateUi()

    def import_nostr_labels(self):
        """Import nostr labels."""
        Message(
            translate(
                "import",
                "Please go to the Sync Tab and import your Sync key there. The labels will then be automatically restored.",
            ),
            parent=self,
        )

    def updateUi(self) -> None:
        """UpdateUi."""
        self.setTitle(self.tr("Import labels and categories"))
        self.action_import.setText(self.tr("Full (Bitcoin Safe)"))
        self.action_bip329_import.setText(self.tr("Exchange format (BIP329)"))
        self.action_electrum_import.setText(self.tr("Electrum Wallet"))
        self.action_nostr_import.setText(self.tr("Restore labels from cloud using an existing sync key"))


class ExportLabelMenu(Menu):
    def __init__(self, wallet_signals: WalletSignals) -> None:
        """Initialize instance."""
        super().__init__()
        self.wallet_signals = wallet_signals

        self.action_export_full = self.add_action(
            "", self.wallet_signals.export_labels.emit, icon=svg_tools.get_QIcon("bi--download.svg")
        )
        self.action_bip329 = self.add_action(
            "", self.wallet_signals.export_bip329_labels.emit, icon=svg_tools.get_QIcon("bi--download.svg")
        )
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        self.setTitle(self.tr("Export labels and categories"))
        self.action_export_full.setText(self.tr("Full (Bitcoin Safe)"))
        self.action_bip329.setText(self.tr("Exchange format (BIP329)"))


class LabelSnapshotMenu(Menu):
    def __init__(
        self, wallets: dict[str, Wallet], wallet_functions: WalletFunctions, parent: QWidget | None = None
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.wallet_functions = wallet_functions
        self.wallets = wallets
        self.aboutToShow.connect(self._populate_snapshot_menu)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.setTitle(self.tr("Restore labels and categories snapshot"))

    def _populate_snapshot_menu(self) -> None:
        """Populate snapshot menu."""
        self.clear()

        if not self.wallets:
            action = self.add_action(self.tr("No wallets available"))
            action.setEnabled(False)
            return

        multiple_wallets = len(self.wallets) > 1
        for wallet in self.wallets.values():
            target_menu = self.add_menu(wallet.id) if multiple_wallets else self
            self._fill_snapshot_menu_for_wallet(target_menu, wallet)

    def _fill_snapshot_menu_for_wallet(self, menu: Menu, wallet: Wallet) -> None:
        """Fill snapshot menu for wallet."""
        snapshots = wallet.labels.get_snapshots()
        if snapshots:
            for snapshot in reversed(snapshots):
                text = self._format_snapshot_label(snapshot)
                action = menu.add_action(text)
                action.triggered.connect(partial(self._restore_wallet_snapshot, wallet, snapshot))
        else:
            placeholder = menu.add_action(self.tr("No previous snapshots"))
            placeholder.setEnabled(False)

    def _snapshot_reason_text(self, reason: LabelSnapshotReason) -> str:
        """Snapshot reason text."""
        if reason == LabelSnapshotReason.AUTOMATIC:
            return self.tr("Automatic snapshot")
        if reason == LabelSnapshotReason.RESTORE:
            return self.tr("State before restore")

    def _format_snapshot_label(self, snapshot: LabelSnapshot) -> str:
        """Format snapshot label."""
        timestamp_text = snapshot.created_at.strftime("%Y-%m-%d %H:%M:%S")
        reason_text = self._snapshot_reason_text(snapshot.reason)
        if reason_text:
            return " - ".join(
                [
                    timestamp_text,
                    reason_text,
                    self.tr("{count} Labels").format(count=snapshot.count_address_labels),
                ]
            )
        return timestamp_text

    def _restore_wallet_snapshot(self, wallet: Wallet, snapshot: LabelSnapshot) -> None:
        """Restore wallet snapshot."""
        changed_items = wallet.labels.restore_snapshot(snapshot)
        if not changed_items:
            return

        wallet_signals = self.wallet_functions.wallet_signals.get(wallet.id)
        if wallet_signals:
            wallet_signals.updated.emit(
                changed_items.to_update_filter(reason=UpdateFilterReason.RestoredSnapshot)
            )

        timestamp_text = snapshot.created_at.strftime("%Y-%m-%d %H:%M:%S")
        Message(
            self.tr("Restored labels snapshot from {timestamp}").format(timestamp=timestamp_text),
            type=MessageType.Info,
            parent=self,
        )


class AddressUsageStateFilter(IntEnum):
    ALL = 0
    UNUSED = 1
    FUNDED = 2
    USED_AND_EMPTY = 3
    FUNDED_OR_UNUSED = 4

    def ui_text(self) -> str:
        """Ui text."""
        return {
            self.ALL: translate("address_list", "All status"),
            self.UNUSED: translate("address_list", "Unused"),
            self.FUNDED: translate("address_list", "Funded"),
            self.USED_AND_EMPTY: translate("address_list", "Used and empty"),
            self.FUNDED_OR_UNUSED: translate("address_list", "Funded or Unused"),
        }[self]


class AddressTypeFilter(IntEnum):
    ALL = 0
    RECEIVING = 1
    CHANGE = 2

    def ui_text(self) -> str:
        """Ui text."""
        return {
            self.ALL: translate("address_list", "All types"),
            self.RECEIVING: translate("address_list", "Receiving"),
            self.CHANGE: translate("address_list", "Change"),
        }[self]


class AddressList(MyTreeView[str]):
    signal_tag_dropped = cast(SignalProtocol[[AddressDragInfo]], pyqtSignal(AddressDragInfo))

    class Columns(MyTreeView.BaseColumnsEnum):
        NUM_TXS = enum.auto()
        WALLET_ID = enum.auto()
        TYPE = enum.auto()
        INDEX = enum.auto()
        ADDRESS = enum.auto()
        CATEGORY = enum.auto()
        LABEL = enum.auto()
        COIN_BALANCE = enum.auto()
        FIAT_BALANCE = enum.auto()

    filter_columns = [
        Columns.TYPE,
        Columns.ADDRESS,
        Columns.CATEGORY,
        Columns.LABEL,
        Columns.COIN_BALANCE,
    ]
    column_alignments = {
        Columns.NUM_TXS: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.WALLET_ID: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.TYPE: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.INDEX: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.ADDRESS: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.CATEGORY: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.LABEL: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.COIN_BALANCE: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        Columns.FIAT_BALANCE: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    }

    stretch_column = Columns.LABEL
    key_column = Columns.ADDRESS
    column_widths: dict[MyTreeView.BaseColumnsEnum, int] = {
        Columns.ADDRESS: 150,
        Columns.COIN_BALANCE: 120,
        Columns.FIAT_BALANCE: 110,
    }

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
        fx: FX,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        wallets: list[Wallet] | None = None,
        hidden_columns: list[int] | None = None,
        selected_ids: list[str] | None = None,
        _scroll_position=0,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            config=config,
            signals=wallet_functions.signals,
            stretch_column=self.stretch_column,
            column_widths=self.column_widths,
            editable_columns=[AddressList.Columns.LABEL],
            sort_column=AddressList.Columns.COIN_BALANCE,
            sort_order=Qt.SortOrder.DescendingOrder,
            hidden_columns=hidden_columns,
            selected_ids=selected_ids,
            _scroll_position=_scroll_position,
        )
        self.fx = fx
        self.wallet_functions = wallet_functions
        self.wallets: dict[str, Wallet] = {}
        self._signal_tracker_wallet_signals = SignalTracker()
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.current_change_filter = AddressTypeFilter.ALL
        self.current_used_filter = AddressUsageStateFilter.ALL
        self.current_category_filter: str | None = None
        self._source_model = MyStandardItemModel(
            key_column=self.key_column,
            parent=self,
        )
        self.proxy = MySortModel(
            key_column=self.key_column,
            Columns=self.Columns,
            drag_key="addresses",
            parent=self,
            source_model=self._source_model,
            sort_role=MyItemDataRole.ROLE_SORT_ORDER,
        )
        self.set_wallets(wallets=wallets)

        ColorScheme.update_from_widget(self)

        self.setModel(self.proxy)
        self.setSortingEnabled(True)  # Allow user to sort by clicking column headers
        self.updateUi()

        # signals
        self.fx.signal_data_updated.connect(self.on_update_fx_rates)

    def _set_wallets(self, wallets: list[Wallet] | None):
        """Set wallets."""
        self._signal_tracker_wallet_signals.disconnect_all()

        self.wallets.clear()
        self.wallets.update({wallet.id: wallet for wallet in wallets} if wallets else {})
        for wallet_id in self.wallets.keys():
            wallet_signals = self.wallet_functions.wallet_signals.get(wallet_id)
            if not wallet_signals:
                continue
            self._signal_tracker_wallet_signals.connect(wallet_signals.updated, self.update_with_filter)

    def set_wallets(self, wallets: list[Wallet] | None):
        """Set wallets."""
        self._set_wallets(wallets=wallets)
        self.update_content()

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        return d

    def get_drop_rules(self) -> list[DropRule]:
        # ─── “drag_tag” JSON only ON items ─────────────────────────────────
        """Get drop rules."""

        def mime_pred_tag(md: QMimeData) -> bool:
            """Mime pred tag."""
            d = self.get_json_mime_data(md)
            return bool(d and d.get("type") == "drag_tag" and isinstance(d.get("tag"), (list, str)))

        def handler_tag(view: QTreeView, e: QDropEvent, source_idx: QModelIndex) -> None:
            """Handler tag."""
            md = e.mimeData()
            if not md:
                e.ignore()
                return
            d = self.get_json_mime_data(md)
            if not isinstance(d, dict):
                e.ignore()
                return
            tag = d["tag"]
            # if it's a singleton list, unwrap it:
            if isinstance(tag, list) and len(tag) == 1:
                tag = tag[0]
            if not isinstance(tag, str | None):
                e.ignore()
                return

            # lookup the hit‐address under the drop index
            hit_address = self._source_model.data(
                self._source_model.index(source_idx.row(), self.Columns.ADDRESS)
            )
            if hit_address is not None:
                info = AddressDragInfo([tag], [hit_address])
                self.signal_tag_dropped.emit(info)
                e.acceptProposedAction()
            else:
                e.ignore()

        return super().get_drop_rules() + [
            DropRule(
                mime_pred=mime_pred_tag,
                allowed_positions=[
                    QAbstractItemView.DropIndicatorPosition.OnItem,
                ],
                handler=handler_tag,
            ),
        ]

    def get_wallet(self, row: int) -> None | Wallet:
        """Get wallet."""
        item = self._source_model.item(row, self.Columns.WALLET_ID)
        if not item:
            return None
        wallet_id = item.data(role=MyItemDataRole.ROLE_CLIPBOARD_DATA)
        if not wallet_id:
            return None
        return self.wallets.get(wallet_id)

    def on_double_click(self, source_idx: QModelIndex) -> None:
        """On double click."""
        addr = self.get_role_data_for_current_item(col=self.key_column, role=MyItemDataRole.ROLE_KEY)
        if not addr or not (wallet := self.get_wallet(source_idx.row())):
            return
        wallet_signals = self.wallet_functions.wallet_signals.get(wallet.id)
        if not wallet_signals:
            return
        wallet_signals.show_address.emit(addr, wallet.id)

    def get_address(
        self,
        wallet: Wallet,
        force_new=False,
        category: str | None = None,
    ) -> bdk.AddressInfo:
        """Get address."""
        if force_new:
            address_info = wallet.get_address(force_new=force_new)
            address = str(address_info.address)
            wallet.labels.set_addr_category(address, category, timestamp="now")

            if wallet_signals := self.wallet_functions.wallet_signals.get(wallet.id):
                wallet_signals.updated.emit(
                    UpdateFilter(addresses=set([address]), reason=UpdateFilterReason.NewAddressRevealed)
                )
        else:
            address_info = wallet.get_unused_category_address(category)
            address = str(address_info.address)

            if self.wallet_functions:
                self.wallet_functions.wallet_signals[wallet.id].updated.emit(
                    UpdateFilter(addresses=set([address]), reason=UpdateFilterReason.GetUnusedCategoryAddress)
                )

        do_copy(address, title=self.tr("Address {address}").format(address=address))
        self.select_row_by_key(address, scroll_to_last=True)
        return address_info

    def set_filter_change(self, state: int) -> None:
        """Set filter change."""
        if state == self.current_change_filter:
            return

        self.current_change_filter = AddressTypeFilter(state)
        self.update_base_hidden_rows()
        self.filter()

    def set_filter_used(self, state: int) -> None:
        """Set filter used."""
        if state == self.current_used_filter:
            return
        self.current_used_filter = AddressUsageStateFilter(state)
        self.update_base_hidden_rows()
        self.filter()

    def set_filter_category(self, category_info: CategoryInfo | None) -> None:
        """Set filter category."""
        if (category_info is None and self.current_category_filter is None) or (
            category_info and category_info.category == self.current_category_filter
        ):
            return
        self.current_category_filter = category_info.category if category_info else None
        self.update_base_hidden_rows()
        self.filter()

    def update_base_hidden_rows(self):
        """Update base hidden rows."""
        self.base_hidden_rows.clear()

        hidden_rows_type = set()
        hidden_rows_used = set()
        hidden_rows_category = set()

        for row in range(self._source_model.rowCount()):
            address = self._source_model.data(self._source_model.index(row, self.Columns.ADDRESS))
            if not (wallet := self.get_wallet(row)):
                continue

            if self.current_change_filter == AddressTypeFilter.RECEIVING and not wallet.is_receive(address):
                hidden_rows_type.add(row)
            elif self.current_change_filter == AddressTypeFilter.CHANGE and not wallet.is_change(address):
                hidden_rows_type.add(row)

            balance = wallet.get_addr_balance(address).total
            is_used = wallet.address_is_used(address)
            is_used_and_empty = is_used and balance == 0
            if self.current_used_filter == AddressUsageStateFilter.UNUSED and is_used:
                hidden_rows_used.add(row)
            if self.current_used_filter == AddressUsageStateFilter.FUNDED and (balance == 0):
                hidden_rows_used.add(row)
            if self.current_used_filter == AddressUsageStateFilter.USED_AND_EMPTY and not is_used_and_empty:
                hidden_rows_used.add(row)
            if self.current_used_filter == AddressUsageStateFilter.FUNDED_OR_UNUSED and (
                (balance == 0) and is_used
            ):
                hidden_rows_used.add(row)

            if (
                self.current_category_filter
                and wallet.labels.get_category(address) != self.current_category_filter
            ):
                hidden_rows_category.add(row)

        self.base_hidden_rows.update(hidden_rows_type)
        self.base_hidden_rows.update(hidden_rows_used)
        self.base_hidden_rows.update(hidden_rows_category)

    def on_update_fx_rates(self):
        """On update fx rates."""
        addresses_with_balance = []

        model = self._source_model
        for row in range(model.rowCount()):
            address = model.data(model.index(row, self.Columns.ADDRESS))
            balance = model.data(
                model.index(row, self.Columns.COIN_BALANCE), role=MyItemDataRole.ROLE_CLIPBOARD_DATA
            )
            if balance:
                addresses_with_balance.append(address)

        update_filter = UpdateFilter(addresses=addresses_with_balance, reason=UpdateFilterReason.NewFxRates)
        self.update_with_filter(update_filter)

    @time_logger
    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        """Update with filter."""
        if update_filter.refresh_all:
            return self.update_content()
        logger.debug(f"{self.__class__.__name__}  update_with_filter")

        self._before_update_content()
        remaining_addresses = set(update_filter.addresses)

        model = self._source_model
        log_info = []
        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            address = model.data(model.index(row, self.Columns.ADDRESS))
            address_match = address in update_filter.addresses
            category_match = model.data(model.index(row, self.Columns.CATEGORY)) in update_filter.categories
            if (
                (
                    update_filter.reason == UpdateFilterReason.ChainHeightAdvanced
                    and model.data(
                        model.index(row, self.key_column), role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG
                    )
                )
                or address_match
                or (not update_filter.addresses and category_match or len(update_filter.categories) > 1)
            ):
                log_info.append((row, str(address)[:6]))  # no sensitive info in log
                self.refresh_row(address, row)
                remaining_addresses = remaining_addresses - set([address])

        # get_maximum_index
        # address_infos_min = max([wallet.get_address_info_min( address) for address in remaining_addresses ])
        # max_index =

        # sometimes additional addresses are updated,
        # i can add them here without recreating the whole model
        if remaining_addresses:
            for wallet in self.wallets.values():
                for address in set(wallet.get_addresses()).intersection(remaining_addresses):
                    log_info.append((0, str(address)[:6]))  # no sensitive info in log
                    self.append_address(wallet=wallet, address=address)
                    remaining_addresses = remaining_addresses - set([address])

        logger.debug(f"Updated addresses  {log_info}.  {len(remaining_addresses)=}")
        self._after_update_content()

    def get_headers(self) -> dict[MyTreeView.BaseColumnsEnum, QStandardItem]:
        """Get headers."""
        currency_symbol = self.fx.get_currency_symbol()
        return {
            self.Columns.NUM_TXS: header_item(self.tr("Tx"), tooltip=self.tr("Number of transactions")),
            self.Columns.WALLET_ID: header_item(self.tr("Wallet")),
            self.Columns.TYPE: header_item(self.tr("Type")),
            self.Columns.INDEX: header_item(self.tr("Index")),
            self.Columns.ADDRESS: header_item(self.tr("Address")),
            self.Columns.CATEGORY: header_item(self.tr("Category")),
            self.Columns.LABEL: header_item(self.tr("Label")),
            self.Columns.COIN_BALANCE: header_item(self.tr("Balance")),
            self.Columns.FIAT_BALANCE: header_item(currency_symbol + " " + self.tr("Value")),
        }

    def update_content(self) -> None:
        """Update content."""
        if self.maybe_defer_update():
            return
        logger.debug(f"{self.__class__.__name__} update")
        self._before_update_content()

        self._source_model.clear()
        self.update_headers(self.get_headers())
        for wallet in self.wallets.values():
            for address in wallet.get_addresses():
                self.append_address(wallet, address)

        self.update_base_hidden_rows()
        self._after_update_content()
        super().update_content()

    def append_address(self, wallet: Wallet, address: str) -> None:
        """Append address."""
        labels = [""] * len(self.Columns)
        labels[self.Columns.ADDRESS] = address
        item = [QStandardItem(e) for e in labels]
        item[self.Columns.ADDRESS].setData(address, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        # align text and set fonts
        # for i, item in enumerate(item):
        #     item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter)
        #     if i in (self.Columns.ADDRESS,):
        #         item.setFont(QFont(MONOSPACE_FONT))
        self.set_editability(item)
        # setup column 0

        address_info_min = wallet.get_address_info_min(address)
        if address_info_min:
            sort_tuple = (address_info_min.address_path()[0], -address_info_min.address_path()[1])
            item[self.Columns.WALLET_ID].setText(wallet.id)
            item[self.Columns.WALLET_ID].setData(wallet.id, MyItemDataRole.ROLE_CLIPBOARD_DATA)
            item[self.Columns.INDEX].setText(str(address_info_min.index))
            item[self.Columns.INDEX].setData(address_info_min.index, MyItemDataRole.ROLE_CLIPBOARD_DATA)
            item[self.Columns.INDEX].setData(sort_tuple, MyItemDataRole.ROLE_SORT_ORDER)
            if address_info_min.is_change():
                item[self.Columns.TYPE].setText(self.tr("change"))
                item[self.Columns.TYPE].setData(self.tr("change"), MyItemDataRole.ROLE_CLIPBOARD_DATA)
                item[self.Columns.TYPE].setBackground(ColorScheme.YELLOW.as_color(True))
            else:
                item[self.Columns.TYPE].setText(self.tr("receiving"))
                item[self.Columns.TYPE].setData(self.tr("receiving"), MyItemDataRole.ROLE_CLIPBOARD_DATA)
                item[self.Columns.TYPE].setBackground(ColorScheme.GREEN.as_color(True))
            item[self.key_column].setData(address, MyItemDataRole.ROLE_KEY)
            item[self.Columns.TYPE].setData(
                sort_tuple,
                MyItemDataRole.ROLE_SORT_ORDER,
            )
            item[self.Columns.TYPE].setToolTip(
                f"""{address_info_min.address_path()[1]}. {self.tr("change address") if address_info_min.address_path()[0] else self.tr("receiving address")}"""
            )
        # add item
        count = self._source_model.rowCount()
        self._source_model.insertRow(count, item)
        self.refresh_row(address, count)

    def refresh_row(self, key: str, row: int) -> None:
        """Refresh row."""
        assert row is not None
        address = key
        wallet = self.get_wallet(row)
        if not wallet:
            return

        label = wallet.get_label_for_address(address)
        category = wallet.labels.get_category(address)

        txids = wallet.get_involved_txids(address)
        fulltxdetails = [wallet.get_dict_fulltxdetail().get(txid) for txid in txids]
        txs_involed = [fulltxdetail.tx for fulltxdetail in fulltxdetails if fulltxdetail]

        statuses = [TxStatus.from_wallet(tx.txid, wallet) for tx in txs_involed]
        min_status = sorted(statuses, key=lambda status: status.sort_id())[0] if statuses else None
        icon_path = sort_id_to_icon(min_status.sort_id()) if min_status else None
        num = len(txs_involed)

        balance = wallet.get_addr_balance(address).total
        balance_text = str(Satoshis(balance, wallet.network))
        # create item

        fiat_value = self.fx.btc_to_fiat(balance)
        fiat_balance_str = (
            self.fx.fiat_to_str(fiat_value, use_currency_symbol=False) if fiat_value is not None else ""
        )
        _item = [self._source_model.item(row, col) for col in self.Columns]
        items = [entry for entry in _item if entry]
        items[self.key_column].setData(
            needs_frequent_flag(status=min_status), role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG
        )
        items[self.Columns.LABEL].setText(label)
        items[self.Columns.LABEL].setData(label, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        items[self.Columns.CATEGORY].setText(category if category else "")
        items[self.Columns.CATEGORY].setData(category, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        items[self.Columns.CATEGORY].setBackground(category_color(category))
        items[self.Columns.COIN_BALANCE].setText(balance_text)
        color = (
            self.palette().color(self.foregroundRole()) if balance else QColor(255 // 2, 255 // 2, 255 // 2)
        )
        items[self.Columns.COIN_BALANCE].setForeground(QBrush(color))
        items[self.Columns.COIN_BALANCE].setData(balance, MyItemDataRole.ROLE_SORT_ORDER)
        items[self.Columns.COIN_BALANCE].setData(balance, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        items[self.Columns.FIAT_BALANCE].setText(fiat_balance_str)
        items[self.Columns.FIAT_BALANCE].setForeground(QBrush(color))
        items[self.Columns.FIAT_BALANCE].setData(fiat_value, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        items[self.Columns.FIAT_BALANCE].setData(fiat_value, MyItemDataRole.ROLE_SORT_ORDER)
        # item[self.Columns.NUM_TXS].setText("%d" % num)
        items[self.Columns.NUM_TXS].setToolTip(f"{num} Transaction")
        items[self.Columns.NUM_TXS].setData(num, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        items[self.Columns.NUM_TXS].setData(
            min_status.sort_id() if min_status else -1, MyItemDataRole.ROLE_SORT_ORDER
        )
        items[self.Columns.NUM_TXS].setIcon(svg_tools.get_QIcon(icon_path))

        # calculated_width = QFontMetrics(self.font()).horizontalAdvance(balance_text)
        # current_width = self.header().sectionSize(self.Columns.ADDRESS)
        # # Update the column width if the calculated width is larger
        # if calculated_width > current_width:
        #     self.header().resizeSection(self.Columns.ADDRESS, calculated_width)

    def create_menu(self, position: QPoint) -> Menu:
        """Create menu."""
        menu = Menu()
        # is_multisig = isinstance(wallet, Multisig_Wallet)
        selected = self.selected_in_column(self.Columns.ADDRESS)
        selected_items = [item for idx in selected if (item := self.item_from_index(idx))]
        if not selected_items:
            return menu
        multi_select = len(selected_items) > 1
        addrs = [item.text() for item in selected_items]
        if not multi_select:
            addr = addrs[0]

            wallet = self.get_wallet(selected_items[0].index().row())
            if wallet and (wallet_signals := self.wallet_functions.wallet_signals.get(wallet.id)):
                menu.add_action(
                    self.tr("Details"), partial(wallet_signals.show_address.emit, addr, wallet.id)
                )

            addr_URL = block_explorer_URL(self.config.network_config.mempool_url, "addr", addr)
            if addr_URL:
                menu.add_action(
                    self.tr("View on block explorer"),
                    partial(webopen, addr_URL),
                    icon=svg_tools.get_QIcon("block-explorer.svg"),
                )

        menu.add_action(
            self.tr("Select corresponding UTXOs for sending"),
            partial(self._select_utxos_for_sending, self._group_addresses_by_wallet(selected_items)),
        )

        menu.addSeparator()
        self._add_category_menu(menu, addrs)

        menu.addSeparator()
        if selected and not multi_select:
            self.add_copy_menu(menu, selected[0], include_columns_even_if_hidden=[self.key_column])

        address_list = [item.data(MySortModel.role_drag_key) for item in selected_items if item]
        menu.add_action(
            self.tr("Copy Addresses"),
            partial(
                do_copy,
                "\n".join(address_list),
                title=self.tr("{n} addresses have ben copied").format(n=len(address_list)),
            ),
            icon=svg_tools.get_QIcon("bi--filetype-csv.svg"),
        )

        menu.add_action(
            self.tr("Copy as csv"),
            partial(
                self.copyRowsToClipboardAsCSV,
                address_list,
            ),
            icon=svg_tools.get_QIcon("bi--filetype-csv.svg"),
        )

        menu.addSeparator()
        self._context_menu_import_export = self.recreate_export_import_menu(menu)

        # run_hook('receive_menu', menu, addrs, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    def recreate_export_import_menu(self, menu: QMenu, position: int | None = None) -> list[QMenu]:
        # 1) Remove any old export/import sub‑menus
        """Recreate export import menu."""
        for action in list(menu.actions()):
            sub = action.menu()
            if isinstance(sub, (ExportLabelMenu, ImportLabelMenu)):
                menu.removeAction(action)

        # 2) Build the fresh list of sub‑menus
        new_menus: list[QMenu] = []
        for wallet_id in self.wallets.keys():
            wallet_signals = self.wallet_functions.wallet_signals.get(wallet_id)
            if not wallet_signals:
                continue
            export_menu = ExportLabelMenu(wallet_signals=wallet_signals)
            import_menu = ImportLabelMenu(wallet_signals=wallet_signals)
            new_menus += [export_menu, import_menu]

        # 3) Insert (or append) the new menus in one place
        existing_actions = menu.actions()
        if position is None:
            position = len(existing_actions)
        if 0 <= position < len(existing_actions):
            # If inserting in the middle, insert each submenu BEFORE the same anchor action,
            # iterating in reverse so they end up in the correct order.
            anchor = existing_actions[position]
            for submenu in reversed(new_menus):
                menu.insertMenu(anchor, submenu)
        else:
            # Otherwise just append them at the end
            for submenu in new_menus:
                menu.addMenu(submenu)

        return new_menus

    def _add_category_menu(self, menu: Menu, addresses: list[str]):
        """Add category menu."""
        category_menu = menu.add_menu(self.tr("Set category"))

        categories = sum([wallet.labels.categories for wallet in self.wallets.values()], [])

        for category in categories:
            # When the user selects the action, emit the drop signal with the category and address.
            action = partial(self.signal_tag_dropped.emit, AddressDragInfo([category], addresses))
            category_menu.add_action(
                category,
                action,
                icon=create_color_circle(category_color(category)),
            )

        return menu

    def _group_addresses_by_wallet(self, items: list[QStandardItem]) -> dict[str, list[str]]:
        """Return selected addresses grouped by wallet id."""
        grouped: dict[str, list[str]] = {}
        for item in items:
            wallet = self.get_wallet(item.index().row())
            if not wallet:
                continue
            grouped.setdefault(wallet.id, []).append(item.text())
        return grouped

    def _utxos_for_addresses(self, wallet: Wallet, addresses: list[str]) -> list[PythonUtxo]:
        """Return spendable UTXOs that belong to the given addresses."""
        wanted = set(addresses)
        return [utxo for utxo in wallet.get_all_utxos() if utxo.address in wanted]

    def _select_utxos_for_sending(self, group_addresses_by_walletdict: dict[str, list[str]]) -> None:
        """Open the send tab with UTXOs of the selected addresses pre‑selected."""
        if not group_addresses_by_walletdict:
            return

        if len(group_addresses_by_walletdict) > 1:
            Message(
                self.tr("Please select addresses from a single wallet to choose UTXOs for sending."),
                type=MessageType.Info,
                parent=self,
            )
            return

        wallet_id, addresses = next(iter(group_addresses_by_walletdict.items()))
        wallet = self.wallets.get(wallet_id)
        if not wallet:
            return

        utxos = self._utxos_for_addresses(wallet, addresses)
        if not utxos:
            Message(
                self.tr("No spendable UTXOs found for the selected addresses."),
                type=MessageType.Info,
                parent=self,
            )
            return

        tx_ui_infos = TxUiInfos(
            utxo_dict={utxo.outpoint: utxo for utxo in utxos},
            hide_UTXO_selection=False,
            main_wallet_id=wallet.id,
        )
        tx_ui_infos.spend_all_utxos = True
        self.wallet_functions.signals.open_tx_like.emit(tx_ui_infos)

    def get_edit_key_from_coordinate(self, row, col) -> Any:
        """Get edit key from coordinate."""
        if col != self.Columns.LABEL:
            return None
        return self.get_role_data_from_coordinate(row, self.key_column, role=MyItemDataRole.ROLE_KEY)

    def on_edited(self, source_idx: QModelIndex, edit_key: str, text: str) -> None:
        """On edited."""
        wallet = self.get_wallet(source_idx.row())
        if not wallet:
            return
        wallet.labels.set_addr_label(edit_key, text, timestamp="now")
        categories = []
        if not wallet.labels.get_category_raw(edit_key):
            # also fix the category to have consitency across wallets via the labelsyncer
            category = wallet.labels.get_category(edit_key)
            categories += [category]
            wallet.labels.set_addr_category(edit_key, category, timestamp="now")

        if wallet_signals := self.wallet_functions.wallet_signals.get(wallet.id):
            wallet_signals.updated.emit(
                UpdateFilter(
                    addresses=[edit_key],
                    categories=categories,
                    txids=wallet.get_involved_txids(edit_key),
                    reason=UpdateFilterReason.UserInput,
                )
            )

    def close(self) -> bool:
        """Close."""
        self.setParent(None)
        self._signal_tracker_wallet_signals.disconnect_all()
        return super().close()


class AddressListWithToolbar(TreeViewWithToolbar):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        AddressList.__name__: AddressList,
    }

    @staticmethod
    def cls_kwargs(
        config: UserConfig,
    ):
        return {
            "config": config,
        }

    def __init__(
        self,
        address_list: AddressList,
        config: UserConfig,
        category_core: CategoryCore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(address_list, config, toolbar_is_visible=True, parent=parent)
        self.default_export_csv_filename = (
            f"category_export_{','.join([wallet_id for wallet_id in address_list.wallets.keys()])}.csv"
        )
        self.category_core = category_core
        self.address_list: AddressList = address_list
        self.change_button = QComboBox(self)
        self.change_button.currentIndexChanged.connect(self.address_list.set_filter_change)
        for addr_type in AddressTypeFilter:
            self.change_button.addItem(addr_type.ui_text(), addr_type)

        self.used_button = QComboBox(self)
        self.used_button.currentIndexChanged.connect(self.address_list.set_filter_used)
        for addr_usage_state in AddressUsageStateFilter:
            self.used_button.addItem(addr_usage_state.ui_text(), addr_usage_state)

        self.button_create_address = QPushButton()
        self.button_create_address.setIcon(svg_tools.get_QIcon("bi--plus-lg.svg"))
        self.button_create_address.clicked.connect(self.on_create_address)
        self.button_create_address_label = QLabel()

        self.category_combobox = CategoryComboBox(category_core=self.category_core)
        self.snapshot_menu: LabelSnapshotMenu | None = None

        self.create_layout()
        self.updateUi()

        self.address_list.signals.language_switch.connect(self.updateUi)
        self.address_list.signals.any_wallet_updated.connect(self.update_with_filter)
        self.category_combobox.currentIndexChanged.connect(self.on_change_category_menu)

    def set_category_core(self, category_core: CategoryCore | None):
        """Set category core."""
        self.category_core = category_core
        self.category_combobox.set_category_core(category_core=category_core)
        self._menu_import_export = self.address_list.recreate_export_import_menu(self.menu)

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["address_list"] = self.address_list
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> AddressListWithToolbar:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def on_create_address(self, wallet_id: str | None = None):
        """On create address."""
        if not self.category_core:
            return
        category = self.category_combobox.currentText()
        if category not in self.category_core.wallet.labels.categories:
            return

        wallet_id = list(self.address_list.wallets.keys())[0] if self.address_list.wallets else None
        wallet = self.address_list.wallets.get(wallet_id) if wallet_id else None
        if not wallet:
            return

        self.address_list.get_address(force_new=True, category=category, wallet=wallet)

    def on_change_category_menu(self, index: int):
        """On change category menu."""
        if index < 0:
            return
        data = self.category_combobox.itemData(index)
        if data is None or isinstance(data, CategoryInfo):
            self.address_list.set_filter_category(data)
            self.set_visibilities()

    def set_visibilities(self):
        """Set visibilities."""
        if not self.category_core:
            return

        self.button_create_address.setEnabled(
            self.category_combobox.currentText() in self.category_core.wallet.labels.categories
        )

    def update_with_filter(self, update_filter: UpdateFilter):
        """Update with filter."""
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()

        self.set_visibilities()

        for action in list(self.menu.actions()):
            sub = action.menu()
            if isinstance(sub, (ExportLabelMenu, ImportLabelMenu, LabelSnapshotMenu)):
                sub.updateUi()

        self.button_create_address.setText(self.tr("Create new address"))
        self.button_create_address_label.setText(self.tr("for"))
        self.action_manage_categories.setText(self.tr("Manage Categories"))
        if self.snapshot_menu:
            self.snapshot_menu.updateUi()

        if self.balance_label:
            balance = Balance()
            for wallet in self.address_list.wallets.values():
                balance += wallet.get_balance()
            self.balance_label.setText(
                balance.format_short(self.config.network, btc_symbol=self.config.bitcoin_symbol.value)
            )
            self.balance_label.setToolTip(
                balance.format_long(self.config.network, btc_symbol=self.config.bitcoin_symbol.value)
            )

    def _mine_to_selected_addresses(self) -> None:
        """Mine to selected addresses."""
        selected = self.address_list.selected_in_column(self.address_list.Columns.ADDRESS)
        if not selected:
            return
        selected_items = [self.address_list.item_from_index(item) for item in selected]
        addresses = [item.text() for item in selected_items if item]

        for address in addresses:
            response = send_rpc_command(
                self.config.network_config.rpc_ip,
                str(self.config.network_config.rpc_port),
                self.config.network_config.rpc_username,
                self.config.network_config.rpc_password,
                "generatetoaddress",
                params=[1, address],
            )
            logger.info(f"{response}")
        self.address_list.signals.chain_data_changed.emit(f"Mined to addresses {addresses}")

    def create_toolbar_with_menu(self, title) -> None:
        """Create toolbar with menu."""
        super().create_toolbar_with_menu(title=title)

        font = QFont()
        font.setPointSize(12)
        self.balance_label.setFont(font)

        self.menu.addSeparator()
        self.action_manage_categories = self.menu.add_action(
            "",
        )

        self.menu.addSeparator()
        self._menu_import_export = self.address_list.recreate_export_import_menu(self.menu)

        self.snapshot_menu = LabelSnapshotMenu(
            self.address_list.wallets,
            wallet_functions=self.address_list.wallet_functions,
            parent=self.menu,
        )
        self.menu.addMenu(self.snapshot_menu)

        if (
            self.config
            and self.config.network_config.server_type == BlockchainType.RPC
            and self.config.network != bdk.Network.BITCOIN
        ):
            b = QPushButton(self.tr("Generate to selected adddresses"))
            b.clicked.connect(self._mine_to_selected_addresses)
            self.toolbar.insertWidget(self.toolbar.count() - 2, b)

        hbox = self.create_toolbar_buttons()
        self.toolbar.insertLayout(self.toolbar.count() - 1, hbox)

        # category
        self.toolbar.insertWidget(0, self.button_create_address)
        self.toolbar.insertWidget(1, self.button_create_address_label)
        self.toolbar.insertWidget(2, self.category_combobox)

    def create_toolbar_buttons(self) -> QHBoxLayout:
        """Create toolbar buttons."""
        hbox = QHBoxLayout()
        buttons = [self.change_button, self.used_button]
        for b in buttons:
            b.setVisible(True)
            hbox.addWidget(b)
        self.toolbar_buttons = buttons
        return hbox

    def on_hide_toolbar(self) -> None:
        """On hide toolbar."""
        self.update()

    def show_toolbar(self, is_visible: bool, config=None) -> None:
        """Show toolbar."""
        super().show_toolbar(is_visible=is_visible, config=config)
        for b in self.toolbar_buttons:
            b.setVisible(is_visible)
