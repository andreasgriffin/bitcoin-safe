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

import enum
import logging
from typing import Any, cast

from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.util import time_logger
from PyQt6.QtCore import QMimeData, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDropEvent, QStandardItem
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTreeView, QWidget

from bitcoin_safe.category_info import CategoryInfo
from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.gui.qt.drag_info import AddressDragInfo
from bitcoin_safe.gui.qt.my_treeview import (
    DropRule,
    MyItemDataRole,
    MySortModel,
    MyStandardItemModel,
    MyTreeView,
    TreeViewWithToolbar,
    header_item,
)
from bitcoin_safe.gui.qt.util import category_color, create_color_circle
from bitcoin_safe.storage import BaseSaveableClass

from ....signals import Signals, UpdateFilter, UpdateFilterReason

logger = logging.getLogger(__name__)


class CategoryList(MyTreeView[CategoryInfo]):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        MyTreeView.__name__: MyTreeView,
    }

    signal_addresses_dropped = cast(SignalProtocol[[AddressDragInfo]], pyqtSignal(AddressDragInfo))

    class Columns(MyTreeView.BaseColumnsEnum):
        ADDRESS_COUNT = enum.auto()
        TXO_COUNT = enum.auto()
        UTXO_COUNT = enum.auto()
        COLOR = enum.auto()
        CATEGORY = enum.auto()
        TXO_BALANCE = enum.auto()
        UTXO_BALANCE = enum.auto()

    filter_columns = [
        Columns.ADDRESS_COUNT,
        Columns.CATEGORY,
    ]
    column_alignments = {
        Columns.ADDRESS_COUNT: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.TXO_COUNT: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.UTXO_COUNT: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.CATEGORY: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.COLOR: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        Columns.TXO_BALANCE: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        Columns.UTXO_BALANCE: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    }

    column_widths: dict[MyTreeView.BaseColumnsEnum, int] = {}
    stretch_column = Columns.CATEGORY
    key_column = Columns.CATEGORY

    @staticmethod
    def cls_kwargs(
        signals: Signals,
        config: UserConfig,
    ):
        return {
            "signals": signals,
            "config": config,
        }

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        category_core: CategoryCore | None = None,
        sort_column: int | None = Columns.CATEGORY,
        sort_order: Qt.SortOrder | None = Qt.SortOrder.AscendingOrder,
        hidden_columns: list[int] | None = None,
        selected_ids: list[str] | None = None,
        _scroll_position=0,
    ):
        """_summary_

        Args:
            config (UserConfig): _description_
            signals (Signals): _description_
            outpoints (List[OutPoint]): _description_
            hidden_columns (_type_, optional): _description_. Defaults to None.
            txout_dict (Dict[str, bdk.TxOut], optional): Can be used to augment the list with infos, if the utxo is not from the own wallet. Defaults to None.
        """
        super().__init__(
            config=config,
            stretch_column=self.stretch_column,
            column_widths=self.column_widths,
            editable_columns=[],
            signals=signals,
            sort_column=sort_column if sort_column is not None else None,
            sort_order=sort_order if sort_order is not None else Qt.SortOrder.AscendingOrder,
            hidden_columns=hidden_columns,
            selected_ids=selected_ids,
            _scroll_position=_scroll_position,
        )
        self.category_core = category_core

        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._source_model = MyStandardItemModel(
            key_column=self.key_column,
            parent=self,
        )
        self.proxy = MySortModel(
            Columns=self.Columns,
            drag_key="tag",
            key_column=self.key_column,
            parent=self,
            source_model=self._source_model,
            sort_role=MyItemDataRole.ROLE_SORT_ORDER,
        )
        self.setModel(self.proxy)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(False)  # Allow user to sort by clicking column headers

        self.update_content()

        # signals
        self.signals.any_wallet_updated.connect(self.update_with_filter)

    def set_category_core(self, category_core: CategoryCore | None):
        """Set category core."""
        self.category_core = category_core
        self.update_content()

    def get_headers(self) -> dict[MyTreeView.BaseColumnsEnum, QStandardItem]:
        """Get headers."""
        return {
            self.Columns.ADDRESS_COUNT: header_item(self.tr("Addresses")),
            self.Columns.UTXO_COUNT: header_item(
                self.tr("UTXOs"), tooltip=self.tr("Number of unspent transaction outputs")
            ),
            self.Columns.TXO_COUNT: header_item(
                self.tr("Tx Outputs"), tooltip=self.tr("Number of spent and unspent transaction outputs")
            ),
            self.Columns.COLOR: header_item(self.tr("Color")),
            self.Columns.CATEGORY: header_item(self.tr("Category")),
            self.Columns.TXO_BALANCE: header_item(
                self.tr("Received"), tooltip=self.tr("Total received (possibly already spent again)")
            ),
            self.Columns.UTXO_BALANCE: header_item(self.tr("Balance"), tooltip=self.tr("Current Balance")),
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

        model = self._source_model
        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            category_info: CategoryInfo = model.data(
                model.index(row, self.key_column), role=MyItemDataRole.ROLE_KEY
            )
            self.refresh_row(category_info, row)

        self._after_update_content()

    def update_content(self):
        """Update content."""
        if not self.category_core:
            return
        if self.maybe_defer_update():
            return

        self._before_update_content()

        # build dicts to look up the outpoints later (fast)
        category_infos = self.category_core.wallet_signals.get_category_infos.emit() or list()

        self._source_model.clear()
        self.update_headers(self.get_headers())
        for i, category_info in enumerate(category_infos):
            items = [QStandardItem() for _ in self.Columns]
            self.set_editability(items)
            items[self.Columns.CATEGORY].setText(category_info.category)
            items[self.Columns.CATEGORY].setData(category_info, role=MyItemDataRole.ROLE_KEY)
            items[self.Columns.CATEGORY].setData(category_info.category, MyItemDataRole.ROLE_CLIPBOARD_DATA)
            items[self.Columns.CATEGORY].setData(i, role=MyItemDataRole.ROLE_SORT_ORDER)

            # add item
            count = self._source_model.rowCount()
            self._source_model.insertRow(count, items)
            self.refresh_row(category_info, count)

        if isinstance(header := self.header(), QHeaderView):
            header.setSectionResizeMode(self.Columns.CATEGORY, QHeaderView.ResizeMode.Interactive)

        self._after_update_content()
        super().update_content()

    def refresh_row(self, key: Any, row: int):
        """Refresh row."""
        if not self.category_core:
            return
        if not isinstance(key, CategoryInfo):
            logger.error(f"Wrong type {key=}")
            return
        assert row is not None

        _items = [self._source_model.item(row, col) for col in self.Columns]
        items = [entry for entry in _items if entry]

        items[self.Columns.ADDRESS_COUNT].setText(str(key.address_count))
        items[self.Columns.ADDRESS_COUNT].setData(key.address_count, MyItemDataRole.ROLE_CLIPBOARD_DATA)

        items[self.Columns.TXO_COUNT].setText(str(key.txo_count))
        items[self.Columns.TXO_COUNT].setData(key.txo_count, MyItemDataRole.ROLE_CLIPBOARD_DATA)

        items[self.Columns.UTXO_COUNT].setText(str(key.utxo_count))
        items[self.Columns.UTXO_COUNT].setData(key.utxo_count, MyItemDataRole.ROLE_CLIPBOARD_DATA)

        for column, balance in [
            (self.Columns.TXO_BALANCE, key.txo_balance),
            (self.Columns.UTXO_BALANCE, key.utxo_balance),
        ]:
            txo_balance_text = str(Satoshis(balance, self.category_core.wallet.network))
            items[column].setText(txo_balance_text)
            color = (
                self.palette().color(self.foregroundRole())
                if balance
                else QColor(255 // 2, 255 // 2, 255 // 2)
            )
            items[column].setForeground(QBrush(color))
            items[column].setData(balance, MyItemDataRole.ROLE_SORT_ORDER)
            items[column].setData(balance, MyItemDataRole.ROLE_CLIPBOARD_DATA)

        color = category_color(key.category)
        items[self.Columns.COLOR].setText(color.name())
        items[self.Columns.COLOR].setData(color.name(), MyItemDataRole.ROLE_CLIPBOARD_DATA)

        items[self.Columns.CATEGORY].setIcon(create_color_circle(color, size=18))

    def get_selected_category_infos(self) -> list[CategoryInfo]:
        """Get selected category infos."""
        items = self.selected_in_column(self.key_column)
        return [x.data(MyItemDataRole.ROLE_KEY) for x in items]

    def get_drop_rules(self) -> list[DropRule]:
        # ─── JSON “drag_addresses” only on items ────────────────────────────
        """Get drop rules."""

        def mime_pred_json_addresses(md: QMimeData) -> bool:
            """Mime pred json addresses."""
            data = self.get_json_mime_data(md)
            return bool(data and data.get("type") == "drag_addresses")

        def handler_json_addresses(tree_view: QTreeView, e: QDropEvent, idx: QModelIndex) -> None:
            """Handler json addresses."""
            e.acceptProposedAction()
            md = e.mimeData()
            if not md:
                e.ignore()
                return
            data = self.get_json_mime_data(md)
            if not isinstance(data, dict):
                e.ignore()
                return
            addresses = data["addresses"]
            proxy_model = tree_view.model()
            if not proxy_model:
                e.ignore()
                return

            category = proxy_model.data(proxy_model.index(idx.row(), self.key_column))
            drag_info = AddressDragInfo([category], addresses)
            self.signal_addresses_dropped.emit(drag_info)

        # ───   JSON “drag_tag Reorder ────────────────────────────
        def mime_pred_json_tag(md: QMimeData) -> bool:
            """Mime pred json tag."""
            data = self.get_json_mime_data(md)
            return bool(data and data.get("type") == "drag_tag")

        def handler_json_tag(view: QTreeView, e: QDropEvent, source_idx: QModelIndex) -> None:
            """Handler json tag."""
            if not self.category_core:
                return
            e.acceptProposedAction()
            md = e.mimeData()
            if not md:
                e.ignore()
                return
            data = self.get_json_mime_data(md)
            if not isinstance(data, dict):
                e.ignore()
                return
            tags = data["tag"]
            if not isinstance(tags, list):
                e.ignore()
                return

            # ── row in proxy ─────────────────────────────────────────────────────
            source_row = source_idx.row() if source_idx.isValid() else self._source_model.rowCount()
            if view.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem:
                source_row += 1

            self.category_core.move_categories(tags, source_row)
            logger.info(str((tags, source_row)))

        return super().get_drop_rules() + [
            DropRule(
                mime_pred=mime_pred_json_addresses,
                allowed_positions=[
                    QAbstractItemView.DropIndicatorPosition.OnItem,
                ],
                handler=handler_json_addresses,
            ),
            DropRule(
                mime_pred=mime_pred_json_tag,
                allowed_positions=[
                    QAbstractItemView.DropIndicatorPosition.AboveItem,
                    QAbstractItemView.DropIndicatorPosition.BelowItem,
                ],
                handler=handler_json_tag,
            ),
        ]

    def get_selected_values(self) -> list[int]:
        """Get selected values."""
        items = self.selected_in_column(self.Columns.UTXO_BALANCE)
        return [x.data(MyItemDataRole.ROLE_CLIPBOARD_DATA) for x in items]


class CategoryListWithToolbar(TreeViewWithToolbar):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        CategoryList.__name__: CategoryList,
    }

    def __init__(
        self, category_list: CategoryList, config: UserConfig, parent: QWidget | None = None
    ) -> None:
        """Initialize instance."""
        super().__init__(category_list, config, parent=parent)
        self.utxo_list = category_list
        self.set_category_core(category_core=category_list.category_core)
        self.create_layout()
        self.utxo_list.signals.language_switch.connect(self.updateUi)
        self.utxo_list.signals.any_wallet_updated.connect(self.update_with_filter)

    def create_toolbar_with_menu(self, title: str):
        """Create toolbar with menu."""
        super().create_toolbar_with_menu(title=title)
        self.search_edit.setVisible(False)

    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        """Update with filter."""
        self.updateUi()

    def updateUi(self):
        """UpdateUi."""
        super().updateUi()

    def set_category_core(self, category_core: CategoryCore | None):
        """Set category core."""
        self.utxo_list.set_category_core(category_core=category_core)
        self.category_core = category_core
        self.default_export_csv_filename = f"category_export_{self.utxo_list.category_core.wallet.id if self.utxo_list.category_core else ''}.csv"
