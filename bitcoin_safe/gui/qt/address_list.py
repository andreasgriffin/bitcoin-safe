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

import csv
from datetime import datetime
import io
import logging
import os
import tempfile


from ...config import UserConfig, BlockchainType

logger = logging.getLogger(__name__)


from .util import (
    MONOSPACE_FONT,
    ColorScheme,
    MessageBoxMixin,
    set_balance_label,
    webopen,
    do_copy,
    read_QIcon,
    TX_ICONS,
    sort_id_to_icon,
)
from PySide2.QtGui import QBrush, QColor, QFont
import bdkpython as bdk
import enum
from enum import IntEnum
import numpy as np
from typing import TYPE_CHECKING, List
from PySide2.QtCore import (
    Qt,
    QPersistentModelIndex,
    QModelIndex,
    QMimeData,
    QPoint,
    Signal,
)
from PySide2.QtCore import QMimeData, QUrl

from PySide2.QtGui import (
    QStandardItemModel,
    QStandardItem,
    QFont,
    QFontMetrics,
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
from bitcoin_qrreader.bitcoin_qr import Data, DataType
from ...i18n import _
from ...util import (
    InternalAddressCorruption,
    Satoshis,
    block_explorer_URL,
    DEVELOPMENT_PREFILLS,
)
import json
from ...rpc import send_rpc_command

from .util import MONOSPACE_FONT, ColorScheme, MessageBoxMixin, webopen, do_copy
from .my_treeview import MyTreeView, MySortModel, MyStandardItemModel
from .taglist import AddressDragInfo
from .html_delegate import HTMLDelegate
from ...signals import UpdateFilter

from ...signals import Signals


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


class AddressList(MyTreeView, MessageBoxMixin):
    signal_tag_dropped = Signal(AddressDragInfo)

    class Columns(MyTreeView.BaseColumnsEnum):
        NUM_TXS = enum.auto()
        TYPE = enum.auto()
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
        Columns.TYPE: Qt.AlignHCenter | Qt.AlignVCenter,
        Columns.ADDRESS: Qt.AlignLeft | Qt.AlignVCenter,
        Columns.CATEGORY: Qt.AlignHCenter | Qt.AlignVCenter,
        Columns.LABEL: Qt.AlignLeft | Qt.AlignVCenter,
        Columns.COIN_BALANCE: Qt.AlignRight | Qt.AlignVCenter,
        Columns.NUM_TXS: Qt.AlignRight | Qt.AlignVCenter,
    }

    stretch_column = Columns.LABEL
    key_column = Columns.ADDRESS
    column_widths = {Columns.ADDRESS: 150, Columns.COIN_BALANCE: 100}

    def __init__(self, fx, config, wallet: Wallet, signals: Signals):
        super().__init__(
            config=config,
            stretch_column=self.stretch_column,
            column_widths=self.column_widths,
            editable_columns=[AddressList.Columns.LABEL],
        )
        self.fx = fx
        self.signals = signals
        self.wallet = wallet
        self.setTextElideMode(Qt.ElideMiddle)
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
        self.std_model = MyStandardItemModel(self, drag_key="addresses")
        self.proxy = MySortModel(self, sort_role=self.ROLE_SORT_ORDER)
        self.proxy.setSourceModel(self.std_model)
        self.setModel(self.proxy)
        self.update()
        self.sortByColumn(AddressList.Columns.TYPE, Qt.AscendingOrder)
        self.signals.addresses_updated.connect(self.update_with_filter)
        self.signals.labels_updated.connect(self.update_with_filter)
        self.signals.category_updated.connect(self.update_with_filter)

    def dragEnterEvent(self, event):
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

    def dragMoveEvent(self, event):
        return self.dragEnterEvent(event)

    def dropEvent(self, event):
        # handle dropped files
        super().dropEvent(event)
        if event.isAccepted():
            return

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
        addr = self.get_role_data_for_current_item(
            col=self.key_column, role=self.ROLE_KEY
        )
        self.signals.show_address.emit(addr)

    def create_toolbar(self, config: UserConfig = None):
        toolbar, menu = self.create_toolbar_with_menu("")
        self.balance_label = toolbar.itemAt(0).widget()
        font = QFont()
        font.setPointSize(12)
        self.balance_label.setFont(font)

        self.button_get_new_address = toolbar.itemAt(1).widget()
        menu.addToggle(_("Show Filter"), lambda: self.toggle_toolbar(config))
        menu.addAction(
            _("Export Labels"),
            lambda: self.signals.export_bip329_labels.emit(self.wallet.id),
        )
        menu.addAction(
            _("Import Labels"),
            lambda: self.signals.import_bip329_labels.emit(self.wallet.id),
        )

        # self.button_fresh_address = QPushButton("Copy fresh receive address")
        # self.button_fresh_address.clicked.connect(self.get_address)
        # toolbar.insertWidget(toolbar.count()-2, self.button_fresh_address)
        # self.button_new_address = QPushButton("+ Add receive address")
        # self.button_new_address.clicked.connect(
        #     lambda: self.get_address(force_new=True)
        # )
        # toolbar.insertWidget(toolbar.count()-2, self.button_new_address)

        if (
            config
            and config.network_settings.server_type == BlockchainType.RPC
            and config.network_settings.network != bdk.Network.BITCOIN
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
            toolbar.insertWidget(toolbar.count() - 2, b)

        hbox = self.create_toolbar_buttons()
        toolbar.insertLayout(toolbar.count() - 1, hbox)

        return toolbar

    def get_address(self, force_new=False, category=None) -> bdk.AddressInfo:
        if force_new:
            address_info = self.wallet.get_address(force_new=force_new)
            address = address_info.address.as_string()
            self.wallet.labels.set_addr_category(address, category)
            self.signals.addresses_updated.emit(UpdateFilter(addresses=[address]))
        else:
            address_info = self.wallet.get_unused_category_address(category)
            address = address_info.address.as_string()

        do_copy(address, title=f"Address {address}")
        self.select_row(address, self.Columns.ADDRESS)
        return address_info

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
        logger.debug(f"{self.__class__.__name__}  update_with_filter {update_filter}")

        if update_filter.refresh_all:
            return self.update()

        remaining_addresses = set(update_filter.addresses)

        model = self.std_model
        log_info = []
        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            address = model.data(model.index(row, self.Columns.ADDRESS))
            if (
                address in update_filter.addresses
                or model.data(model.index(row, self.Columns.CATEGORY))
                in update_filter.categories
            ):
                log_info.append((row, address))
                self.refresh_row(address, row)
                remaining_addresses = remaining_addresses - set([address])

        # sometimes additional addresses are updated,
        # i can add them here without recreating the whole model
        if remaining_addresses:
            for address in set(self.wallet.get_addresses()).intersection(
                remaining_addresses
            ):
                log_info.append((address,))
                self.append_address(address)
                remaining_addresses = remaining_addresses - set([address])

        logger.debug(
            f"Updated addresses  {log_info}.  remaining_addresses = {remaining_addresses}"
        )

    def update(self):
        if self.maybe_defer_update():
            return
        logger.debug(f"{self.__class__.__name__} update")
        current_selected_key = self.get_role_data_for_current_item(
            col=self.key_column, role=self.ROLE_KEY
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
        set_address = None
        for address in addr_list:
            self.append_address(address)
            address_idx = self.std_model.index(
                self.std_model.rowCount() - 1, self.Columns.LABEL
            )
            if address == current_selected_key:
                set_address = QPersistentModelIndex(address_idx)

        self.set_current_idx(set_address)
        # show/hide self.Columns
        if self.should_show_fiat():
            self.showColumn(self.Columns.FIAT_BALANCE)
        else:
            self.hideColumn(self.Columns.FIAT_BALANCE)
        self.filter()
        self.proxy.setDynamicSortFilter(True)

        if self.balance_label:
            set_balance_label(self.balance_label, [self.wallet])

    def append_address(self, address):
        c, u, x = self.wallet.get_addr_balance(address)
        balance = c + u + x
        is_used_and_empty = self.wallet.address_is_used(address) and balance == 0
        if self.show_used == AddressUsageStateFilter.UNUSED and (
            balance or is_used_and_empty
        ):
            return
        if self.show_used == AddressUsageStateFilter.FUNDED and balance == 0:
            return
        if (
            self.show_used == AddressUsageStateFilter.USED_AND_EMPTY
            and not is_used_and_empty
        ):
            return
        if (
            self.show_used == AddressUsageStateFilter.FUNDED_OR_UNUSED
            and is_used_and_empty
        ):
            return
        labels = [""] * len(self.Columns)
        labels[self.Columns.ADDRESS] = address
        item = [QStandardItem(e) for e in labels]
        item[self.Columns.ADDRESS].setData(address, self.ROLE_CLIPBOARD_DATA)
        # align text and set fonts
        # for i, item in enumerate(item):
        #     item.setTextAlignment(Qt.AlignVCenter)
        #     if i in (self.Columns.ADDRESS,):
        #         item.setFont(QFont(MONOSPACE_FONT))
        self.set_editability(item)
        # setup column 0
        if self.wallet.is_change(address):
            item[self.Columns.TYPE].setText(_("change"))
            item[self.Columns.TYPE].setData(_("change"), self.ROLE_CLIPBOARD_DATA)
            item[self.Columns.TYPE].setBackground(ColorScheme.YELLOW.as_color(True))
            address_path = self.wallet.get_address_index_tuple(
                address, bdk.KeychainKind.INTERNAL
            )
        else:
            item[self.Columns.TYPE].setText(_("receiving"))
            item[self.Columns.TYPE].setData(_("receiving"), self.ROLE_CLIPBOARD_DATA)
            item[self.Columns.TYPE].setBackground(ColorScheme.GREEN.as_color(True))
            address_path = self.wallet.get_address_index_tuple(
                address, bdk.KeychainKind.EXTERNAL
            )
        item[self.key_column].setData(address, self.ROLE_KEY)
        item[self.Columns.TYPE].setData(
            (address_path[0], -address_path[1]), self.ROLE_SORT_ORDER
        )
        item[self.Columns.TYPE].setToolTip(
            f"{address_path[1]}. {'change' if address_path[0] else 'receiving'} address"
        )
        # add item
        count = self.std_model.rowCount()
        self.std_model.insertRow(count, item)
        self.refresh_row(address, count)

    def refresh_row(self, key, row):
        assert row is not None
        address = key
        label = self.wallet.get_label_for_address(address)
        category = self.wallet.labels.get_category(address)

        txids = self.wallet.get_address_to_txids(address)
        fulltxdetails = [
            self.wallet.get_dict_fulltxdetail().get(txid) for txid in txids
        ]
        txs_involed = [
            fulltxdetail.tx for fulltxdetail in fulltxdetails if fulltxdetail
        ]

        sort_id = (
            min([self.wallet.get_tx_status(tx).sort_id for tx in txs_involed])
            if txs_involed
            else None
        )
        icon_path = sort_id_to_icon(sort_id) if txs_involed else None
        num = len(txs_involed)

        c, u, x = self.wallet.get_addr_balance(address)
        balance = c + u + x
        balance_text = str(Satoshis(balance, self.wallet.network))
        # create item
        fx = self.fx
        if self.should_show_fiat():
            rate = fx.exchange_rate()
            fiat_balance_str = fx.value_str(balance, rate)
        else:
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
        item[self.Columns.FIAT_BALANCE].setData(
            fiat_balance_str, self.ROLE_CLIPBOARD_DATA
        )
        # item[self.Columns.NUM_TXS].setText("%d" % num)
        item[self.Columns.NUM_TXS].setToolTip(f"{num} Transaction")
        item[self.Columns.NUM_TXS].setData(num, self.ROLE_CLIPBOARD_DATA)
        item[self.Columns.NUM_TXS].setIcon(read_QIcon(icon_path))

        # calculated_width = QFontMetrics(self.font()).horizontalAdvance(balance_text)
        # current_width = self.header().sectionSize(self.Columns.ADDRESS)
        # # Update the column width if the calculated width is larger
        # if calculated_width > current_width:
        #     self.header().resizeSection(self.Columns.ADDRESS, calculated_width)

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

            addr_URL = block_explorer_URL(self.config.network_settings, "addr", addr)
            if addr_URL:
                menu.addAction(_("View on block explorer"), lambda: webopen(addr_URL))

            menu.addSeparator()

            self.add_copy_menu(menu, idx)

            # addr_column_title = self.std_model.horizontalHeaderItem(
            #     self.Columns.LABEL
            # ).text()
            # addr_idx = idx.sibling(idx.row(), self.Columns.LABEL)
            # persistent = QPersistentModelIndex(addr_idx)
            # menu.addAction(
            #     _("Edit {}").format(addr_column_title),
            #     lambda p=persistent: self.edit(QModelIndex(p)),
            # )

        menu.addAction(
            _("Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
        )
        menu.addSeparator()
        menu.addAction(
            _("Export Labels"),
            lambda: self.signals.export_bip329_labels.emit(self.wallet.id),
        )
        menu.addAction(
            _("Import Labels"),
            lambda: self.signals.import_bip329_labels.emit(self.wallet.id),
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
        return self.get_role_data_from_coordinate(
            row, self.key_column, role=self.ROLE_KEY
        )

    def on_edited(self, idx, edit_key, *, text):
        self.wallet.labels.set_addr_label(edit_key, text)
        self.signals.labels_updated.emit(
            UpdateFilter(
                addresses=[edit_key],
                txids=self.wallet.get_address_to_txids(edit_key),
            )
        )
