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
from typing import Any, Dict, Tuple

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.wrappers import Menu

from ...config import UserConfig
from ...network_config import BlockchainType

logger = logging.getLogger(__name__)


import enum
from enum import IntEnum

import bdkpython as bdk
from PyQt6.QtCore import QModelIndex, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QStandardItem,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from ...i18n import translate
from ...rpc import send_rpc_command
from ...signals import Signals, UpdateFilter, UpdateFilterReason, WalletSignals
from ...util import Satoshis, block_explorer_URL, time_logger
from ...wallet import TxStatus, Wallet
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
from .util import ColorScheme, Message, do_copy, read_QIcon, sort_id_to_icon, webopen


class ImportLabelMenu:
    def __init__(self, upper_menu: Menu, wallet: Wallet, wallet_signals: WalletSignals) -> None:
        self.wallet_signals = wallet_signals
        self.wallet = wallet
        self.import_label_menu = upper_menu.add_menu(
            "",
        )

        self.action_import = self.import_label_menu.add_action(
            "",
            lambda: self.wallet_signals.import_labels.emit(self.wallet.id),
        )
        self.action_bip329_import = self.import_label_menu.add_action(
            "",
            lambda: self.wallet_signals.import_bip329_labels.emit(self.wallet.id),
        )
        self.action_electrum_import = self.import_label_menu.add_action(
            "",
            lambda: self.wallet_signals.import_electrum_wallet_labels.emit(self.wallet.id),
        )
        self.action_nostr_import = self.import_label_menu.add_action(
            "",
            self.import_nostr_labels,
            icon=read_QIcon("cloud-sync.svg"),
        )
        self.updateUi()

    def import_nostr_labels(self):
        Message(
            translate(
                "import",
                "Please go to the Sync Tab and import your Sync key there. The labels will then be automatically restored.",
            )
        )

    def updateUi(self) -> None:
        self.import_label_menu.setTitle(translate("menu", "Import Labels"))
        self.action_import.setText(translate("menu", "Import Labels"))
        self.action_bip329_import.setText(translate("menu", "Import Labels (BIP329 / Sparrow)"))
        self.action_electrum_import.setText(translate("menu", "Import Labels (Electrum Wallet)"))
        self.action_nostr_import.setText(
            translate("menu", "Restore labels from cloud using an existing sync key")
        )


class ExportLabelMenu:
    def __init__(self, upper_menu: Menu, wallet: Wallet, wallet_signals: WalletSignals) -> None:
        self.wallet_signals = wallet_signals
        self.wallet = wallet
        self.export_label_menu = upper_menu.add_menu(
            "",
        )

        self.action_export_full = self.export_label_menu.add_action(
            "",
            lambda: self.wallet_signals.export_labels.emit(self.wallet.id),
        )
        self.action_bip329 = self.export_label_menu.add_action(
            "",
            lambda: self.wallet_signals.export_bip329_labels.emit(self.wallet.id),
        )
        self.updateUi()

    def updateUi(self) -> None:
        self.export_label_menu.setTitle(translate("menu", "Export Labels"))
        self.action_export_full.setText(translate("export", "Export Labels"))
        self.action_bip329.setText(translate("export", "Export Labels for other wallets (BIP329)"))


class AddressUsageStateFilter(IntEnum):
    ALL = 0
    UNUSED = 1
    FUNDED = 2
    USED_AND_EMPTY = 3
    FUNDED_OR_UNUSED = 4

    def ui_text(self) -> str:
        return {
            self.ALL: translate("address_list", "All status"),
            self.UNUSED: translate("address_list", "Unused"),
            self.FUNDED: translate("address_list", "Funded"),
            self.USED_AND_EMPTY: translate("address_list", "Used"),
            self.FUNDED_OR_UNUSED: translate("address_list", "Funded or Unused"),
        }[self]


class AddressTypeFilter(IntEnum):
    ALL = 0
    RECEIVING = 1
    CHANGE = 2

    def ui_text(self) -> str:
        return {
            self.ALL: translate("address_list", "All types"),
            self.RECEIVING: translate("address_list", "Receiving"),
            self.CHANGE: translate("address_list", "Change"),
        }[self]


