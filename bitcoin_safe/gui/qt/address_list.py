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

from matplotlib import category

from ...config import UserConfig, BlockchainType

logger = logging.getLogger(__name__)


import bdkpython as bdk
import enum
from enum import IntEnum
from typing import TYPE_CHECKING

from PySide2.QtCore import (
    Qt,
    QPersistentModelIndex,
    QModelIndex,
    QMimeData,
    QPoint,
    Signal,
)
from PySide2.QtGui import (
    QStandardItemModel,
    QStandardItem,
    QFont,
    QMouseEvent,
    QDrag,
    QPixmap,
    QCursor,
    QRegion,
    QPainter,
)
from PySide2.QtWidgets import QAbstractItemView, QComboBox, QLabel, QMenu, QPushButton
from jsonschema import draft201909_format_checker
from .category_list import CategoryEditor

from ...wallet import Wallet

from ...i18n import _
from ...util import (
    InternalAddressCorruption,
    block_explorer_URL,
    format_satoshis,
    DEVELOPMENT_PREFILLS,
)
import json
from ...rpc import send_rpc_command

from .util import MONOSPACE_FONT, ColorScheme, MessageBoxMixin, webopen, do_copy
from .my_treeview import MyTreeView, MySortModel
from .taglist import AddressDragInfo
from .html_delegate import HTMLDelegate
from ...signals import UpdateFilter


class MyStandardItemModel(QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)

    def flags(self, index):
        if (
            index.column() == AddressList.Columns.ADDRESS
        ):  # only enable dragging for column 1
            return super().flags(index) | Qt.ItemIsDragEnabled
        else:
            return super().flags(index)

    def mimeData(self, indexes):
        mime_data = QMimeData()
        d = {
            "type": "drag_addresses",
            "addresses": [],
        }

        for index in indexes:
            if index.isValid() and index.column() == AddressList.Columns.ADDRESS:
                d["addresses"].append(self.data(index))

        json_string = json.dumps(d).encode()
        mime_data.setData("application/json", json_string)
        return mime_data


class AddressUsageStateFilter(IntEnum):
    ALL = 0
    UNUSED = 1
    FUNDED = 2
    USED_AND_EMPTY = 3
    FUNDED_OR_UNUSED = 4

    def ui_text(self) -> str:
        return {
            self.ALL: _("All status"),
            self.UNUSED: _("Unused"),
            self.FUNDED: _("Funded"),
            self.USED_AND_EMPTY: _("Used"),
            self.FUNDED_OR_UNUSED: _("Funded or Unused"),
        }[self]


class AddressTypeFilter(IntEnum):
    ALL = 0
    RECEIVING = 1
    CHANGE = 2

    def ui_text(self) -> str:
        return {
            self.ALL: _("All types"),
            self.RECEIVING: _("Receiving"),
            self.CHANGE: _("Change"),
        }[self]


from ...signals import Signals


