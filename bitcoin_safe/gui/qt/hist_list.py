import logging
from os import stat

logger = logging.getLogger(__name__)

import datetime
import bdkpython as bdk
import enum
from enum import IntEnum
from typing import TYPE_CHECKING, List, Dict, Tuple

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

from ...wallet import Wallet, TxConfirmationStatus

from ...i18n import _
from ...util import (
    InternalAddressCorruption,
    block_explorer_URL,
    format_satoshis,
    serialized_to_hex,
)
import json


from .util import (
    MONOSPACE_FONT,
    ColorScheme,
    MessageBoxMixin,
    webopen,
    do_copy,
    read_QIcon,
    TX_ICONS,
    sort_id_to_icon,
)
from .my_treeview import MyTreeView, MySortModel, MyStandardItemModel
from .taglist import AddressDragInfo
from .html_delegate import HTMLDelegate
from ...signals import UpdateFilter
from PySide2.QtGui import QStandardItem, QBrush, QColor


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


class HistList(MyTreeView, MessageBoxMixin):
    signal_tag_dropped = Signal(AddressDragInfo)

    class Columns(MyTreeView.BaseColumnsEnum):
        WALLET_ID = enum.auto()
        STATUS = enum.auto()
        CATEGORIES = enum.auto()
        LABEL = enum.auto()
        AMOUNT = enum.auto()
        SATOSHIS = enum.auto()
        BALANCE = enum.auto()
        TXID = enum.auto()

    filter_columns = [
        Columns.WALLET_ID,
        Columns.STATUS,
        Columns.CATEGORIES,
        Columns.LABEL,
        Columns.AMOUNT,
        Columns.SATOSHIS,
        Columns.TXID,
    ]

    headers = {
        Columns.WALLET_ID: _("Wallet"),
        Columns.STATUS: _("Status"),
        Columns.CATEGORIES: _("Category"),
        Columns.LABEL: _("Label"),
        Columns.AMOUNT: _("Amount"),
        Columns.SATOSHIS: _("SATOSHIS"),
        Columns.BALANCE: _("Balance"),
        Columns.TXID: _("Txid"),
    }

    column_alignments = {
        Columns.STATUS: Qt.AlignCenter,
        Columns.WALLET_ID: Qt.AlignCenter,
        Columns.CATEGORIES: Qt.AlignCenter,
        Columns.SATOSHIS: Qt.AlignRight,
        Columns.BALANCE: Qt.AlignRight,
        Columns.AMOUNT: Qt.AlignRight,
    }

    def __init__(
        self,
        fx,
        config,
        signals: Signals,
        wallet_id=None,
        hidden_columns=None,
        txid_domain=None,
    ):
        super().__init__(
            config=config,
            stretch_column=HistList.Columns.LABEL,
            editable_columns=[HistList.Columns.LABEL],
        )
        self.fx = fx
        self.txid_domain = txid_domain
        self.hidden_columns = hidden_columns if hidden_columns else []
        self._tx_dict: Dict[
            str, Tuple[Wallet, bdk.TransactionDetails]
        ] = {}  # txid -> wallet, tx
        self.signals = signals
        self.wallet_id = wallet_id
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSortingEnabled(True)
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        # self.change_button = QComboBox(self)
        # self.change_button.currentIndexChanged.connect(self.toggle_change)
        # for (
        #     addr_type
        # ) in AddressTypeFilter.__members__.values():  # type: AddressTypeFilter
        #     self.change_button.addItem(addr_type.ui_text())
        self.num_label = None
        # self.used_button = QComboBox(self)
        # self.used_button.currentIndexChanged.connect(self.toggle_used)
        # for (
        #     addr_usage_state
        # ) in (
        #     AddressUsageStateFilter.__members__.values()
        # ):  # type: AddressUsageStateFilter
        #     self.used_button.addItem(addr_usage_state.ui_text())
        self.std_model = MyStandardItemModel(
            self,
            drag_key="txids",
            get_file_data=self.get_file_data,
            file_extension="tx",
        )
        self.proxy = MySortModel(self, sort_role=self.ROLE_SORT_ORDER)
        self.proxy.setSourceModel(self.std_model)
        self.setModel(self.proxy)
        self.update()
        self.sortByColumn(HistList.Columns.STATUS, Qt.AscendingOrder)
        self.signals.addresses_updated.connect(self.update)
        self.signals.labels_updated.connect(self.update_with_filter)
        self.signals.category_updated.connect(self.update_with_filter)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def get_file_data(self, txid):
        wallets: List[Wallet] = self.signals.get_wallets().values()
        for wallet in wallets:
            txdetails = wallet.get_tx(txid)
        if txdetails:
            return serialized_to_hex(txdetails.transaction.serialize())

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
                if index.column() != self.key_column:
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
        # This tells the widget to accept file drops
        elif event.mimeData().hasUrls():
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
            hit_address = model.data(model.index(index.row(), self.key_column))

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

        elif event.mimeData().hasUrls():
            # Iterate through the list of dropped file URLs
            for url in event.mimeData().urls():
                # Convert URL to local file path
                file_path = url.toLocalFile()
                # Read and print contents of each file
                with open(file_path, "r") as file:
                    self.signals.open_tx.emit(file.read())

        event.ignore()

    def on_double_click(self, idx):
        txid = self.get_role_data_for_current_item(col=0, role=self.ROLE_KEY)
        wallet, tx_details = self._tx_dict[txid]
        self.signals.show_transaction.emit(tx_details)

    def create_toolbar(self, config=None):
        toolbar, menu = self.create_toolbar_with_menu("")
        self.num_label = toolbar.itemAt(0).widget()
        self.button_get_new_address = toolbar.itemAt(1).widget()
        # menu.addToggle(_("Show Filter"), lambda: self.toggle_toolbar(config))

        hbox = self.create_toolbar_buttons()
        toolbar.insertLayout(3, hbox)

        return toolbar

    def get_toolbar_buttons(self):
        return []
        return self.change_button, self.used_button

    def on_hide_toolbar(self):
        self.show_change = AddressTypeFilter.ALL  # type: AddressTypeFilter
        self.show_used = AddressUsageStateFilter.ALL  # type: AddressUsageStateFilter
        self.update()

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

        model = self.std_model
        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            txid = model.data(model.index(row, self.Columns.TXID))
            if txid in update_filter.txids or set(
                model.data(model.index(row, self.Columns.CATEGORIES))
            ) - set(update_filter.categories):
                logger.debug(f"Updating row {row}: {txid}")
                self.refresh_row(txid, row)

    def update(self):
        if self.maybe_defer_update():
            return

        self._tx_dict = {}
        wallets: List[Wallet] = self.signals.get_wallets().values()

        current_key = self.get_role_data_for_current_item(
            col=self.key_column, role=self.ROLE_KEY
        )

        self.proxy.setDynamicSortFilter(
            False
        )  # temp. disable re-sorting after every change
        self.std_model.clear()
        self.update_headers(self.headers)

        num_shown = 0
        set_idx = None
        for wallet in wallets:
            if self.wallet_id and wallet.id != self.wallet_id:
                continue
            tx_list = wallet.get_list_transactions()
            for tx in tx_list:
                # WALLET_ID = enum.auto()
                # AMOUNT = enum.auto()
                # SATOSHIS = enum.auto()
                # BALANCE = enum.auto()
                # TXID = enum.auto()
                self._tx_dict[tx.txid] = [wallet, tx]

                if self.txid_domain is not None and tx.txid not in self.txid_domain:
                    continue

                amount = tx.received - tx.sent
                status = wallet.get_tx_status(tx)

                labels = [""] * len(self.Columns)
                labels[self.Columns.WALLET_ID] = wallet.id
                labels[self.Columns.AMOUNT] = format_satoshis(amount, is_diff=True)
                labels[self.Columns.SATOSHIS] = str(amount)
                labels[self.Columns.BALANCE] = str(0)  # TODO
                labels[self.Columns.TXID] = tx.txid
                items = [QStandardItem(e) for e in labels]

                items[self.Columns.STATUS].setData(status.sort_id, self.ROLE_SORT_ORDER)
                items[self.Columns.WALLET_ID].setData(
                    wallet.id, self.ROLE_CLIPBOARD_DATA
                )
                items[self.Columns.AMOUNT].setData(amount, self.ROLE_CLIPBOARD_DATA)
                if amount < 0:
                    items[self.Columns.AMOUNT].setData(
                        QBrush(QColor("red")), Qt.ForegroundRole
                    )
                items[self.Columns.SATOSHIS].setData(amount, self.ROLE_CLIPBOARD_DATA)
                items[self.Columns.BALANCE].setData(0, self.ROLE_CLIPBOARD_DATA)  # TODO
                items[self.Columns.TXID].setData(tx.txid, self.ROLE_CLIPBOARD_DATA)

                # # align text and set fonts
                # for i, item in enumerate(items):
                #     item.setTextAlignment(Qt.AlignVCenter)
                #     if i in (self.Columns.TXID,):
                #         item.setFont(QFont(MONOSPACE_FONT))

                self.set_editability(items)

                items[self.key_column].setData(tx.txid, self.ROLE_KEY)
                num_shown += 1
                # add item
                count = self.std_model.rowCount()
                self.std_model.insertRow(count, items)
                self.refresh_row(tx.txid, count)
                idx = self.std_model.index(count, self.Columns.LABEL)
                if tx.txid == current_key:
                    set_idx = QPersistentModelIndex(idx)
        if set_idx:
            self.set_current_idx(set_idx)
        # show/hide self.Columns
        self.filter()
        self.proxy.setDynamicSortFilter(True)
        # update counter
        if self.num_label:
            self.num_label.setText(_("{} transactions").format(num_shown))
        for hidden_column in self.hidden_columns:
            self.hideColumn(hidden_column)

    def refresh_row(self, key, row):
        assert row is not None
        wallet, tx = self._tx_dict[key]
        # STATUS = enum.auto()
        # CATEGORIES = enum.auto()
        # LABEL = enum.auto()

        label = wallet.get_label_for_txid(tx.txid)
        categories = wallet.get_categories_for_txid(tx.txid)
        category = categories[0] if categories else ""
        status = wallet.get_tx_status(tx)
        status_text = (
            datetime.datetime.fromtimestamp(tx.confirmation_time.timestamp).strftime(
                "%Y-%m-%d %H:%M"
            )
            if status.confirmations
            else (TxConfirmationStatus.to_str(status.confirmation_status))
        )

        item = [self.std_model.item(row, col) for col in self.Columns]
        item[self.Columns.STATUS].setText(status_text)
        item[self.Columns.STATUS].setData(
            status.confirmations, self.ROLE_CLIPBOARD_DATA
        )
        item[self.Columns.STATUS].setIcon(read_QIcon(sort_id_to_icon(status.sort_id)))

        item[self.Columns.STATUS].setToolTip(
            f"{status.confirmations} Confirmations"
            if status.confirmations
            else status_text
        )
        item[self.Columns.LABEL].setText(label)
        item[self.Columns.LABEL].setData(label, self.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORIES].setText(category)
        item[self.Columns.CATEGORIES].setData(categories, self.ROLE_CLIPBOARD_DATA)
        item[self.Columns.CATEGORIES].setBackground(CategoryEditor.color(category))

    def create_menu(self, position):
        # is_multisig = isinstance(self.wallet, Multisig_Wallet)
        selected = self.selected_in_column(self.Columns.TXID)
        if not selected:
            return
        multi_select = len(selected) > 1
        txids = [self.item_from_index(item).text() for item in selected]
        menu = QMenu()
        if not multi_select:
            idx = self.indexAt(position)
            if not idx.isValid():
                return
            item = self.item_from_index(idx)
            if not item:
                return
            txid = txids[0]
            menu.addAction(
                _("Details"), lambda: self.signals.show_transaction.emit(txid)
            )
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
            # menu.addAction(_("Request payment"), lambda: self.main_window.receive_at(txid))
            # if self.wallet.can_export():
            #     menu.addAction(_("Private key"), lambda: self.signals.show_private_key(txid))
            # if not is_multisig and not self.wallet.is_watching_only():
            #     menu.addAction(_("Sign/verify message"), lambda: self.signals.sign_verify_message(txid))
            #     menu.addAction(_("Encrypt/decrypt message"), lambda: self.signals.encrypt_message(txid))
            addr_URL = block_explorer_URL(self.config, "tx", txid)
            if addr_URL:
                menu.addAction(_("View on block explorer"), lambda: webopen(addr_URL))

        menu.addAction(
            _("Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
        )

        # run_hook('receive_menu', menu, txids, self.wallet)
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
        txid = edit_key
        wallet, tx = self._tx_dict[txid]

        wallet.labels.set_tx_label(edit_key, text)

        self.signals.labels_updated.emit(
            UpdateFilter(
                txids=[txid],
                addresses=[
                    wallet.get_address_of_txout(txout)
                    for txout in tx.transaction.output()
                ],
            )
        )