class AddressList(MyTreeView):
    signal_tag_dropped = pyqtSignal(AddressDragInfo)

    class Columns(MyTreeView.BaseColumnsEnum):
        NUM_TXS = enum.auto()
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
        Columns.TYPE: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.ADDRESS: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.CATEGORY: Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        Columns.LABEL: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.COIN_BALANCE: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        Columns.NUM_TXS: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        Columns.FIAT_BALANCE: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    }

    hidden_columns = [Columns.INDEX]

    stretch_column = Columns.LABEL
    key_column = Columns.ADDRESS
    column_widths: Dict[MyTreeView.BaseColumnsEnum, int] = {Columns.ADDRESS: 150, Columns.COIN_BALANCE: 100}

    def __init__(
        self,
        fx: FX,
        config: UserConfig,
        wallet: Wallet,
        wallet_signals: WalletSignals,
        signals: Signals,
    ) -> None:
        super().__init__(
            config=config,
            signals=signals,
            stretch_column=self.stretch_column,
            column_widths=self.column_widths,
            editable_columns=[AddressList.Columns.LABEL],
            sort_column=AddressList.Columns.COIN_BALANCE,
            sort_order=Qt.SortOrder.DescendingOrder,
        )
        self.fx = fx
        self.wallet_signals = wallet_signals
        self.wallet = wallet
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        self._source_model = MyStandardItemModel(self, drag_key="addresses")
        self.proxy = MySortModel(
            self, source_model=self._source_model, sort_role=MyItemDataRole.ROLE_SORT_ORDER
        )
        self.setModel(self.proxy)
        self.setSortingEnabled(True)  # Allow user to sort by clicking column headers
        self.updateUi()

        # signals
        self.wallet_signals.updated.connect(self.update_with_filter)
        self.wallet_signals.language_switch.connect(self.updateUi)
        self.fx.signal_data_updated.connect(self.on_update_fx_rates)

    def updateUi(self) -> None:
        self.update_content()

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        super().dragEnterEvent(event)
        if not event or event.isAccepted():
            return

        if (mime_data := event.mimeData()) and self.get_json_mime_data(mime_data) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent | None) -> None:
        super().dragMoveEvent(event)
        if not event:
            return
        if event.isAccepted():
            return

        if (mime_data := event.mimeData()) and (
            json_mime_data := self.get_json_mime_data(mime_data)
        ) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        # handle dropped files
        super().dropEvent(event)
        if event.isAccepted():
            return

        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            # Handle the case where the drop is not on a valid index
            return

        if (mime_data := event.mimeData()) and (
            json_mime_data := self.get_json_mime_data(mime_data)
        ) is not None:
            model = self.model()
            hit_address = model.data(model.index(index.row(), self.Columns.ADDRESS))
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
        addr = self.get_role_data_for_current_item(col=self.key_column, role=MyItemDataRole.ROLE_KEY)
        self.wallet_signals.show_address.emit(addr, self.wallet.id)

    def get_address(self, force_new=False, category: str | None = None) -> bdk.AddressInfo:
        if force_new:
            address_info = self.wallet.get_address(force_new=force_new)
            address = address_info.address.as_string()
            self.wallet.labels.set_addr_category(address, category, timestamp="now")
            self.wallet_signals.updated.emit(
                UpdateFilter(addresses=set([address]), reason=UpdateFilterReason.NewAddressRevealed)
            )
        else:
            address_info = self.wallet.get_unused_category_address(category)
            address = address_info.address.as_string()

            if self.signals:
                self.signals.wallet_signals[self.wallet.id].updated.emit(
                    UpdateFilter(addresses=set([address]), reason=UpdateFilterReason.GetUnusedCategoryAddress)
                )

        do_copy(address, title=self.tr("Address {address}").format(address=address))
        self.select_row(address, self.Columns.ADDRESS)
        return address_info

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

    def on_update_fx_rates(self):
        addresses_with_balance = []

        model = self.sourceModel()
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
        if update_filter.refresh_all:
            return self.update_content()
        logger.debug(f"{self.__class__.__name__}  update_with_filter {update_filter}")

        self._before_update_content()
        remaining_addresses = set(update_filter.addresses)

        model = self.sourceModel()
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
                log_info.append((row, address))
                self.refresh_row(address, row)
                remaining_addresses = remaining_addresses - set([address])

        # get_maximum_index
        # address_infos_min = max([self.wallet.get_address_info_min( address) for address in remaining_addresses ])
        # max_index =

        # sometimes additional addresses are updated,
        # i can add them here without recreating the whole model
        if remaining_addresses:
            for address in set(self.wallet.get_addresses()).intersection(remaining_addresses):
                log_info.append((0, address))
                self.append_address(address)
                remaining_addresses = remaining_addresses - set([address])

        logger.debug(f"Updated addresses  {log_info}.  remaining_addresses = {remaining_addresses}")
        self._after_update_content()

    def get_headers(self) -> Dict:
        return {
            self.Columns.NUM_TXS: self.tr("Tx"),
            self.Columns.TYPE: self.tr("Type"),
            self.Columns.INDEX: self.tr("Index"),
            self.Columns.ADDRESS: self.tr("Address"),
            self.Columns.CATEGORY: self.tr("Category"),
            self.Columns.LABEL: self.tr("Label"),
            self.Columns.COIN_BALANCE: self.tr("Balance"),
            self.Columns.FIAT_BALANCE: "$ " + self.tr("Balance"),
        }

    def update_content(self) -> None:
        if self.maybe_defer_update():
            return
        logger.debug(f"{self.__class__.__name__} update")
        self._before_update_content()

        current_selected_key = self.get_role_data_for_current_item(
            col=self.key_column, role=MyItemDataRole.ROLE_KEY
        )
        if self.show_change == AddressTypeFilter.RECEIVING:
            addr_list = self.wallet.get_receiving_addresses()
        elif self.show_change == AddressTypeFilter.CHANGE:
            addr_list = self.wallet.get_change_addresses()
        else:
            addr_list = self.wallet.get_addresses()
        self._source_model.clear()
        self.update_headers(self.get_headers())
        for address in addr_list:
            self.append_address(address)

        self._after_update_content()
        super().update_content()

    def append_address(self, address: str) -> None:
        balance = self.wallet.get_addr_balance(address).total
        is_used_and_empty = self.wallet.address_is_used(address) and balance == 0
        if self.show_used == AddressUsageStateFilter.UNUSED and (balance or is_used_and_empty):
            return
        if self.show_used == AddressUsageStateFilter.FUNDED and balance == 0:
            return
        if self.show_used == AddressUsageStateFilter.USED_AND_EMPTY and not is_used_and_empty:
            return
        if self.show_used == AddressUsageStateFilter.FUNDED_OR_UNUSED and is_used_and_empty:
            return
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

        address_info_min = self.wallet.get_address_info_min(address)
        if address_info_min:
            item[self.Columns.INDEX].setData(address_info_min.index, MyItemDataRole.ROLE_CLIPBOARD_DATA)
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
                (address_info_min.address_path()[0], -address_info_min.address_path()[1]),
                MyItemDataRole.ROLE_SORT_ORDER,
            )
            item[self.Columns.TYPE].setToolTip(
                f"""{address_info_min.address_path()[1]}. {self.tr("change address") if address_info_min.address_path()[0] else   self.tr('receiving address')}"""
            )
        # add item
        count = self._source_model.rowCount()
        self._source_model.insertRow(count, item)
        self.refresh_row(address, count)

    def refresh_row(self, key: str, row: int) -> None:
        assert row is not None
        address = key
        label = self.wallet.get_label_for_address(address)
        category = self.wallet.labels.get_category(address)

        txids = self.wallet.get_involved_txids(address)
        fulltxdetails = [self.wallet.get_dict_fulltxdetail().get(txid) for txid in txids]
        txs_involed = [fulltxdetail.tx for fulltxdetail in fulltxdetails if fulltxdetail]

        statuses = [TxStatus.from_wallet(tx.txid, self.wallet) for tx in txs_involed]
        min_status = sorted(statuses, key=lambda status: status.sort_id())[0] if statuses else None
        icon_path = sort_id_to_icon(min_status.sort_id()) if min_status else None
        num = len(txs_involed)

        balance = self.wallet.get_addr_balance(address).total
        balance_text = str(Satoshis(balance, self.wallet.network))
        # create item

        dollar_amount = self.fx.to_fiat("usd", balance)
        fiat_balance_str = (
            self.fx.format_dollar(dollar_amount, prepend_dollar_sign=False)
            if dollar_amount is not None
            else ""
        )
        fiat_balance_data = (
            self.fx.format_dollar(dollar_amount, prepend_dollar_sign=False)
            if dollar_amount is not None
            else ""
        )
        _item = [self._source_model.item(row, col) for col in self.Columns]
        item = [entry for entry in _item if entry]
        if needs_frequent_flag(status=min_status):
            item[self.key_column].setData(True, role=MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG)
        item[self.Columns.LABEL].setText(label)
        item[self.Columns.LABEL].setData(label, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORY].setText(category if category else "")
        item[self.Columns.CATEGORY].setData(category, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORY].setBackground(CategoryEditor.color(category))
        item[self.Columns.COIN_BALANCE].setText(balance_text)
        color = QColor(0, 0, 0) if balance else QColor(255 // 2, 255 // 2, 255 // 2)
        item[self.Columns.COIN_BALANCE].setForeground(QBrush(color))
        item[self.Columns.COIN_BALANCE].setData(balance, MyItemDataRole.ROLE_SORT_ORDER)
        item[self.Columns.COIN_BALANCE].setData(balance, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.FIAT_BALANCE].setText(fiat_balance_str)
        item[self.Columns.FIAT_BALANCE].setData(fiat_balance_data, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        # item[self.Columns.NUM_TXS].setText("%d" % num)
        item[self.Columns.NUM_TXS].setToolTip(f"{num} Transaction")
        item[self.Columns.NUM_TXS].setData(num, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        item[self.Columns.NUM_TXS].setIcon(read_QIcon(icon_path))

        # calculated_width = QFontMetrics(self.font()).horizontalAdvance(balance_text)
        # current_width = self.header().sectionSize(self.Columns.ADDRESS)
        # # Update the column width if the calculated width is larger
        # if calculated_width > current_width:
        #     self.header().resizeSection(self.Columns.ADDRESS, calculated_width)

    def create_menu(self, position: QPoint) -> Menu:
        menu = Menu()
        # is_multisig = isinstance(self.wallet, Multisig_Wallet)
        selected = self.selected_in_column(self.Columns.ADDRESS)
        if not selected:
            return menu
        multi_select = len(selected) > 1
        selected_items = [self.item_from_index(item) for item in selected]
        addrs = [item.text() for item in selected_items if item]
        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return menu
            item = self.item_from_index(idx)
            if not item:
                return menu
            addr = addrs[0]
            menu.add_action(
                self.tr("Details"), lambda: self.wallet_signals.show_address.emit(addr, self.wallet.id)
            )

            addr_URL = block_explorer_URL(self.config.network_config.mempool_url, "addr", addr)
            if addr_URL:
                menu.add_action(
                    self.tr("View on block explorer"), lambda: webopen(addr_URL), icon=read_QIcon("link.svg")
                )

            menu.addSeparator()

            self.add_copy_menu(menu, idx, include_columns_even_if_hidden=[self.key_column])

        menu.add_action(
            self.tr("Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
            icon=read_QIcon("csv-file.svg"),
        )
        menu.addSeparator()
        self.export_label_menu = ExportLabelMenu(menu, wallet=self.wallet, wallet_signals=self.wallet_signals)
        self.import_label_menu = ImportLabelMenu(menu, wallet=self.wallet, wallet_signals=self.wallet_signals)

        # run_hook('receive_menu', menu, addrs, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    # def place_text_on_clipboard(self, text: str, *, title: str = None) -> None:
    #     if bdk.Address(text):
    #         try:
    #             self.wallet.check_address_for_corruption(text)
    #         except InternalAddressCorruption as e:
    #             self.show_error(str(e))
    #             raise
    #     super().place_text_on_clipboard(text, title=title)

    def get_edit_key_from_coordinate(self, row, col) -> Any:
        if col != self.Columns.LABEL:
            return None
        return self.get_role_data_from_coordinate(row, self.key_column, role=MyItemDataRole.ROLE_KEY)

    def on_edited(self, idx, edit_key, *, text) -> None:
        self.wallet.labels.set_addr_label(edit_key, text, timestamp="now")
        categories = []
        if not self.wallet.labels.get_category_raw(edit_key):
            # also fix the category to have consitency across wallets via the labelsyncer
            category = self.wallet.labels.get_category(edit_key)
            categories += [category]
            self.wallet.labels.set_addr_category(edit_key, category, timestamp="now")
        self.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=[edit_key],
                categories=categories,
                txids=self.wallet.get_involved_txids(edit_key),
                reason=UpdateFilterReason.UserInput,
            )
        )


class AddressListWithToolbar(TreeViewWithToolbar):
    def __init__(
        self,
        address_list: AddressList,
        config: UserConfig,
        parent: QWidget | None = None,
        signals: Signals | None = None,
    ) -> None:
        super().__init__(address_list, config, parent=parent)
        self.signals = signals
        self.address_list: AddressList = address_list
        self.change_button = QComboBox(self)
        self.change_button.currentIndexChanged.connect(self.address_list.toggle_change)
        for addr_type in AddressTypeFilter.__members__.values():
            self.change_button.addItem(addr_type.ui_text())
        self.used_button = QComboBox(self)
        self.used_button.currentIndexChanged.connect(self.address_list.toggle_used)
        for addr_usage_state in AddressUsageStateFilter.__members__.values():
            self.used_button.addItem(addr_usage_state.ui_text())

        self.create_layout()
        self.updateUi()

        self.address_list.wallet_signals.language_switch.connect(self.updateUi)
        self.address_list.wallet_signals.updated.connect(self.updateUi)

    def updateUi(self) -> None:
        super().updateUi()

        self.action_show_filter.setText(self.tr("Show Filter"))
        self.menu_import_labels.updateUi()
        self.menu_export_labels.updateUi()

        if self.balance_label:
            balance = self.address_list.wallet.get_balance()
            if self.signals:
                display_balance = (
                    self.signals.wallet_signals[self.address_list.wallet.id]
                    .get_display_balance.emit()
                    .get(self.address_list.wallet.id)
                )
                if display_balance:
                    balance = display_balance

            self.balance_label.setText(balance.format_short(self.address_list.wallet.network))
            self.balance_label.setToolTip(balance.format_long(self.address_list.wallet.network))

    def create_toolbar_with_menu(self, title) -> None:
        super().create_toolbar_with_menu(title=title)

        font = QFont()
        font.setPointSize(12)
        self.balance_label.setFont(font)

        self.action_show_filter = self.menu.addToggle("", lambda: self.toggle_toolbar(self.config))
        self.menu_export_labels = ExportLabelMenu(
            self.menu, wallet=self.address_list.wallet, wallet_signals=self.address_list.wallet_signals
        )
        self.menu_import_labels = ImportLabelMenu(
            self.menu, wallet=self.address_list.wallet, wallet_signals=self.address_list.wallet_signals
        )

        if (
            self.config
            and self.config.network_config.server_type == BlockchainType.RPC
            and self.config.network != bdk.Network.BITCOIN
        ):

            def mine_to_selected_addresses() -> None:
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
                if self.signals:
                    self.signals.chain_data_changed.emit(f"Mined to addresses {addresses}")

            b = QPushButton(self.tr("Generate to selected adddresses"))
            b.clicked.connect(mine_to_selected_addresses)
            self.toolbar.insertWidget(self.toolbar.count() - 2, b)

        hbox = self.create_toolbar_buttons()
        self.toolbar.insertLayout(self.toolbar.count() - 1, hbox)

    def create_toolbar_buttons(self) -> QHBoxLayout:
        def get_toolbar_buttons() -> Tuple[QComboBox, QComboBox]:
            return self.change_button, self.used_button

        hbox = QHBoxLayout()
        buttons = get_toolbar_buttons()
        for b in buttons:
            b.setVisible(False)
            hbox.addWidget(b)
        self.toolbar_buttons = buttons
        return hbox

    def on_hide_toolbar(self) -> None:
        self.update()

    def show_toolbar(self, is_visible: bool, config=None) -> None:
        super().show_toolbar(is_visible=is_visible, config=config)
        for b in self.toolbar_buttons:
            b.setVisible(is_visible)