class AddressList(MyTreeView, MessageBoxMixin):
    signal_tag_dropped = Signal(AddressDragInfo)

    class Columns(MyTreeView.BaseColumnsEnum):
        TYPE = enum.auto()
        ADDRESS = enum.auto()
        CATEGORY = enum.auto()
        LABEL = enum.auto()
        COIN_BALANCE = enum.auto()
        FIAT_BALANCE = enum.auto()
        NUM_TXS = enum.auto()

    filter_columns = [
        Columns.TYPE,
        Columns.ADDRESS,
        Columns.CATEGORY,
        Columns.LABEL,
        Columns.COIN_BALANCE,
    ]
    column_alignments = {
        Columns.COIN_BALANCE: Qt.AlignRight,
        Columns.NUM_TXS: Qt.AlignRight,
        Columns.CATEGORY: Qt.AlignCenter,
    }

    ROLE_SORT_ORDER = Qt.UserRole + 1000
    ROLE_ADDRESS_STR = Qt.UserRole + 1001
    key_role = ROLE_ADDRESS_STR

    def __init__(self, fx, config, wallet: Wallet, signals: Signals):
        super().__init__(
            config=config,
            stretch_column=AddressList.Columns.LABEL,
            editable_columns=[AddressList.Columns.LABEL],
        )
        self.fx = fx
        self.signals = signals
        self.wallet = wallet
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        self.change_button = QComboBox(self)
        self.change_button.currentIndexChanged.connect(self.toggle_change)
        for (
            addr_type
        ) in AddressTypeFilter.__members__.values():  # type: AddressTypeFilter
            self.change_button.addItem(addr_type.ui_text())
        self.used_button = QComboBox(self)
        self.used_button.currentIndexChanged.connect(self.toggle_used)
        for (
            addr_usage_state
        ) in (
            AddressUsageStateFilter.__members__.values()
        ):  # type: AddressUsageStateFilter
            self.used_button.addItem(addr_usage_state.ui_text())
        self.std_model = MyStandardItemModel(self)
        self.proxy = MySortModel(self, sort_role=self.ROLE_SORT_ORDER)
        self.proxy.setSourceModel(self.std_model)
        self.setModel(self.proxy)
        self.update()
        self.sortByColumn(AddressList.Columns.TYPE, Qt.AscendingOrder)
        self.signals.addresses_updated.connect(self.update)
        self.signals.labels_updated.connect(self.update_with_filter)
        self.signals.category_updated.connect(self.update_with_filter)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def startDrag(self, action):
        indexes = self.selectedIndexes()
        if indexes:
            drag = QDrag(self)
            mime_data = self.model().mimeData(indexes)
            drag.setMimeData(mime_data)

            total_height = sum(self.visualRect(index).height() for index in indexes)
            max_width = max(self.visualRect(index).width() for index in indexes)

            pixmap = QPixmap(max_width, total_height)
            pixmap.fill(Qt.transparent)

            painter = QPainter(pixmap)
            current_height = 0
            for index in indexes:
                if index.column() != self.Columns.ADDRESS:
                    continue
                rect = self.visualRect(index)
                temp_pixmap = QPixmap(rect.size())
                self.viewport().render(temp_pixmap, QPoint(), QRegion(rect))
                painter.drawPixmap(0, current_height, temp_pixmap)
                current_height += rect.height()
            painter.end()

            cursor_pos = self.mapFromGlobal(QCursor.pos())
            visual_rect = self.visualRect(indexes[0]).bottomLeft()
            hotspot_pos = cursor_pos - visual_rect
            # the y offset is always off, so just set it completely to 0
            hotspot_pos.setY(0)
            drag.setPixmap(pixmap)
            drag.setHotSpot(hotspot_pos)

            drag.exec_(action)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/json"):
            logger.debug("accept drag enter")
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        index = self.indexAt(event.pos())
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

    def on_double_click(self, idx):
        addr = self.get_role_data_for_current_item(col=0, role=self.ROLE_ADDRESS_STR)
        self.signals.show_address.emit(addr)

    def create_toolbar(self, config: UserConfig = None):
        toolbar, menu = self.create_toolbar_with_menu("")
        self.num_addr_label = toolbar.itemAt(0).widget()
        self.button_get_new_address = toolbar.itemAt(1).widget()
        menu.addToggle(_("Show Filter"), lambda: self.toggle_toolbar(config))
        # menu.addConfig(_('Show Fiat balances'), 'fiat_address', False, callback=self.main_window.app.update_fiat_signal.emit)

        self.button_fresh_address = QPushButton("Copy fresh receive address")
        self.button_fresh_address.clicked.connect(self.get_address)
        toolbar.insertWidget(1, self.button_fresh_address)
        self.button_new_address = QPushButton("+ Add \& Copy receive address")
        self.button_new_address.clicked.connect(
            lambda: self.get_address(force_new=True)
        )
        toolbar.insertWidget(2, self.button_new_address)

        if (
            config
            and DEVELOPMENT_PREFILLS
            and config.network_settings.server_type == BlockchainType.RPC
        ):

            def mine_to_selected_addresses():
                selected = self.selected_in_column(self.Columns.ADDRESS)
                if not selected:
                    return
                addresses = [self.item_from_index(item).text() for item in selected]

                for address in addresses:
                    response = send_rpc_command(
                        config.network_settings.rpc_ip,
                        config.network_settings.rpc_port,
                        config.network_settings.rpc_username,
                        config.network_settings.rpc_password,
                        "generatetoaddress",
                        params=[1, address],
                    )
                    logger.info(f"{response}")
                self.signals.chain_data_changed.emit(f"Mined to addresses {addresses}")

            b = QPushButton("Generate to selected adddresses")
            b.clicked.connect(mine_to_selected_addresses)
            toolbar.insertWidget(3, b)

        hbox = self.create_toolbar_buttons()
        toolbar.insertLayout(3, hbox)

        return toolbar

    def get_address(self, force_new=False):
        address_info = self.wallet.get_address(force_new=force_new)
        address = address_info.address.as_string()
        do_copy(address, title=f"Address {address}")
        self.signals.addresses_updated.emit()
        self.select_rows(address, self.Columns.ADDRESS)

    def should_show_fiat(self):
        return False
        return (
            self.main_window.fx
            and self.main_window.fx.is_enabled()
            and self.config.get("fiat_address", False)
        )

    def get_toolbar_buttons(self):
        return self.change_button, self.used_button

    def on_hide_toolbar(self):
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        self.update()

    def refresh_headers(self):
        if self.should_show_fiat():
            ccy = self.fx.get_currency()
        else:
            ccy = _("Fiat")
        headers = {
            self.Columns.TYPE: _("Type"),
            self.Columns.ADDRESS: _("Address"),
            self.Columns.CATEGORY: _("Category"),
            self.Columns.LABEL: _("Label"),
            self.Columns.COIN_BALANCE: _("Balance"),
            self.Columns.FIAT_BALANCE: ccy + " " + _("Balance"),
            self.Columns.NUM_TXS: _("Tx"),
        }
        self.update_headers(headers)

    def toggle_change(self, state: int):
        if state == self.show_change:
            return
        self.show_change = AddressTypeFilter(state)
        self.update()

    def toggle_used(self, state: int):
        if state == self.show_used:
            return
        self.show_used = AddressUsageStateFilter(state)
        self.update()

    def update_with_filter(self, update_filter: UpdateFilter):
        if update_filter.refresh_all:
            return self.update()

        model = self.model()
        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            address = model.data(model.index(row, self.Columns.ADDRESS))
            if (
                address in update_filter.addresses
                or model.data(model.index(row, self.Columns.CATEGORY))
                in update_filter.categories
            ):
                logger.debug(f"Updating row {row}: {address}")
                self.refresh_row(address, row)

    def update(self):
        if self.maybe_defer_update():
            return
        current_address = self.get_role_data_for_current_item(
            col=0, role=self.ROLE_ADDRESS_STR
        )
        if self.show_change == AddressTypeFilter.RECEIVING:
            addr_list = self.wallet.get_receiving_addresses()
        elif self.show_change == AddressTypeFilter.CHANGE:
            addr_list = self.wallet.get_change_addresses()
        else:
            addr_list = self.wallet.get_addresses()
        self.proxy.setDynamicSortFilter(
            False
        )  # temp. disable re-sorting after every change
        self.std_model.clear()
        self.refresh_headers()
        fx = None
        set_address = None
        num_shown = 0
        self.addresses_beyond_gap_limit = (
            self.wallet.get_all_known_addresses_beyond_gap_limit()
        )
        for address in addr_list:
            c, u, x = self.wallet.get_addr_balance(address)
            balance = c + u + x
            is_used_and_empty = self.wallet.address_is_used(address) and balance == 0
            if self.show_used == AddressUsageStateFilter.UNUSED and (
                balance or is_used_and_empty
            ):
                continue
            if self.show_used == AddressUsageStateFilter.FUNDED and balance == 0:
                continue
            if (
                self.show_used == AddressUsageStateFilter.USED_AND_EMPTY
                and not is_used_and_empty
            ):
                continue
            if (
                self.show_used == AddressUsageStateFilter.FUNDED_OR_UNUSED
                and is_used_and_empty
            ):
                continue
            num_shown += 1
            labels = [""] * len(self.Columns)
            labels[self.Columns.ADDRESS] = address
            address_item = [QStandardItem(e) for e in labels]
            address_item[self.Columns.ADDRESS].setData(
                address, self.ROLE_CLIPBOARD_DATA
            )
            # align text and set fonts
            for i, item in enumerate(address_item):
                item.setTextAlignment(Qt.AlignVCenter)
                if i in (self.Columns.ADDRESS,):
                    item.setFont(QFont(MONOSPACE_FONT))
            self.set_editability(address_item)
            address_item[self.Columns.FIAT_BALANCE].setTextAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            # setup column 0
            if self.wallet.is_change(address):
                address_item[self.Columns.TYPE].setText(_("change"))
                address_item[self.Columns.TYPE].setData(
                    _("change"), self.ROLE_CLIPBOARD_DATA
                )
                address_item[self.Columns.TYPE].setBackground(
                    ColorScheme.YELLOW.as_color(True)
                )
                address_path = self.wallet.get_address_index_tuple(
                    address, bdk.KeychainKind.INTERNAL
                )
            else:
                address_item[self.Columns.TYPE].setText(_("receiving"))
                address_item[self.Columns.TYPE].setData(
                    _("receiving"), self.ROLE_CLIPBOARD_DATA
                )
                address_item[self.Columns.TYPE].setBackground(
                    ColorScheme.GREEN.as_color(True)
                )
                address_path = self.wallet.get_address_index_tuple(
                    address, bdk.KeychainKind.EXTERNAL
                )
            address_item[0].setData(address, self.ROLE_ADDRESS_STR)
            address_item[self.Columns.TYPE].setData(address_path, self.ROLE_SORT_ORDER)
            address_path_str = self.wallet.get_address_path_str(address)
            if address_path_str is not None:
                address_item[self.Columns.TYPE].setToolTip(address_path_str)
            # add item
            count = self.std_model.rowCount()
            self.std_model.insertRow(count, address_item)
            self.refresh_row(address, count)
            address_idx = self.std_model.index(count, self.Columns.LABEL)
            if address == current_address:
                set_address = QPersistentModelIndex(address_idx)
        self.set_current_idx(set_address)
        # show/hide self.Columns
        if self.should_show_fiat():
            self.showColumn(self.Columns.FIAT_BALANCE)
        else:
            self.hideColumn(self.Columns.FIAT_BALANCE)
        self.filter()
        self.proxy.setDynamicSortFilter(True)
        # update counter
        self.num_addr_label.setText(_("{} addresses").format(num_shown))

    def refresh_row(self, key, row):
        assert row is not None
        address = key
        label = self.wallet.get_label_for_address(address)
        category = self.wallet.get_category_for_address(address)
        num = self.wallet.get_address_history_len(address)
        c, u, x = self.wallet.get_addr_balance(address)
        balance = c + u + x
        balance_text = format_satoshis(balance)
        # create item
        fx = self.fx
        if self.should_show_fiat():
            rate = fx.exchange_rate()
            fiat_balance_str = fx.value_str(balance, rate)
        else:
            fiat_balance_str = ""
        address_item = [self.std_model.item(row, col) for col in self.Columns]
        address_item[self.Columns.LABEL].setText(label)
        address_item[self.Columns.LABEL].setData(label, self.ROLE_CLIPBOARD_DATA)
        address_item[self.Columns.CATEGORY].setText(category)
        address_item[self.Columns.CATEGORY].setData(category, self.ROLE_CLIPBOARD_DATA)
        address_item[self.Columns.CATEGORY].setBackground(
            CategoryEditor.color(category)
        )
        address_item[self.Columns.COIN_BALANCE].setText(balance_text)
        address_item[self.Columns.COIN_BALANCE].setData(balance, self.ROLE_SORT_ORDER)
        address_item[self.Columns.COIN_BALANCE].setData(
            balance, self.ROLE_CLIPBOARD_DATA
        )
        address_item[self.Columns.FIAT_BALANCE].setText(fiat_balance_str)
        address_item[self.Columns.FIAT_BALANCE].setData(
            fiat_balance_str, self.ROLE_CLIPBOARD_DATA
        )
        address_item[self.Columns.NUM_TXS].setText("%d" % num)
        address_item[self.Columns.NUM_TXS].setData(num, self.ROLE_CLIPBOARD_DATA)
        if address in self.addresses_beyond_gap_limit:
            address_item[self.Columns.ADDRESS].setBackground(
                ColorScheme.RED.as_color(True)
            )

    def create_menu(self, position):
        # is_multisig = isinstance(self.wallet, Multisig_Wallet)
        selected = self.selected_in_column(self.Columns.ADDRESS)
        if not selected:
            return
        multi_select = len(selected) > 1
        addrs = [self.item_from_index(item).text() for item in selected]
        menu = QMenu()
        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return
            item = self.item_from_index(idx)
            if not item:
                return
            addr = addrs[0]
            menu.addAction(_("Details"), lambda: self.signals.show_address.emit(addr))
            addr_column_title = self.std_model.horizontalHeaderItem(
                self.Columns.LABEL
            ).text()
            addr_idx = idx.sibling(idx.row(), self.Columns.LABEL)
            self.add_copy_menu(menu, idx)
            persistent = QPersistentModelIndex(addr_idx)
            menu.addAction(
                _("Edit {}").format(addr_column_title),
                lambda p=persistent: self.edit(QModelIndex(p)),
            )
            # menu.addAction(_("Request payment"), lambda: self.main_window.receive_at(addr))
            # if self.wallet.can_export():
            #     menu.addAction(_("Private key"), lambda: self.signals.show_private_key(addr))
            # if not is_multisig and not self.wallet.is_watching_only():
            #     menu.addAction(_("Sign/verify message"), lambda: self.signals.sign_verify_message(addr))
            #     menu.addAction(_("Encrypt/decrypt message"), lambda: self.signals.encrypt_message(addr))
            addr_URL = block_explorer_URL(self.config, "addr", addr)
            if addr_URL:
                menu.addAction(_("View on block explorer"), lambda: webopen(addr_URL))

        menu.addAction(
            _("Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
        )

        # run_hook('receive_menu', menu, addrs, self.wallet)
        menu.exec_(self.viewport().mapToGlobal(position))

    # def place_text_on_clipboard(self, text: str, *, title: str = None) -> None:
    #     if bdk.Address(text):
    #         try:
    #             self.wallet.check_address_for_corruption(text)
    #         except InternalAddressCorruption as e:
    #             self.show_error(str(e))
    #             raise
    #     super().place_text_on_clipboard(text, title=title)

    def get_edit_key_from_coordinate(self, row, col):
        if col != self.Columns.LABEL:
            return None
        return self.get_role_data_from_coordinate(row, 0, role=self.ROLE_ADDRESS_STR)

    def on_edited(self, idx, edit_key, *, text):
        self.wallet.set_label(edit_key, text)
        self.signals.labels_updated.emit(UpdateFilter(addresses=[edit_key]))
