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
# Copyright (C) 2023 The Electrum Developers
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

import csv
import enum
import io
import json
import logging
import os
import os.path
import tempfile
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from functools import partial
from typing import (
    Any,
    Generic,
    NamedTuple,
    TypeVar,
    cast,
)

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.util import str_to_qbytearray
from bitcoin_safe_lib.util import unique_elements
from PyQt6 import QtCore
from PyQt6.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QCursor,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QHelpEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QRegion,
    QShowEvent,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.dialog_import import file_to_str
from bitcoin_safe.gui.qt.html_delegate import HTMLDelegate
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.signals import Signals
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.wallet import TxStatus

from ...config import UserConfig
from ...i18n import translate
from .util import do_copy

logger = logging.getLogger(__name__)


T = TypeVar("T")


def needs_frequent_flag(status: TxStatus | None) -> bool:
    """Needs frequent flag."""
    if not status:
        return True

    return status.do_icon_check_on_chain_height_change()


def header_item(text: str, tooltip: str | None = None) -> QStandardItem:
    """Header item."""
    item = QStandardItem(text)
    if tooltip:
        item.setToolTip(tooltip)
    return item


class MyItemDataRole(enum.IntEnum):
    ROLE_CLIPBOARD_DATA = Qt.ItemDataRole.UserRole + 100
    ROLE_CUSTOM_PAINT = Qt.ItemDataRole.UserRole + 101
    ROLE_EDIT_KEY = Qt.ItemDataRole.UserRole + 102
    ROLE_FILTER_DATA = Qt.ItemDataRole.UserRole + 103
    ROLE_SORT_ORDER = Qt.ItemDataRole.UserRole + 1000
    ROLE_KEY = Qt.ItemDataRole.UserRole + 1001
    ROLE_FREQUENT_UPDATEFLAG = Qt.ItemDataRole.UserRole + 1002


class MyMenu(Menu):
    def __init__(self, config: UserConfig) -> None:
        """Initialize instance."""
        QMenu.__init__(self)
        self.setToolTipsVisible(True)
        self.config = config

    def addToggle(self, text: str, callback: Callable, *, tooltip="") -> QAction:
        """AddToggle."""
        m = self.add_action(text, callback)
        m.setCheckable(True)
        m.setToolTip(tooltip)
        return m


