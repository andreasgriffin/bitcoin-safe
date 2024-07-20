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

from ...config import UserConfig
from ...network_config import BlockchainType

logger = logging.getLogger(__name__)


import enum
import json
from enum import IntEnum

import bdkpython as bdk
from PyQt6.QtCore import QModelIndex, QPersistentModelIndex, QPoint, Qt, pyqtSignal
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
    QMenu,
    QPushButton,
    QWidget,
)

from ...i18n import translate
from ...rpc import send_rpc_command
from ...signals import Signals, UpdateFilter
from ...util import Satoshis, block_explorer_URL
from ...wallet import TxStatus, Wallet
from .category_list import CategoryEditor
from .my_treeview import (
    MySortModel,
    MyStandardItemModel,
    MyTreeView,
    TreeViewWithToolbar,
)
from .taglist import AddressDragInfo
from .util import ColorScheme, do_copy, read_QIcon, sort_id_to_icon, webopen


class ImportMenu:
    def __init__(self, upper_menu: QMenu, wallet: Wallet, signals: Signals) -> None:
        self.signals = signals
        self.wallet = wallet
        self.import_label_menu = upper_menu.addMenu(
            "",
        )

        self.action_bip329 = self.import_label_menu.addAction(
            "",
            lambda: self.signals.import_bip329_labels.emit(self.wallet.id),
        )
        self.action_electrum = self.import_label_menu.addAction(
            "",
            lambda: self.signals.import_electrum_wallet_labels.emit(self.wallet.id),
        )
        self.updateUi()

    def updateUi(self) -> None:
        self.import_label_menu.setTitle(translate("menu", "Import Labels"))
        self.action_bip329.setText(translate("menu", "Import Labels (BIP329 / Sparrow)"))
        self.action_electrum.setText(translate("menu", "Import Labels (Electrum Wallet)"))


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
    }

    hidden_columns = {Columns.INDEX, Columns.FIAT_BALANCE}

    stretch_column = Columns.LABEL
    key_column = Columns.ADDRESS
    column_widths = {Columns.ADDRESS: 150, Columns.COIN_BALANCE: 100}

    def __init__(self, fx, config: UserConfig, wallet: Wallet, signals: Signals) -> None:
        super().__init__(
            config=config,
            stretch_column=self.stretch_column,
            column_widths=self.column_widths,
            editable_columns=[AddressList.Columns.LABEL],
        )
        self.fx = fx
        self.signals = signals
        self.wallet = wallet
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        self.std_model = MyStandardItemModel(self, drag_key="addresses")
        self.proxy = MySortModel(self, sort_role=self.ROLE_SORT_ORDER)
        self.proxy.setSourceModel(self.std_model)
        self.setModel(self.proxy)
        self.sortByColumn(self.Columns.TYPE, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(True)  # Allow user to sort by clicking column headers
        self.update()
        self.updateUi()

        # signals
        self.signals.addresses_updated.connect(self.update_with_filter)
        self.signals.labels_updated.connect(self.update_with_filter)
        self.signals.category_updated.connect(self.update_with_filter)
        self.signals.utxos_updated.connect(self.update_with_filter)
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        self.update()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        # handle dropped files
        super().dragEnterEvent(event)
        if event.isAccepted():
            return

        if event.mimeData().hasFormat("application/json"):
            data_bytes = event.mimeData().data("application/json")
            json_string = bytes(data_bytes).decode()
            logger.debug(f"dragEnterEvent: {json_string}")

            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        return self.dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        # handle dropped files
        super().dropEvent(event)
        if event.isAccepted():
            return

        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            # Handle the case where the drop is not on a valid index
            return

        if event.mimeData().hasFormat("application/json"):
            model = self.model()
            hit_address = model.data(model.index(index.row(), self.Columns.ADDRESS))

            data_bytes = event.mimeData().data("application/json")
            json_string = bytes(data_bytes).decode()  # convert bytes to string

            d = json.loads(json_string)
            if d.get("type") == "drag_tag":
                if hit_address is not None:
                    drag_info = AddressDragInfo([d.get("tag")], [hit_address])
                    logger.debug(f"drag_info {drag_info}")
                    self.signal_tag_dropped.emit(drag_info)
                event.accept()
                return

        event.ignore()

    def on_double_click(self, idx: QModelIndex) -> None:
        addr = self.get_role_data_for_current_item(col=self.key_column, role=self.ROLE_KEY)
        self.signals.show_address.emit(addr)

    def get_address(self, force_new=False, category: str = None) -> bdk.AddressInfo:
        if force_new:
            address_info = self.wallet.get_address(force_new=force_new)
            address = address_info.address.as_string()
            self.wallet.labels.set_addr_category(address, category, timestamp="now")
            self.signals.addresses_updated.emit(UpdateFilter(addresses=set([address])))
        else:
            address_info = self.wallet.get_unused_category_address(category)
            address = address_info.address.as_string()

        do_copy(address, title=self.tr("Address {address}").format(address=address))
        self.select_row(address, self.Columns.ADDRESS)
        return address_info

    def toggle_change(self, state: int) -> None:
        if state == self.show_change:
            return
        self.show_change = AddressTypeFilter(state)
        self.update()

    def toggle_used(self, state: int) -> None:
        if state == self.show_used:
            return
        self.show_used = AddressUsageStateFilter(state)
        self.update()

    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        if update_filter.refresh_all:
            return self.update()
        logger.debug(f"{self.__class__.__name__}  update_with_filter {update_filter}")

        if update_filter.refresh_all:
            return self.update()

        remaining_addresses = set(update_filter.addresses)

        model = self.std_model
        log_info = []
        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            address = model.data(model.index(row, self.Columns.ADDRESS))
            address_match = address in update_filter.addresses
            category_match = model.data(model.index(row, self.Columns.CATEGORY)) in update_filter.categories
            if address_match or (
                not update_filter.addresses and category_match or len(update_filter.categories) > 1
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

    def get_headers(self) -> Dict:
        return {
            self.Columns.NUM_TXS: self.tr("Tx"),
            self.Columns.TYPE: self.tr("Type"),
            self.Columns.INDEX: self.tr("Index"),
            self.Columns.ADDRESS: self.tr("Address"),
            self.Columns.CATEGORY: self.tr("Category"),
            self.Columns.LABEL: self.tr("Label"),
            self.Columns.COIN_BALANCE: self.tr("Balance"),
            self.Columns.FIAT_BALANCE: self.tr("Fiat Balance"),
        }

    def update(self) -> None:
        if self.maybe_defer_update():
            return
        logger.debug(f"{self.__class__.__name__} update")

        current_selected_key = self.get_role_data_for_current_item(col=self.key_column, role=self.ROLE_KEY)
        if self.show_change == AddressTypeFilter.RECEIVING:
            addr_list = self.wallet.get_receiving_addresses()
        elif self.show_change == AddressTypeFilter.CHANGE:
            addr_list = self.wallet.get_change_addresses()
        else:
            addr_list = self.wallet.get_addresses()
        self.proxy.setDynamicSortFilter(False)  # temp. disable re-sorting after every change
        self.std_model.clear()
        self.update_headers(self.get_headers())
        set_address = None
        for address in addr_list:
            self.append_address(address)
            address_idx = self.std_model.index(self.std_model.rowCount() - 1, self.Columns.LABEL)
            if address == current_selected_key:
                set_address = QPersistentModelIndex(address_idx)

        self.set_current_idx(set_address)
        # show/hide self.Columns
        self.hideColumn(self.Columns.FIAT_BALANCE)
        self.filter()
        self.proxy.setDynamicSortFilter(True)

        for hidden_column in self.hidden_columns:
            self.hideColumn(hidden_column)

        # manually sort, after the data is filled
        super().update()

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
        item[self.Columns.ADDRESS].setData(address, self.ROLE_CLIPBOARD_DATA)
        # align text and set fonts
        # for i, item in enumerate(item):
        #     item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter)
        #     if i in (self.Columns.ADDRESS,):
        #         item.setFont(QFont(MONOSPACE_FONT))
        self.set_editability(item)
        # setup column 0

        address_info_min = self.wallet.get_address_info_min(address)
        if address_info_min:
            item[self.Columns.INDEX].setData(address_info_min.index, self.ROLE_CLIPBOARD_DATA)
            if address_info_min.is_change():
                item[self.Columns.TYPE].setText(self.tr("change"))
                item[self.Columns.TYPE].setData(self.tr("change"), self.ROLE_CLIPBOARD_DATA)
                item[self.Columns.TYPE].setBackground(ColorScheme.YELLOW.as_color(True))
            else:
                item[self.Columns.TYPE].setText(self.tr("receiving"))
                item[self.Columns.TYPE].setData(self.tr("receiving"), self.ROLE_CLIPBOARD_DATA)
                item[self.Columns.TYPE].setBackground(ColorScheme.GREEN.as_color(True))
            item[self.key_column].setData(address, self.ROLE_KEY)
            item[self.Columns.TYPE].setData(
                (address_info_min.address_path()[0], -address_info_min.address_path()[1]),
                self.ROLE_SORT_ORDER,
            )
            item[self.Columns.TYPE].setToolTip(
                f"""{address_info_min.address_path()[1]}. {self.tr("change address") if address_info_min.address_path()[0] else   self.tr('receiving address')}"""
            )
        # add item
        count = self.std_model.rowCount()
        self.std_model.insertRow(count, item)
        self.refresh_row(address, count)

    def refresh_row(self, key: str, row: int) -> None:
        assert row is not None
        address = key
        label = self.wallet.get_label_for_address(address)
        category = self.wallet.labels.get_category(address)

        txids = self.wallet.get_involved_txids(address)
        fulltxdetails = [self.wallet.get_dict_fulltxdetail().get(txid) for txid in txids]
        txs_involed = [fulltxdetail.tx for fulltxdetail in fulltxdetails if fulltxdetail]

        sort_id = (
            min([TxStatus.from_wallet(tx.txid, self.wallet).sort_id() for tx in txs_involed])
            if txs_involed
            else None
        )
        icon_path = sort_id_to_icon(sort_id) if sort_id else None
        num = len(txs_involed)

        balance = self.wallet.get_addr_balance(address).total
        balance_text = str(Satoshis(balance, self.wallet.network))
        # create item

        fiat_balance_str = ""
        item = [self.std_model.item(row, col) for col in self.Columns]
        item[self.Columns.LABEL].setText(label)
        item[self.Columns.LABEL].setData(label, self.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORY].setText(category)
        item[self.Columns.CATEGORY].setData(category, self.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORY].setBackground(CategoryEditor.color(category))
        item[self.Columns.COIN_BALANCE].setText(balance_text)
        color = QColor(0, 0, 0) if balance else QColor(255 // 2, 255 // 2, 255 // 2)
        item[self.Columns.COIN_BALANCE].setForeground(QBrush(color))
        item[self.Columns.COIN_BALANCE].setData(balance, self.ROLE_SORT_ORDER)
        item[self.Columns.COIN_BALANCE].setData(balance, self.ROLE_CLIPBOARD_DATA)
        item[self.Columns.FIAT_BALANCE].setText(fiat_balance_str)
        item[self.Columns.FIAT_BALANCE].setData(fiat_balance_str, self.ROLE_CLIPBOARD_DATA)
        # item[self.Columns.NUM_TXS].setText("%d" % num)
        item[self.Columns.NUM_TXS].setToolTip(f"{num} Transaction")
        item[self.Columns.NUM_TXS].setData(num, self.ROLE_CLIPBOARD_DATA)
        item[self.Columns.NUM_TXS].setIcon(read_QIcon(icon_path))

        # calculated_width = QFontMetrics(self.font()).horizontalAdvance(balance_text)
        # current_width = self.header().sectionSize(self.Columns.ADDRESS)
        # # Update the column width if the calculated width is larger
        # if calculated_width > current_width:
        #     self.header().resizeSection(self.Columns.ADDRESS, calculated_width)

    def create_menu(self, position: QPoint) -> None:
        # is_multisig = isinstance(self.wallet, Multisig_Wallet)
        selected = self.selected_in_column(self.Columns.ADDRESS)
        if not selected:
            return
        multi_select = len(selected) > 1
        selected_items = [self.item_from_index(item) for item in selected]
        addrs = [item.text() for item in selected_items if item]
        menu = QMenu()
        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return
            item = self.item_from_index(idx)
            if not item:
                return
            addr = addrs[0]
            menu.addAction(self.tr("Details"), lambda: self.signals.show_address.emit(addr))

            addr_URL = block_explorer_URL(self.config.network_config.mempool_url, "addr", addr)
            if addr_URL:
                menu.addAction(self.tr("View on block explorer"), lambda: webopen(addr_URL))

            menu.addSeparator()

            self.add_copy_menu(menu, idx)

            # addr_column_title = self.std_model.horizontalHeaderItem(
            #     self.Columns.LABEL
            # ).text()
            # addr_idx = idx.sibling(idx.row(), self.Columns.LABEL)
            # persistent = QPersistentModelIndex(addr_idx)
            # menu.addAction(
            #     self.tr("Edit {}").format(addr_column_title),
            #     lambda p=persistent: self.edit(QModelIndex(p)),
            # )

        menu.addAction(
            self.tr("Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
        )
        menu.addSeparator()
        menu.addAction(
            self.tr("Export Labels"),
            lambda: self.signals.export_bip329_labels.emit(self.wallet.id),
        )
        self.import_label_menu = ImportMenu(menu, wallet=self.wallet, signals=self.signals)

        # run_hook('receive_menu', menu, addrs, self.wallet)
        menu.exec(self.viewport().mapToGlobal(position))

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
        return self.get_role_data_from_coordinate(row, self.key_column, role=self.ROLE_KEY)

    def on_edited(self, idx, edit_key, *, text) -> None:
        self.wallet.labels.set_addr_label(edit_key, text, timestamp="now")
        self.signals.labels_updated.emit(
            UpdateFilter(
                addresses=[edit_key],
                txids=self.wallet.get_involved_txids(edit_key),
            )
        )


class AddressListWithToolbar(TreeViewWithToolbar):
    def __init__(self, address_list: AddressList, config: UserConfig, parent: QWidget = None) -> None:
        super().__init__(address_list, config, parent=parent)
        self.address_list: AddressList = address_list
        self.change_button = QComboBox(self)
        self.change_button.currentIndexChanged.connect(self.address_list.toggle_change)
        for addr_type in AddressTypeFilter.__members__.values():  # type: AddressTypeFilter
            self.change_button.addItem(addr_type.ui_text())
        self.used_button = QComboBox(self)
        self.used_button.currentIndexChanged.connect(self.address_list.toggle_used)
        for addr_usage_state in AddressUsageStateFilter.__members__.values():  # type: AddressUsageStateFilter
            self.used_button.addItem(addr_usage_state.ui_text())

        self.create_layout()

        self.address_list.signals.language_switch.connect(self.updateUi)
        self.address_list.signals.utxos_updated.connect(self.updateUi)

    def updateUi(self) -> None:
        super().updateUi()

        self.action_show_filter.setText(self.tr("Show Filter"))
        self.action_export_labels.setText(self.tr("Export Labels"))
        self.menu_import_labels.updateUi()

        if self.balance_label:
            balance = self.address_list.wallet.get_balance()
            self.balance_label.setText(balance.format_short(self.address_list.wallet.network))
            self.balance_label.setToolTip(balance.format_long(self.address_list.wallet.network))

    def create_toolbar_with_menu(self, title) -> None:
        super().create_toolbar_with_menu(title=title)

        font = QFont()
        font.setPointSize(12)
        self.balance_label.setFont(font)

        self.action_show_filter = self.menu.addToggle("", lambda: self.toggle_toolbar(self.config))
        self.action_export_labels = self.menu.addAction(
            "",
            lambda: self.address_list.signals.export_bip329_labels.emit(self.address_list.wallet.id),
        )

        self.menu_import_labels = ImportMenu(
            self.menu, wallet=self.address_list.wallet, signals=self.address_list.signals
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
                self.address_list.signals.chain_data_changed.emit(f"Mined to addresses {addresses}")

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