class MyStandardItemModel(QStandardItemModel):
    def __init__(
        self,
        key_column: int,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.key_column = key_column

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Flags."""
        f = super().flags(index)

        # the view needs this on *every* index (and on the root) to show the in-between line
        f |= Qt.ItemFlag.ItemIsDropEnabled

        # drag is still restricted to the key column
        if index.column() == self.key_column:
            f |= Qt.ItemFlag.ItemIsDragEnabled
        return f


class MySortModel(QSortFilterProxyModel):
    role_drag_key = MyItemDataRole.ROLE_CLIPBOARD_DATA

    class CSVOrderTpye(enum.Enum):
        proxy_order = enum.auto()
        source_order = enum.auto()
        selection_order = enum.auto()
        sorted_drag_key = enum.auto()

    def __init__(
        self,
        key_column: int,
        parent,
        source_model: MyStandardItemModel,
        sort_role: int,
        Columns: Iterable[int],
        drag_key: str = "item",
        custom_drag_keys_to_file_paths=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.key_column = key_column
        self._sort_role = sort_role
        self._source_model = source_model
        self.Columns = Columns
        self.drag_key = drag_key
        self.custom_drag_keys_to_file_paths = custom_drag_keys_to_file_paths
        self.setSourceModel(source_model)
        self.setSortRole(sort_role)

    def setSourceModel(self, sourceModel: MyStandardItemModel) -> None:  # type: ignore[override]
        """SetSourceModel."""
        self._source_model = sourceModel
        super().setSourceModel(sourceModel)

    def sourceModel(self) -> MyStandardItemModel:
        """SourceModel."""
        return self._source_model

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """LessThan."""
        item1 = self._source_model.itemFromIndex(left)
        item2 = self._source_model.itemFromIndex(right)

        if not item1 or not item2:
            return bool(item1) < bool(item2)

        data1 = item1.data(self._sort_role)
        data2 = item2.data(self._sort_role)
        if data1 is not None and data2 is not None:
            return data1 < data2
        v1 = item1.text()
        v2 = item2.text()
        try:
            return Decimal(v1) < Decimal(v2)
        except Exception:
            return v1 < v2

    def close(self):
        """Close."""
        self._source_model.clear()
        # super().close()

    def get_rows_as_list(
        self, drag_keys: list[str] | None, order: CSVOrderTpye = CSVOrderTpye.proxy_order
    ) -> Any:
        "if drag_keys is None, then all rows"

        def get_data(
            row,
            col,
            model: MyStandardItemModel | MySortModel,
            role=MyItemDataRole.ROLE_CLIPBOARD_DATA,
        ) -> Any:
            """Get data."""
            if model == self:
                data = self.data(self.index(row, col), role=role)
                return (
                    data
                    if data is not None
                    else self.data(self.index(row, col), role=Qt.ItemDataRole.DisplayRole)
                )
            else:
                if item := self._source_model.itemFromIndex(self._source_model.index(row, col)):
                    data = item.data(role)
                    return data if data is not None else item.text()

        # collect data
        proxy_ordered_dict: dict[str, list[str]] = {}
        for row in range(self.rowCount()):
            drag_key = get_data(row, self.key_column, model=self, role=self.role_drag_key)
            if drag_keys is None or drag_key in drag_keys:
                row_data = []
                for column in self.Columns:
                    row_data.append(get_data(row, column, self))
                proxy_ordered_dict[drag_key] = row_data

        ordered_drag_keys: Iterable[str] = []
        if order == self.CSVOrderTpye.proxy_order:
            ordered_drag_keys = proxy_ordered_dict.keys()
        elif order == self.CSVOrderTpye.selection_order:
            ordered_drag_keys = unique_elements(drag_keys) if drag_keys else proxy_ordered_dict.keys()
        elif order == self.CSVOrderTpye.sorted_drag_key:
            ordered_drag_keys = (
                sorted(unique_elements(drag_keys)) if drag_keys else sorted(proxy_ordered_dict.keys())
            )
        elif order == self.CSVOrderTpye.source_order:
            ordered_drag_keys = []
            for row in range(self.rowCount()):
                drag_key = get_data(row, self.key_column, model=self._source_model, role=self.role_drag_key)
                if drag_key:
                    ordered_drag_keys.append(drag_key)

        # assemble the table
        table = []
        headers = [
            self.headerData(i, QtCore.Qt.Orientation.Horizontal) for i in range(self.columnCount())
        ]  # retrieve headers
        table.append(headers)  # write headers to table
        for drag_key in ordered_drag_keys:
            if _row_data := proxy_ordered_dict.get(drag_key):
                table.append(_row_data)
        return table

    def as_csv_string(self, drag_keys: list[str] | None) -> str:
        """As csv string."""
        table = self.get_rows_as_list(drag_keys=drag_keys)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerows(table)

        return stream.getvalue()

    def csv_drag_keys_to_file_paths(
        self, drag_keys: list[str], save_directory: str | None = None
    ) -> list[str]:
        """Writes the selected rows in a csv file (the directory is )"""
        file_path = os.path.join(save_directory, "export.csv") if save_directory else None
        return [self.csv_drag_keys_to_file_path(drag_keys=drag_keys, file_path=file_path)]

    def csv_drag_keys_to_file_path(
        self, drag_keys: list[str] | None = None, file_path: str | None = None
    ) -> str:
        "if drag_keys is None, then export all"

        # Fetch the serialized data using the drag_keys
        csv_string = self.as_csv_string(drag_keys=drag_keys)

        if file_path:
            file_descriptor = os.open(file_path, os.O_CREAT | os.O_WRONLY)
        else:
            # Create a temporary file
            file_descriptor, file_path = tempfile.mkstemp(
                suffix=".csv",
                prefix=f"{self.drag_key} ",
            )

        with os.fdopen(file_descriptor, "w") as file:
            file.write(csv_string)

        logger.debug(f"CSV Table saved to {file_path}")
        return file_path

    def mimeData(self, indexes: Iterable[QtCore.QModelIndex]) -> QMimeData:
        """_summary_

        Args:
            indexes (Iterable[QtCore.QModelIndex]):
            these are in the order of how they were selected

        Returns:
            QMimeData: _description_
        """
        mime_data = QMimeData()
        keys = list()
        for index in indexes:
            if index.isValid():
                key = self.data(index.sibling(index.row(), self.key_column), role=self.role_drag_key)
                keys.append(key)
        keys = unique_elements(keys)

        # set the key data for internal drags
        d = {
            "type": f"drag_{self.drag_key}",
            self.drag_key: list(keys),
        }

        mime_data.setData("application/json", str_to_qbytearray(json.dumps(d)))

        # set the key data for files

        file_urls = []
        file_paths = (
            self.custom_drag_keys_to_file_paths(keys)
            if self.custom_drag_keys_to_file_paths
            else self.csv_drag_keys_to_file_paths(keys)
        )
        for file_path in file_paths:
            # Add the file URL to the list
            file_urls.append(QUrl.fromLocalFile(file_path))

        # Set the URLs of the files in the mime data
        mime_data.setUrls(file_urls)

        return mime_data

    # below this is not necessary
    # def flags(self, index: QModelIndex) -> Qt.ItemFlag:
    #     # 1) forward all of the normal flags (selectable, enabled, dragEnabled, dropEnabled if source had it)
    #     f = super().flags(index)
    #     # 2) on *every* index (and on the "invalid" index for the root), allow drops
    #     return f | Qt.ItemFlag.ItemIsDropEnabled

    def supportedDropActions(self) -> Qt.DropAction:
        """SupportedDropActions."""
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction | Qt.DropAction.LinkAction

    def canDropMimeData(
        self,
        data: QMimeData | None,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: QModelIndex,
    ) -> bool:
        """Qt calls this to decide whether to show the drop indicator.

        We look at the same rules and see if *any* apply at the current position.
        """
        view = cast(MyTreeView, self.parent())
        pos = view.dropIndicatorPosition()
        viewport = view.viewport()
        if not viewport:
            return False

        for rule in view._drop_rules:
            if data and rule.mime_pred(data) and pos in rule.allowed_positions:
                return True
        return False

    def dropMimeData(
        self,
        data: QMimeData | None,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: QModelIndex,
    ) -> bool:
        # map the proxy‐parent back to the source and let the source handle it
        """DropMimeData."""
        src_parent = self.mapToSource(parent)
        return self.sourceModel().dropMimeData(data, action, row, column, src_parent)


class MyItemDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 24

    def __init__(self, tv: MyTreeView) -> None:
        """Initialize instance."""
        super().__init__(tv)
        self.icon_shift_right = 30
        self.tv = tv
        self.opened: QPersistentModelIndex | None = None

        def on_closeEditor(editor: QLineEdit, hint) -> None:
            """On closeEditor."""
            self.opened = None
            self.tv.is_editor_open = False
            if self.tv._pending_update:
                self.tv.update_content()

        def on_commitData(editor: QLineEdit) -> None:
            """On commitData."""
            new_text = editor.text()
            if not self.opened:
                return

            idx = self.tv._p2s(QModelIndex(self.opened))
            row, col = idx.row(), idx.column()
            edit_key = self.tv.get_edit_key_from_coordinate(row, col)
            assert edit_key is not None, (idx.row(), idx.column())
            self.tv.on_edited(idx, edit_key=edit_key, text=new_text)

        self.closeEditor.connect(on_closeEditor)
        self.commitData.connect(on_commitData)

    def initStyleOption(self, option: QStyleOptionViewItem | None, index: QModelIndex) -> None:
        """InitStyleOption."""
        super().initStyleOption(option, index)
        if not option:
            return
        option.displayAlignment = self.tv.column_alignment(index.column())

    def createEditor(
        self, parent: QWidget | None, option: QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> QWidget | None:
        """CreateEditor."""
        self.opened = QPersistentModelIndex(index)
        self.tv.is_editor_open = True
        return super().createEditor(parent, option, index)

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Paint."""
        custom_data = index.data(MyItemDataRole.ROLE_CUSTOM_PAINT)
        if isinstance(custom_data, HTMLDelegate):
            custom_data.paint(painter, option, index)
        else:
            super().paint(painter, option, index)

    def helpEvent(
        self,
        event: QHelpEvent | None,
        view: QAbstractItemView | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        """HelpEvent."""
        custom_data = index.data(MyItemDataRole.ROLE_CUSTOM_PAINT)
        if custom_data is None:
            return super().helpEvent(event, view, option, index)
        else:
            if event and event.type() == QEvent.Type.ToolTip and isinstance(custom_data, HTMLDelegate):
                if custom_data.show_tooltip(event):
                    return True
        return super().helpEvent(event, view, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """SizeHint."""
        custom_data = index.data(MyItemDataRole.ROLE_CUSTOM_PAINT)
        if custom_data is None:
            orghint = super().sizeHint(option, index)
            return QSize(orghint.width(), max(self.ROW_HEIGHT, orghint.height()))
        else:
            # default_size = super().sizeHint(option, idx)
            return custom_data.sizeHint(option, index)


class DropRule(NamedTuple):
    """
    - `mime_pred`: given the QMimeData, return True if this rule applies at all.
    - `allowed_positions`: a sequence of DropIndicatorPosition where we allow it.
    - `handler`: what to do when the drop happens.
    """

    mime_pred: Callable[[QMimeData], bool]
    allowed_positions: Sequence[QAbstractItemView.DropIndicatorPosition]
    handler: Callable[[QTreeView, QDropEvent, QModelIndex], None]


class MyTreeView(QTreeView, BaseSaveableClass, Generic[T]):
    signal_selection_changed = cast(SignalProtocol[[]], pyqtSignal())
    signal_update = cast(SignalProtocol[[]], pyqtSignal())
    signal_finished_update = cast(SignalProtocol[[]], pyqtSignal())

    filter_columns: Iterable[int]
    column_alignments: dict[int, Qt.AlignmentFlag] = {}

    key_column = 0

    class BaseColumnsEnum(enum.IntEnum):
        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values) -> int:
            # this is overridden to get a 0-based counter
            """Generate next value."""
            return count

    Columns: type[BaseColumnsEnum]

    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        parent: QWidget | None = None,
        stretch_column: int | None = None,
        column_widths: dict[BaseColumnsEnum, int] | None = None,
        editable_columns: Sequence[int] | None = None,
        sort_column: int | None = None,
        sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
        hidden_columns: list[int] | None = None,
        selected_ids: list[str] | None = None,
        _scroll_position: int | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.signals = signals
        self._source_model = MyStandardItemModel(key_column=self.key_column, parent=self)
        self.config = config
        self.hidden_columns = hidden_columns if hidden_columns else []
        self.stretch_column = stretch_column
        self.column_widths = column_widths if column_widths else {}
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.create_menu)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(MyItemDelegate.ROW_HEIGHT - 2, MyItemDelegate.ROW_HEIGHT - 2))
        self._selected_ids_for_next_update: list[Any] | None = selected_ids
        self._selected_ids_role_for_next_update = MyItemDataRole.ROLE_CLIPBOARD_DATA

        # Control which columns are editable
        if editable_columns is None:
            editable_columns = []
        self.editable_columns = set(editable_columns)
        self.setItemDelegate(MyItemDelegate(self))
        self.current_filter = ""
        self.base_hidden_rows: set[int] = set()
        self.is_editor_open = False
        self._currently_updating = False
        self._scroll_position = _scroll_position
        self._header_state: QtCore.QByteArray | None = None
        self._valid_header = False

        self.allow_edit = True

        self.setRootIsDecorated(False)  # remove left margin

        # When figuring out the size of columns, Qt by default looks at
        # the first 1000 rows (at least if resize mode is QHeaderView.ResizeToContents).
        # This would be REALLY SLOW, and it's not perfect anyway.
        # So to speed the UI up considerably, set it to
        # only look at as many rows as currently visible.
        if isinstance(header := self.header(), QHeaderView):
            header.setResizeContentsPrecision(0)
            header.setSectionsMovable(True)
            header.setFirstSectionMovable(True)
        self._pending_update = False
        self._forced_update = False
        self._drop_rules = self.get_drop_rules()

        self._default_bg_brush = QStandardItem().background()
        self.proxy = MySortModel(
            key_column=self.key_column,
            Columns=self.Columns,
            parent=self,
            source_model=self._source_model,
            sort_role=MyItemDataRole.ROLE_SORT_ORDER,
        )

        self.setAcceptDrops(True)
        if viewport := self.viewport():
            viewport.setAcceptDrops(True)
        # this will only work if the 1. column is not hidden
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)  # this must be after the other drag toggles

        self._current_column = sort_column if sort_column is not None else self.key_column
        self._current_order = sort_order
        self.sortByColumn(self._current_column, self._current_order)

        self.setAlternatingRowColors(True)

        # signals
        self.signals.language_switch.connect(self.updateUi)
        self.signals.currency_switch.connect(self.updateUi)

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["hidden_columns"] = self.hidden_columns
        d["_scroll_position"] = (
            scrollbar.value() if (scrollbar := self.verticalScrollBar()) else self._scroll_position
        )
        d["selected_ids"] = self.get_selected_keys(role=MyItemDataRole.ROLE_CLIPBOARD_DATA)
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> MyTreeView:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def get_drop_rules(self) -> list[DropRule]:
        # ─── wallet files anywhere ───────────────────────────────────────────
        """Get drop rules."""

        def mime_pred_wallet(md: QMimeData) -> bool:
            """Mime pred wallet."""
            for url in md.urls():
                if url.toLocalFile().endswith(".wallet"):
                    return True
            return False

        def handler_wallet(tree_view: QTreeView, e: QDropEvent, idx: QModelIndex) -> None:
            """Handler wallet."""
            e.acceptProposedAction()
            md = e.mimeData()
            if not md:
                return
            path = md.urls()[0].toLocalFile()
            self.signals.open_wallet.emit(path)

        # ─── tx/.psbt files only between items ─────────────────────────────
        def mime_pred_tx(md: QMimeData) -> bool:
            """Mime pred tx."""
            for url in md.urls():
                if url.toLocalFile().endswith(".tx") or url.toLocalFile().endswith(".psbt"):
                    return True
            return False

        def handler_tx(tree_view: QTreeView, e: QDropEvent, idx: QModelIndex) -> None:
            """Handler tx."""
            e.acceptProposedAction()
            md = e.mimeData()
            if not md:
                return
            path = md.urls()[0].toLocalFile()
            self.signals.open_tx_like.emit(file_to_str(path))

        return [
            DropRule(
                mime_pred=mime_pred_wallet,
                allowed_positions=[
                    QAbstractItemView.DropIndicatorPosition.OnItem,
                    QAbstractItemView.DropIndicatorPosition.AboveItem,
                    QAbstractItemView.DropIndicatorPosition.BelowItem,
                    QAbstractItemView.DropIndicatorPosition.OnViewport,
                ],
                handler=handler_wallet,
            ),
            DropRule(
                mime_pred=mime_pred_tx,
                allowed_positions=[
                    QAbstractItemView.DropIndicatorPosition.OnItem,
                    QAbstractItemView.DropIndicatorPosition.AboveItem,
                    QAbstractItemView.DropIndicatorPosition.BelowItem,
                    QAbstractItemView.DropIndicatorPosition.OnViewport,
                ],
                handler=handler_tx,
            ),
        ]

    def setItemDelegate(self, delegate: MyItemDelegate) -> None:  # type: ignore[override]
        """SetItemDelegate."""
        self._item_delegate = delegate
        super().setItemDelegate(delegate)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.update_content()

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        """StartDrag."""
        proxy_indexes = self.selectedIndexes()
        if proxy_indexes:
            drag = QDrag(self)
            mime_data = self.proxy.mimeData(proxy_indexes)
            drag.setMimeData(mime_data)

            total_height = sum(self.visualRect(index).height() for index in proxy_indexes)
            max_width = max(self.visualRect(index).width() for index in proxy_indexes)

            pixmap = QPixmap(max_width, total_height)
            pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(pixmap)
            current_height = 0
            for index in proxy_indexes:
                if index.column() != self.key_column:
                    continue
                rect = self.visualRect(index)
                temp_pixmap = QPixmap(rect.size())
                if viewport := self.viewport():
                    viewport.render(temp_pixmap, QPoint(), QRegion(rect))
                painter.drawPixmap(0, int(current_height), temp_pixmap)
                current_height += rect.height()
            painter.end()

            # self.mapFromGlobal(QCursor.pos())
            # self.visualRect(indexes[0]).bottomLeft()
            hotspot_pos = QPoint(0, 0)  # cursor_pos - visual_rect
            # the y offset is always off, so just set it completely to 0
            hotspot_pos.setY(0)
            drag.setPixmap(pixmap)
            drag.setHotSpot(hotspot_pos)

            drag.exec(supportedActions)

    def create_menu(self, position: QPoint) -> Menu:
        """Create menu."""
        menu = Menu()
        # is_multisig = isinstance(self.wallet, Multisig_Wallet)
        selected = self.selected_in_column(self.key_column)
        if not selected:
            return menu
        multi_select = len(selected) > 1

        _selected_items = [self.item_from_index(item) for item in selected]
        selected_items = [item for item in _selected_items if item]

        if not selected:
            current_row = self.current_row_in_column(self.key_column)
            if current_row:
                selected = [current_row]

        if not selected:
            return menu

        multi_select = len(selected) > 1
        if not multi_select:
            idx = self._p2s(self.indexAt(position))
            if not idx.isValid():
                return menu

            self.add_copy_menu(menu, idx, include_columns_even_if_hidden=[self.key_column])

        menu.add_action(
            self.tr("Copy as csv"),
            partial(
                self.copyRowsToClipboardAsCSV,
                [item.data(MySortModel.role_drag_key) for item in selected_items if item],
            ),
            icon=svg_tools.get_QIcon("bi--filetype-csv.svg"),
        )

        # run_hook('receive_menu', menu, addrs, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    def add_copy_menu(self, menu: Menu, source_idx: QModelIndex, include_columns_even_if_hidden=None) -> Menu:
        """Add copy menu."""
        copy_menu = menu.add_menu(self.tr("Copy"))
        copy_menu.setIcon(svg_tools.get_QIcon("bi--copy.svg"))

        for column in self.Columns:
            if self.isColumnHidden(column) and (
                include_columns_even_if_hidden is None or column not in include_columns_even_if_hidden
            ):
                continue
            item = self._source_model.horizontalHeaderItem(column)
            if not item:
                continue
            column_title = item.text()
            if not column_title:
                continue
            item_col = self.item_from_index(source_idx.sibling(source_idx.row(), column))
            if not item_col:
                continue
            clipboard_data = item_col.data(MyItemDataRole.ROLE_CLIPBOARD_DATA)
            if clipboard_data is None:
                clipboard_data = item_col.text().strip()
            if not clipboard_data:
                continue

            action = partial(self.place_text_on_clipboard, text=clipboard_data, title=column_title)
            copy_menu.add_action(column_title, action)
        return copy_menu

    def set_editability(self, items: list[QStandardItem]) -> None:
        """Set editability."""
        for idx, i in enumerate(items):
            i.setEditable(idx in self.editable_columns)

    def selected_in_column(self, column: int) -> list[QModelIndex]:
        """Selected in column."""
        selection_model = self.selectionModel()
        if not selection_model:
            return []
        proxy_indices = [idx for idx in selection_model.selectedIndexes() if idx.column() == column]
        # Map each proxy index back to source
        source_indices = []
        for pidx in proxy_indices:
            sidx = self.proxy.mapToSource(pidx)
            if sidx.isValid():
                source_indices.append(sidx)
        return source_indices

    def current_row_in_column(self, column: int) -> QModelIndex | None:
        """Current row in column."""
        selection_model = self.selectionModel()
        if not selection_model:
            return None

        pidx = selection_model.currentIndex()
        if not pidx.isValid():
            return None

        # get the proxy index for this row/column
        pidx_col = pidx.sibling(pidx.row(), column)
        # map to source
        sidx = self.proxy.mapToSource(pidx_col)
        return sidx if sidx.isValid() else None

    def restrict_selection_to_non_hidden_rows(self) -> None:
        """Remove from the current selection any rows that have been hidden (via
        hideRow/setRowHidden)."""
        sel_model = self.selectionModel()
        if sel_model is None:
            return

        model = self.proxy

        new_selection = QItemSelection()
        last_col = model.columnCount() - 1

        # Iterate over each selected row in column 0
        for idx in sel_model.selectedRows(0):
            row, parent = idx.row(), idx.parent()
            # skip any that are hidden
            if self.isRowHidden(row, parent):
                continue

            # select the entire row from col 0 to last_col
            left = idx.sibling(row, 0)
            right = idx.sibling(row, last_col)
            new_selection.select(left, right)

        # replace the old selection
        sel_model.clearSelection()
        sel_model.select(
            new_selection,
            QItemSelectionModel.SelectionFlag.Rows | QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
        self.signal_selection_changed.emit()

    def get_role_data_for_current_item(self, col: int, role: MyItemDataRole) -> Any:
        """Get role data for current item."""
        selection_model = self.selectionModel()
        if not selection_model:
            return None

        proxy_idx = selection_model.currentIndex()
        item = self.item_from_index(self._p2s(proxy_idx.sibling(proxy_idx.row(), col)))
        if item:
            return item.data(role)

    def itemDelegate(self) -> MyItemDelegate:
        """ItemDelegate."""
        return self._item_delegate

    def _p2s(self, proxy_index: QModelIndex) -> QModelIndex:
        """Map a proxy-model index back to the source-model index.

        Returns an invalid QModelIndex if the mapping fails or proxy_index is invalid.
        """
        if not proxy_index.isValid():
            return QModelIndex()
        source_index = self.proxy.mapToSource(proxy_index)
        return source_index if source_index.isValid() else QModelIndex()

    def _s2p(self, source_index: QModelIndex) -> QModelIndex:
        """Map a source-model index into the proxy model.

        Returns an invalid QModelIndex if the mapping fails or source_index is invalid.
        """
        if not source_index.isValid():
            return QModelIndex()
        proxy_index = self.proxy.mapFromSource(source_index)
        return proxy_index if proxy_index.isValid() else QModelIndex()

    def item_from_index(self, source_idx: QModelIndex) -> QStandardItem | None:
        """Item from index."""
        return self._source_model.itemFromIndex(source_idx)

    def select_row_by_clipboard(self, content: str, scroll_to_last=False) -> None:
        """Select row by clipboard."""
        return self.select_rows(
            [content], self.key_column, role=MyItemDataRole.ROLE_CLIPBOARD_DATA, scroll_to_last=scroll_to_last
        )

    def select_row_by_key(self, content: T, scroll_to_last=False) -> None:
        """Select row by key."""
        return self.select_rows(
            [content], self.key_column, role=MyItemDataRole.ROLE_KEY, scroll_to_last=scroll_to_last
        )

    def select_rows(
        self,
        content_list: Iterable[Any],
        column: int,
        role: MyItemDataRole,
        clear_previous_selection=True,
        scroll_to_last=False,
        retry_next_time=True,
    ) -> None:
        """Select rows."""
        model = self.proxy
        # if the selection was unsuccessfull, then save the selection also for the next update
        selection_model = self.selectionModel()
        if not selection_model:
            return

        self._currently_updating = True
        content_index: QModelIndex | None = None

        if clear_previous_selection:
            selection_model.clear()  # Clear previous selection
        for row in range(model.rowCount()):
            index = model.index(row, column)
            this_content = model.data(index, role)
            if this_content in content_list:
                # Select the item
                selection_model.select(
                    index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
                )
                content_index = index

        if not model.rowCount() or (retry_next_time and content_index is None):
            # schedule selection for next update
            self._selected_ids_for_next_update = list(content_list)
            self._selected_ids_role_for_next_update = role

        if scroll_to_last and content_index:
            self._scroll_position = content_index.row()
            self.scrollTo(content_index)

        if viewport := self.viewport():
            viewport.update()
        self._currently_updating = False

        self.signal_selection_changed.emit()

    def scroll_to(
        self,
        content: Any,
        column: int,
        role: MyItemDataRole,
    ) -> None:
        """Scroll to."""
        model = self.proxy

        for row in range(model.rowCount()):
            index = model.index(row, column)
            this_content = model.data(index, role)
            if this_content == content:
                self.scrollTo(index)
                self._scroll_position = index.row()
                break

    def column_alignment(self, index: int) -> Qt.AlignmentFlag:
        """Column alignment."""
        return self.column_alignments.get(index, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def update_headers(
        self,
        headers: dict[BaseColumnsEnum, QStandardItem],
    ) -> None:
        """Update headers."""
        if not isinstance(header := self.header(), QHeaderView):
            return
        # Get the current sorting column and order
        current_column = header.sortIndicatorSection()
        current_order = header.sortIndicatorOrder()

        sorted_keys = sorted(headers.keys())
        self._source_model.setHorizontalHeaderLabels([headers[key].text() for key in sorted_keys])
        # set tooltips for headers
        for i, key in enumerate(sorted_keys):
            item = headers[key]
            self._source_model.setHeaderData(
                i, Qt.Orientation.Horizontal, item.toolTip(), Qt.ItemDataRole.ToolTipRole
            )
            self._source_model.setHeaderData(
                i,
                Qt.Orientation.Horizontal,
                self.column_alignment(key.value),
                Qt.ItemDataRole.TextAlignmentRole,
            )

        header.setSortIndicator(current_column, current_order)
        self.sortByColumn(current_column, current_order)
        header.setStretchLastSection(False)
        for col_idx in headers:
            sm = (
                QHeaderView.ResizeMode.Stretch
                if col_idx == self.stretch_column or col_idx in self.column_widths.keys()
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(int(col_idx), sm)

        for col_idx, width in self.column_widths.items():
            header.setSectionResizeMode(col_idx, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(col_idx, width)

        if not self._valid_header:
            # initial setting of the header state
            # dont do this every time, because at this point, its the default columns , in default order
            self._header_state = header.saveState()
            self._valid_header = True

    def selectionChanged(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        """SelectionChanged."""
        super().selectionChanged(selected, deselected)
        if self._currently_updating:
            return
        self.signal_selection_changed.emit()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        """KeyPressEvent."""
        if self.itemDelegate().opened:
            return  # type: ignore[unreachable]

        selection_model = self.selectionModel()
        if not event or not selection_model:
            super().keyPressEvent(event)
            return

        if event.key() in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            self.on_activated(selection_model.currentIndex())
            return
        if event.key() in [Qt.Key.Key_F2]:
            if not self.editable_columns:
                return
            idx = selection_model.currentIndex()
            idx = idx.sibling(idx.row(), list(self.editable_columns)[0])
            self.edit(
                QModelIndex(QPersistentModelIndex(idx)), QAbstractItemView.EditTrigger.AllEditTriggers, event
            )
            return

        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and (event.key() == Qt.Key.Key_C):
            selection = selection_model.selection().indexes()
            if selection:
                self.copyKeyRoleToClipboard(set([index.row() for index in selection]))
        else:
            super().keyPressEvent(event)

    def copyKeyRoleToClipboard(self, row_numbers) -> None:
        """CopyKeyRoleToClipboard."""

        def get_data(row, col) -> Any:
            """Get data."""
            model = self.proxy
            proxy_index = model.index(row, self.key_column)
            item = self.item_from_index(source_idx=self._p2s(proxy_index))
            if item:
                key = item.data(MyItemDataRole.ROLE_KEY)
                return key

        row_numbers = sorted(row_numbers)

        stream = io.StringIO()
        for row in row_numbers:
            stream.write(
                str(get_data(row, MyItemDataRole.ROLE_KEY)) + "\n"
            )  # append newline character after each row
        do_copy(
            stream.getvalue(), title=self.tr("{n} rows have been copied as text").format(n=len(row_numbers))
        )

    def copyRowsToClipboardAsCSV(self, drag_keys: list[str] | None) -> None:
        """CopyRowsToClipboardAsCSV."""
        table = self.proxy.get_rows_as_list(drag_keys)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerows(table)
        do_copy(
            stream.getvalue(),
            title=self.tr("{n} rows have ben copied as csv").format(n=len(table)),
        )

    def mouseDoubleClickEvent(self, e: QMouseEvent | None) -> None:
        """MouseDoubleClickEvent."""
        if not e:
            return
        source_idx = self._p2s(self.indexAt(e.pos()))
        if not source_idx.isValid():
            # can happen e.g. before list is populated for the first time
            return

        if source_idx.column() in self.editable_columns:
            super().mouseDoubleClickEvent(e)
        else:
            self.on_double_click(source_idx)

    def on_double_click(self, source_idx: QModelIndex) -> None:
        """On double click."""
        pass

    def on_activated(self, idx: QModelIndex) -> None:
        # on 'enter' we show the menu
        """On activated."""
        pt = self.visualRect(idx).bottomLeft()
        pt.setX(50)
        self.customContextMenuRequested.emit(pt)

    def on_edited(self, source_idx: QModelIndex, edit_key: str, text: str) -> None:
        """On edited."""
        raise NotImplementedError()

    def get_text_from_coordinate(self, row: int, col: int) -> str:
        """Get text from coordinate."""
        item = self.item_from_index(self._source_model.index(row, col))
        if not item:
            return ""
        return item.text()

    def get_role_data_from_coordinate(self, row: int, col: int, role) -> Any:
        """Get role data from coordinate."""
        item = self.item_from_index(self._source_model.index(row, col))
        if not item:
            return None
        role_data = item.data(role)
        return role_data

    def get_edit_key_from_coordinate(self, row: int, col: int) -> Any:
        # overriding this might allow avoiding storing duplicate data
        """Get edit key from coordinate."""
        return self.get_role_data_from_coordinate(row, col, role=MyItemDataRole.ROLE_EDIT_KEY)

    def get_filter_data_from_coordinate(self, row: int, col: int) -> str:
        """Get filter data from coordinate."""
        filter_data = self.get_role_data_from_coordinate(row, col, role=MyItemDataRole.ROLE_FILTER_DATA)
        if filter_data:
            return filter_data
        txt: str = self.get_text_from_coordinate(row, col)
        txt = txt.lower()
        return txt

    def any_needs_frequent_flag(self) -> bool:
        """Any needs frequent flag."""
        for row in range(0, self._source_model.rowCount()):
            item = self._source_model.item(row, self.key_column)
            if item and item.data(MyItemDataRole.ROLE_FREQUENT_UPDATEFLAG):
                return True
        return False

    def hide_row(self, row_num: int) -> bool:
        """row_num is a source model row number."""
        is_now_hidden = row_num in self.base_hidden_rows

        source_index = self._source_model.index(row_num, 0)

        proxy_index = self.proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            # The row is already filtered out by the proxy
            return False

        proxy_row = proxy_index.row()

        if not self.current_filter:
            self.setRowHidden(proxy_row, QModelIndex(), is_now_hidden)
            return is_now_hidden

        for column in self.filter_columns:
            filter_data = self.get_filter_data_from_coordinate(row_num, column)
            if self.current_filter in filter_data:
                self.setRowHidden(proxy_row, QModelIndex(), is_now_hidden)
                break
        else:
            is_now_hidden = True
            self.setRowHidden(proxy_row, QModelIndex(), True)

        return is_now_hidden

    def filter(self, p: str | None = None) -> list[bool]:
        "Returns a [row0_is_now_hidden, row1_is_now_hidden, ...]"
        if p is not None:
            p = p.lower()
            self.current_filter = p
        return self.hide_rows()

    def hide_rows(self) -> list[bool]:
        "Returns a [row0_is_now_hidden, row1_is_now_hidden, ...]"
        return [self.hide_row(row) for row in range(self._source_model.rowCount())]

    def export_as_csv(self, file_path=None, default_filename: str = "export.csv") -> None:
        """Export as csv."""
        if not file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self, self.tr("Export csv"), default_filename, self.tr("All Files (*);;Text Files (*.csv)")
            )
            if not file_path:
                logger.info(self.tr("No file selected"))
                return

        self.proxy.csv_drag_keys_to_file_path(file_path=file_path)

    def place_text_on_clipboard(self, text: str, *, title: str | None = None) -> None:
        """Place text on clipboard."""
        do_copy(text, title=title)

    def showEvent(self, a0: QShowEvent | None) -> None:
        """ShowEvent."""
        super().showEvent(a0)
        if a0 and a0.isAccepted() and self._pending_update:
            self._forced_update = True
            self.update_content()
            self._forced_update = False

    def maybe_defer_update(self) -> bool:
        """Returns whether we should defer an update/refresh."""
        defer = not self._forced_update and (not self.isVisible() or self.is_editor_open)
        # side-effect: if we decide to defer update, the state will become stale:
        self._pending_update = defer
        return defer

    def find_row_by_key(self, key: T) -> int | None:
        """Find row by key."""
        for row in range(0, self._source_model.rowCount()):
            item = self._source_model.item(row, self.key_column)
            if item and item.data(MyItemDataRole.ROLE_KEY) == key:
                return row
        return None

    def refresh_all(self) -> None:
        """Refresh all."""
        if self.maybe_defer_update():
            return
        for row in range(0, self._source_model.rowCount()):
            item = self._source_model.item(row, self.key_column)
            if not item:
                continue
            key = item.data(MyItemDataRole.ROLE_KEY)
            self.refresh_row(key, row)

    def refresh_row(self, key: T, row: int) -> None:
        """Refresh row."""
        pass

    def refresh_item(self, key: T) -> None:
        """Refresh item."""
        row = self.find_row_by_key(key)
        if row is not None:
            self.refresh_row(key, row)

    def delete_item(self, key: T) -> None:
        """Delete item."""
        row = self.find_row_by_key(key)
        if row is not None:
            self._source_model.takeRow(row)

    @staticmethod
    def _recognized_files(mime_data: QMimeData) -> list[str]:
        """Recognized files."""
        result: list[str] = []
        if mime_data.hasUrls():
            # Iterate through the list of dropped file URLs
            for url in mime_data.urls():
                # Convert URL to local file path
                file_path = url.toLocalFile()
                if file_path.endswith(".wallet") or file_path.endswith(".tx") or file_path.endswith(".psbt"):
                    result.append(file_path)
        return result

    def dragEnterEvent(self, e: QDragEnterEvent | None) -> None:
        """DragEnterEvent."""
        super().dragEnterEvent(e)
        if not e:
            return
        md = e.mimeData()
        if not md:
            e.ignore()
            return
        # Accept as soon as any rule says "I know that MIME at all"
        if any(rule.mime_pred(md) for rule in self._drop_rules):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent | None) -> None:
        """DragMoveEvent."""
        super().dragMoveEvent(event)
        if not event:
            return
        md = event.mimeData()
        if not md:
            event.ignore()
            return
        pos = self.dropIndicatorPosition()

        # Accept only if there's a rule whose mime_pred matches
        # and whose allowed_positions include the current pos
        for rule in self._drop_rules:
            if rule.mime_pred(md) and pos in rule.allowed_positions:
                event.acceptProposedAction()
                break
        else:
            event.ignore()

    def dropEvent(self, e: QDropEvent | None) -> None:
        """DropEvent."""
        super().dropEvent(e)
        if e is None or e.isAccepted():
            return

        md = e.mimeData()
        pos = self.dropIndicatorPosition()
        idx = self._p2s(self.indexAt(e.position().toPoint()))

        for rule in self._drop_rules:
            if md and rule.mime_pred(md) and pos in rule.allowed_positions:
                # Hand off to the rule's handler
                rule.handler(self, e, idx)
                return

        e.ignore()

    def _save_selection(self):
        """Save selection."""
        self._selected_ids = []
        selection_model = self.selectionModel()
        if not selection_model:
            return
        if self._selected_ids_for_next_update and self._source_model.rowCount():
            # counterproductive to save values, if it wasnt updated yet (or there is no content)
            return

        # Save the current scroll position
        scrollbar = self.verticalScrollBar()
        if scrollbar:
            self._scroll_position = scrollbar.value()

        selected_indexes = selection_model.selectedRows(self.key_column)
        for proxy_index in selected_indexes:
            if not proxy_index.isValid():
                continue
            id = proxy_index.data(MyItemDataRole.ROLE_CLIPBOARD_DATA)
            if id:
                self._selected_ids.append(id)

    def _restore_selection(self):
        """Restore selection."""
        selection_model = self.selectionModel()
        if not selection_model:
            return

        selection_model.clearSelection()
        scrollbar = self.verticalScrollBar()
        if scrollbar and self._scroll_position is not None:
            scrollbar.setValue(self._scroll_position)  # Restore the scroll position

        select_ids: list[str] | None = None

        if self._selected_ids_for_next_update and self._source_model.rowCount():
            select_ids = self._selected_ids_for_next_update
            self._selected_ids_for_next_update = None
            role = self._selected_ids_role_for_next_update
        else:
            select_ids = self._selected_ids
            role = MyItemDataRole.ROLE_CLIPBOARD_DATA

        if select_ids:
            self.select_rows(select_ids, self.key_column, role=role)

    def _before_update_content(self):
        """Before update content."""
        self._currently_updating = True
        self._save_selection()

        header = self.header()
        if not isinstance(header, QHeaderView):
            return

        self._header_state = header.saveState() if self._valid_header else None
        self._current_column = header.sortIndicatorSection()
        self._current_order = header.sortIndicatorOrder()
        self.proxy.setDynamicSortFilter(False)  # temp. disable re-sorting after every change

    def _after_update_content(self):
        # the following 2 lines (in this order)
        # call the sorting only once, in the default case
        # since sorting is slow (~1s, for 3k entries), DO NOT CHANGE the order here,
        # or you double the sorting time
        """After update content."""
        self.proxy.setDynamicSortFilter(True)
        self.sortByColumn(self._current_column, self._current_order)

        # show/hide self.Columns (must be befoe restoring header)
        self.filter()

        header = self.header()
        if isinstance(header, QHeaderView) and self._header_state and self._valid_header:
            header.restoreState(self._header_state)

        # processEvents is important to ensure the scrollbar updates its values and the restoration works
        self._restore_selection()

        for hidden_column in self.hidden_columns:
            self.hideColumn(hidden_column)

        # this MUST be after the selection,
        # such that on_selection_change is not triggered
        self._currently_updating = False
        self._forced_update = False

        self.signal_finished_update.emit()

    def update_content(self) -> None:
        """Update content."""
        super().update()
        logger.debug(f"{self.__class__.__name__} done updating")
        # sort again just as before
        self.signal_update.emit()

    @classmethod
    def get_json_mime_data(cls, mime_data: QMimeData) -> dict | None:
        """Get json mime data."""
        if mime_data.hasFormat("application/json"):
            data_bytes = mime_data.data("application/json")
            try:
                json_string = data_bytes.data().decode()
                logger.debug("dragEnterEvent")
                d = json.loads(json_string)
                return d
            except Exception as e:
                logger.debug(f"{cls.__name__}: {e}")
                return None

        return None

    def selectionCommand(
        self, index: QtCore.QModelIndex, event: QtCore.QEvent | None = None
    ) -> QtCore.QItemSelectionModel.SelectionFlag:
        """SelectionCommand."""
        if not self.allow_edit:
            return QtCore.QItemSelectionModel.SelectionFlag.NoUpdate

        return super().selectionCommand(index, event)

    def get_selected_keys(self, role=MyItemDataRole.ROLE_KEY) -> list[str]:
        """Get selected keys."""
        items = self.selected_in_column(self.key_column)
        return [x.data(role) for x in items]

    def set_allow_edit(self, allow_edit: bool):
        """Set allow edit."""
        self.allow_edit = allow_edit

    def get_headers(self) -> dict[BaseColumnsEnum, QStandardItem]:
        """Get headers."""
        return {col: header_item(col.name) for col in self.Columns}

    def set_column_hidden(self, col: BaseColumnsEnum, hide: bool):
        """Set column hidden."""
        self.setColumnHidden(col.value, hide)
        if hide and col not in self.hidden_columns:
            self.hidden_columns.append(col)
        if not hide and col in self.hidden_columns:
            self.hidden_columns.remove(col)

    def toggle_column_hidden(self, col: BaseColumnsEnum):
        """Toggle column hidden."""
        self.set_column_hidden(col, col.value not in self.hidden_columns)

    def close(self) -> bool:
        """Close."""
        self.proxy.close()
        self._source_model.clear()
        self.setParent(None)
        return super().close()


class SearchableTab(QWidget):
    def __init__(self, parent=None, **kwargs) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)

        self.searchable_list: MyTreeView | None = None

    def close(self):
        """Close."""
        if self.searchable_list:
            self.searchable_list.close()
        self.searchable_list = None
        self.setParent(None)
        return super().close()


class TreeViewWithToolbar(SearchableTab, BaseSaveableClass):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        MyTreeView.__name__: MyTreeView,
    }

    def __init__(
        self,
        searchable_list: MyTreeView,
        config: UserConfig,
        toolbar_is_visible=False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.config = config
        self.toolbar_is_visible = toolbar_is_visible
        self.searchable_list = searchable_list
        self.default_export_csv_filename = "export.csv"

        # signals
        self.searchable_list.signal_finished_update.connect(self.updateUi)
        # in searchable_list signal_update will be sent after the update. and since this
        # is relevant for the balance to show, i need to update also the balance label
        # which is done in updateUi

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["toolbar_is_visible"] = self.toolbar_is_visible
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> TreeViewWithToolbar:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def create_layout(self) -> None:
        """Create layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.create_toolbar_with_menu("")
        layout.addLayout(self.toolbar)
        layout.addWidget(self.searchable_list)

    def _searchable_list_export_as_csv(self):
        """Searchable list export as csv."""
        if self.searchable_list:
            self.searchable_list.export_as_csv(default_filename=self.default_export_csv_filename)

    def create_toolbar_with_menu(self, title: str):
        """Create toolbar with menu."""
        self.menu = MyMenu(self.config)
        self.action_export_as_csv = self.menu.add_action(
            "", self._searchable_list_export_as_csv, icon=svg_tools.get_QIcon("bi--filetype-csv.svg")
        )
        self.menu_hiddden_columns = self.menu.add_menu(
            "",
        )

        toolbar_button = QToolButton()

        toolbar_button.clicked.connect(partial(self.menu.exec, QCursor.pos()))
        toolbar_button.setIcon(svg_tools.get_QIcon("bi--gear.svg"))
        toolbar_button.setMenu(self.menu)
        toolbar_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toolbar = QHBoxLayout()

        self.balance_label = QLabel()
        self.balance_label.setVisible(False)

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        if self.searchable_list:
            self.search_edit.textChanged.connect(self.searchable_list.filter)

        self.toolbar.addWidget(self.balance_label)
        self.toolbar.addStretch()
        self.toolbar.addWidget(self.search_edit)
        self.toolbar.addWidget(toolbar_button)
        self.fill_menu_hiddden_columns()

    def fill_menu_hiddden_columns(self):
        """Fill menu hiddden columns."""
        self.menu_hiddden_columns.clear()
        if not self.searchable_list:
            return
        for column in self.searchable_list.Columns:
            action = self.menu_hiddden_columns.add_action(
                self.searchable_list.get_headers().get(column, QStandardItem()).text(),
                partial(self.searchable_list.toggle_column_hidden, column),
            )
            action.setCheckable(True)
            action.setChecked(column.value not in self.searchable_list.hidden_columns)

    def show_toolbar(self, is_visible: bool, config=None) -> None:
        """Show toolbar."""
        if is_visible == self.toolbar_is_visible:
            return
        self.toolbar_is_visible = is_visible
        if not is_visible:
            self.on_hide_toolbar()

    def on_hide_toolbar(self) -> None:
        """On hide toolbar."""
        pass

    def toggle_toolbar(self, config=None) -> None:
        """Toggle toolbar."""
        self.show_toolbar(not self.toolbar_is_visible, config)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.search_edit.setPlaceholderText(translate("mytreeview", "Type to filter"))
        self.action_export_as_csv.setText(translate("mytreeview", "Export as CSV"))
        self.menu_hiddden_columns.setTitle(translate("mytreeview", "Visible columns"))

    def close(self) -> bool:
        """Close."""
        if self.searchable_list:
            self.searchable_list.close()
            self.searchable_list = None
        self.setParent(None)
        return super().close()
