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

import csv
import enum
import io
import json
import logging
import os
import os.path
import tempfile
from decimal import Decimal
from functools import partial
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Type, Union

from bitcoin_qr_tools.data import Data
from PyQt6 import QtCore
from PyQt6.QtCore import (
    QAbstractItemModel,
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
    QFont,
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
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.signals import Signals
from bitcoin_safe.util import str_to_qbytearray, unique_elements
from bitcoin_safe.wallet import TxStatus

from ...config import UserConfig
from ...i18n import translate
from ...signals import TypedPyQtSignalNo
from .util import do_copy, read_QIcon

logger = logging.getLogger(__name__)


def needs_frequent_flag(status: TxStatus | None) -> bool:
    if not status:
        return True

    if status.confirmations() < 6:
        return True
    return False


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
        QMenu.__init__(self)
        self.setToolTipsVisible(True)
        self.config = config

    def addToggle(self, text: str, callback: Callable, *, tooltip="") -> QAction:
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
        super().__init__(parent)
        self.key_column = key_column

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        if index.column() == self.key_column:  # only enable dragging for column 1
            return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled
        else:
            return super().flags(index)


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
        self._source_model = sourceModel
        super().setSourceModel(sourceModel)

    def sourceModel(self) -> MyStandardItemModel:
        return self._source_model

    def lessThan(self, source_left: QModelIndex, source_right: QModelIndex) -> bool:
        item1 = self.sourceModel().itemFromIndex(source_left)
        item2 = self.sourceModel().itemFromIndex(source_right)

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
        self._source_model.clear()
        # super().close()

    def item_from_index(self, idx: QModelIndex) -> Optional[QStandardItem]:
        return self.sourceModel().itemFromIndex(self.mapToSource(idx))

    def get_rows_as_list(
        self, drag_keys: List[str] | None, order: CSVOrderTpye = CSVOrderTpye.proxy_order
    ) -> Any:
        "if drag_keys is None, then all rows"

        def get_data(
            row, col, role=MyItemDataRole.ROLE_CLIPBOARD_DATA, model: MyStandardItemModel | MySortModel = self
        ) -> Any:
            index = model.index(row, col)
            item = self.item_from_index(index)
            if item:
                return item.data(role)

        # collect data
        proxy_ordered_dict: Dict[str, List[str]] = {}
        for row in range(self.rowCount()):
            drag_key = get_data(row, self.key_column, role=self.role_drag_key)
            if drag_keys is None or get_data(row, self.key_column, role=self.role_drag_key) in drag_keys:
                row_data = []
                for column in self.Columns:
                    row_data.append(get_data(row, column))
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
            for row in range(self._source_model.rowCount()):
                drag_key = get_data(row, self.key_column, role=self.role_drag_key, model=self._source_model)
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

    def as_csv_string(self, drag_keys: List[str] | None) -> str:
        table = self.get_rows_as_list(drag_keys=drag_keys)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerows(table)

        return stream.getvalue()

    def csv_drag_keys_to_file_paths(
        self, drag_keys: List[str], save_directory: Optional[str] = None
    ) -> List[str]:
        """Writes the selected rows in a csv file (the directory is )"""
        file_path = os.path.join(save_directory, f"export.csv") if save_directory else None
        return [self.csv_drag_keys_to_file_path(drag_keys=drag_keys, file_path=file_path)]

    def csv_drag_keys_to_file_path(
        self, drag_keys: List[str] | None = None, file_path: str | None = None
    ) -> str:
        "if drag_keys is None, then export all"

        # Fetch the serialized data using the drag_keys
        csv_string = self.as_csv_string(drag_keys=drag_keys)

        if file_path:
            file_descriptor = os.open(file_path, os.O_CREAT | os.O_WRONLY)
        else:
            # Create a temporary file
            file_descriptor, file_path = tempfile.mkstemp(
                suffix=f".csv",
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
                item = self.item_from_index(index.sibling(index.row(), self.key_column))
                if not item:
                    continue
                key = item.data(role=self.role_drag_key)
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


class ElectrumItemDelegate(QStyledItemDelegate):
    def __init__(self, tv: "MyTreeView") -> None:
        super().__init__(tv)
        self.icon_shift_right = 30
        self.tv = tv
        self.opened: Optional[QPersistentModelIndex] = None

        def on_closeEditor(editor: QLineEdit, hint) -> None:
            self.opened = None
            self.tv.is_editor_open = False
            if self.tv._pending_update:
                self.tv.update_content()

        def on_commitData(editor: QLineEdit) -> None:
            new_text = editor.text()
            if not self.opened:
                return
            idx = QModelIndex(self.opened)
            row, col = idx.row(), idx.column()
            edit_key = self.tv.get_edit_key_from_coordinate(row, col)
            assert edit_key is not None, (idx.row(), idx.column())
            self.tv.on_edited(idx, edit_key=edit_key, text=new_text)

        self.closeEditor.connect(on_closeEditor)
        self.commitData.connect(on_commitData)

    def initStyleOption(self, option: QStyleOptionViewItem | None, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        if not option:
            return
        option.displayAlignment = self.tv.column_alignments.get(index.column(), Qt.AlignmentFlag.AlignLeft)

    def createEditor(
        self, parent: Optional[QWidget], option: QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> Optional[QWidget]:
        self.opened = QPersistentModelIndex(index)
        self.tv.is_editor_open = True
        return super().createEditor(parent, option, index)

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, idx: QModelIndex) -> None:
        custom_data = idx.data(MyItemDataRole.ROLE_CUSTOM_PAINT)
        if isinstance(custom_data, HTMLDelegate):
            custom_data.paint(painter, option, idx)
        else:
            super().paint(painter, option, idx)

    def helpEvent(
        self,
        evt: QHelpEvent | None,
        view: QAbstractItemView | None,
        option: QStyleOptionViewItem,
        idx: QModelIndex,
    ) -> bool:
        custom_data = idx.data(MyItemDataRole.ROLE_CUSTOM_PAINT)
        if custom_data is None:
            return super().helpEvent(evt, view, option, idx)
        else:
            if evt and evt.type() == QEvent.Type.ToolTip and isinstance(custom_data, HTMLDelegate):
                if custom_data.show_tooltip(evt):
                    return True
        return super().helpEvent(evt, view, option, idx)

    def sizeHint(self, option: QStyleOptionViewItem, idx: QModelIndex) -> QSize:
        custom_data = idx.data(MyItemDataRole.ROLE_CUSTOM_PAINT)
        if custom_data is None:
            return super().sizeHint(option, idx)
        else:
            # default_size = super().sizeHint(option, idx)
            return custom_data.sizeHint(option, idx)


class MyTreeView(QTreeView):
    signal_selection_changed: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_update: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    filter_columns: Iterable[int]
    column_alignments: Dict[int, Qt.AlignmentFlag] = {}
    hidden_columns: List[int] = []

    key_column = 0

    class BaseColumnsEnum(enum.IntEnum):
        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values) -> int:
            # this is overridden to get a 0-based counter
            return count

    Columns: Type[BaseColumnsEnum]

    def __init__(
        self,
        *,
        config: UserConfig,
        signals: Signals,
        parent: Optional[QWidget] = None,
        stretch_column: Optional[int] = None,
        column_widths: Optional[Dict[BaseColumnsEnum, int]] = None,
        editable_columns: Optional[Sequence[int]] = None,
        sort_column: int | None = None,
        sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        super().__init__(parent)
        self.signals = signals
        self._source_model = MyStandardItemModel(key_column=self.key_column, parent=self)
        self.config = config
        self.stretch_column = stretch_column
        self.column_widths = column_widths if column_widths else {}
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.create_menu)
        self.setUniformRowHeights(True)

        # Control which columns are editable
        if editable_columns is None:
            editable_columns = []
        self.editable_columns = set(editable_columns)
        self.setItemDelegate(ElectrumItemDelegate(self))
        self.current_filter = ""
        self.is_editor_open = False
        self._currently_updating = False
        self._scroll_position = 0

        self.setRootIsDecorated(False)  # remove left margin

        # When figuring out the size of columns, Qt by default looks at
        # the first 1000 rows (at least if resize mode is QHeaderView.ResizeToContents).
        # This would be REALLY SLOW, and it's not perfect anyway.
        # So to speed the UI up considerably, set it to
        # only look at as many rows as currently visible.
        if isinstance(header := self.header(), QHeaderView):
            header.setResizeContentsPrecision(0)
        self._pending_update = False
        self._forced_update = False

        self._default_bg_brush = QStandardItem().background()
        self.proxy = MySortModel(
            key_column=self.key_column,
            Columns=self.Columns,
            parent=self,
            source_model=self._source_model,
            sort_role=MyItemDataRole.ROLE_SORT_ORDER,
        )

        # Here's where we set the font globally for the view
        font = QFont("Arial", 10)
        self.setFont(font)

        self.setAcceptDrops(True)
        if viewport := self.viewport():
            viewport.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragEnabled(True)  # this must be after the other drag toggles

        self._current_column = sort_column if sort_column is not None else self.key_column
        self._current_order = sort_order
        self.sortByColumn(self._current_column, self._current_order)

    def setItemDelegate(self, delegate: ElectrumItemDelegate) -> None:  # type: ignore[override]
        self._item_delegate = delegate
        super().setItemDelegate(delegate)

    def updateUi(self) -> None:
        pass

    def startDrag(self, action: Qt.DropAction) -> None:
        indexes = self.selectedIndexes()
        if indexes:
            drag = QDrag(self)
            mime_data = self.model().mimeData(indexes)
            drag.setMimeData(mime_data)

            total_height = sum(self.visualRect(index).height() for index in indexes)
            max_width = max(self.visualRect(index).width() for index in indexes)

            pixmap = QPixmap(max_width, total_height)
            pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(pixmap)
            current_height = 0
            for index in indexes:
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

            drag.exec(action)

    def create_menu(self, position: QPoint) -> Menu:
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
            idx = self.indexAt(position)
            if not idx.isValid():
                return menu

            self.add_copy_menu(menu, idx, include_columns_even_if_hidden=[self.key_column])

        menu.add_action(
            self.tr("Copy as csv"),
            partial(
                self.copyRowsToClipboardAsCSV,
                [item.data(MySortModel.role_drag_key) for item in selected_items if item],
            ),
            icon=read_QIcon("csv-file.svg"),
        )

        # run_hook('receive_menu', menu, addrs, self.wallet)
        if viewport := self.viewport():
            menu.exec(viewport.mapToGlobal(position))

        return menu

    def add_copy_menu(self, menu: Menu, idx: QModelIndex, include_columns_even_if_hidden=None) -> Menu:
        copy_menu = menu.add_menu(self.tr("Copy"))
        copy_menu.setIcon(read_QIcon("copy.png"))

        for column in self.Columns:
            if self.isColumnHidden(column) and (
                include_columns_even_if_hidden is None or column not in include_columns_even_if_hidden
            ):
                continue
            item = self.sourceModel().horizontalHeaderItem(column)
            if not item:
                continue
            column_title = item.text()
            if not column_title:
                continue
            item_col = self.item_from_index(idx.sibling(idx.row(), column))
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

    def set_editability(self, items: List[QStandardItem]) -> None:
        for idx, i in enumerate(items):
            i.setEditable(idx in self.editable_columns)

    def selected_in_column(self, column: int) -> List[QModelIndex]:
        selection_model = self.selectionModel()
        if not selection_model:
            return []
        items = selection_model.selectedIndexes()
        return list(x for x in items if x.column() == column)

    def current_row_in_column(self, column: int) -> Optional[QModelIndex]:
        selection_model = self.selectionModel()
        if not selection_model:
            return None

        idx = selection_model.currentIndex()
        if idx.isValid():
            # Retrieve data for a specific role from the current index
            # Replace 'YourSpecificRole' with the role you are interested in
            # For example, QtCore.Qt.DisplayRole for the display text
            return idx.sibling(idx.row(), column)
        return None

    def get_role_data_for_current_item(self, *, col, role) -> Any:
        selection_model = self.selectionModel()
        if not selection_model:
            return None

        idx = selection_model.currentIndex()
        idx = idx.sibling(idx.row(), col)
        item = self.item_from_index(idx)
        if item:
            return item.data(role)

    def model(self) -> QAbstractItemModel:
        if self.proxy:
            return self.proxy
        return self._source_model

    def sourceModel(self) -> MyStandardItemModel:
        return self._source_model

    def itemDelegate(self) -> ElectrumItemDelegate:
        return self._item_delegate

    def item_from_index(self, idx: QModelIndex) -> Optional[QStandardItem]:
        model = self.model()
        if isinstance(model, QSortFilterProxyModel):
            return self.sourceModel().itemFromIndex(model.mapToSource(idx))
        else:
            return self.sourceModel().itemFromIndex(idx)

    def set_current_idx(self, set_current: QPersistentModelIndex) -> None:
        if not set_current or not set_current.isValid():
            return
        selection_model = self.selectionModel()
        if not selection_model:
            return
        selection_model.select(QModelIndex(set_current), QItemSelectionModel.SelectionFlag.SelectCurrent)

    def select_row(self, content, column, role: MyItemDataRole = MyItemDataRole.ROLE_KEY) -> None:
        return self.select_rows([content], column, role)

    def select_rows(
        self,
        content_list,
        column,
        role: MyItemDataRole = MyItemDataRole.ROLE_KEY,
        clear_previous_selection=True,
    ) -> None:
        last_selected_index = None
        model = self.model()
        selection_model = self.selectionModel()
        if not selection_model:
            return

        self._currently_updating = True

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
                last_selected_index = index
        if last_selected_index:
            # Scroll to the last selected index
            self.scrollTo(last_selected_index)

        if viewport := self.viewport():
            viewport.update()
        self._currently_updating = False

        self.signal_selection_changed.emit()

    def update_headers(
        self,
        headers: Union[Dict[Any, str], Iterable[str]],
    ) -> None:
        if not isinstance(header := self.header(), QHeaderView):
            return
        # Get the current sorting column and order
        current_column = header.sortIndicatorSection()
        current_order = header.sortIndicatorOrder()

        # headers is either a list of column names, or a dict: (col_idx->col_name)
        if not isinstance(headers, dict):  # convert to dict
            headers = dict(enumerate(headers))
        col_names = [headers[col_idx] for col_idx in sorted(headers.keys())]
        self.sourceModel().setHorizontalHeaderLabels(col_names)
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

    def selectionChanged(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        super().selectionChanged(selected, deselected)
        if self._currently_updating:
            return
        self.signal_selection_changed.emit()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
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
        def get_data(row, col) -> Any:
            model = self.model()
            index = model.index(row, self.key_column)

            if hasattr(model, "data"):
                key = model.data(index, MyItemDataRole.ROLE_KEY)
                return key
            else:
                item = self.item_from_index(index)
                if item:
                    key = item.data(MyItemDataRole.ROLE_KEY)
                    return key

        row_numbers = sorted(row_numbers)

        stream = io.StringIO()
        for row in row_numbers:
            stream.write(
                str(get_data(row, MyItemDataRole.ROLE_KEY)) + "\n"
            )  # append newline character after each row
        do_copy(stream.getvalue(), title=f"{len(row_numbers)} rows have been copied as text")

    def copyRowsToClipboardAsCSV(self, drag_keys: List[str] | None) -> None:
        table = self.proxy.get_rows_as_list(drag_keys)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerows(table)
        do_copy(
            stream.getvalue(),
            title=f"{len(list(drag_keys) ) if drag_keys else self.model().rowCount()  } rows have ben copied as csv",
        )

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:
        if not event:
            return
        idx: QModelIndex = self.indexAt(event.pos())
        if self.proxy:
            idx = self.proxy.mapToSource(idx)
        if not idx.isValid():
            # can happen e.g. before list is populated for the first time
            return

        if idx.column() in self.editable_columns:
            super().mouseDoubleClickEvent(event)
        else:
            self.on_double_click(idx)

    def on_double_click(self, idx: QModelIndex) -> None:
        pass

    def on_activated(self, idx: QModelIndex) -> None:
        # on 'enter' we show the menu
        pt = self.visualRect(idx).bottomLeft()
        pt.setX(50)
        self.customContextMenuRequested.emit(pt)

    def on_edited(self, idx: QModelIndex, edit_key, *, text: str) -> None:
        raise NotImplementedError()

    def get_text_from_coordinate(self, row: int, col: int) -> str:
        idx = self.model().index(row, col)
        item = self.item_from_index(idx)
        if not item:
            return ""
        return item.text()

    def get_role_data_from_coordinate(self, row: int, col: int, *, role) -> Any:
        idx = self.model().index(row, col)
        item = self.item_from_index(idx)
        if not item:
            return None
        role_data = item.data(role)
        return role_data

    def get_edit_key_from_coordinate(self, row: int, col: int) -> Any:
        # overriding this might allow avoiding storing duplicate data
        return self.get_role_data_from_coordinate(row, col, role=MyItemDataRole.ROLE_EDIT_KEY)

    def get_filter_data_from_coordinate(self, row: int, col: int) -> str:
        filter_data = self.get_role_data_from_coordinate(row, col, role=MyItemDataRole.ROLE_FILTER_DATA)
        if filter_data:
            return filter_data
        txt: str = self.get_text_from_coordinate(row, col)
        txt = txt.lower()
        return txt

    def hide_row(self, row_num: int) -> bool:
        """row_num is for self.model(). So if there is a proxy, it is the row
        number in that!

        It returns:  is_now_hidden
        """
        is_now_hidden = False
        if not self.current_filter:
            # no filters at all, neither date nor search
            is_now_hidden = False
            self.setRowHidden(row_num, QModelIndex(), is_now_hidden)
            return is_now_hidden
        for column in self.filter_columns:
            filter_data = self.get_filter_data_from_coordinate(row_num, column)
            if self.current_filter in filter_data:
                # the filter matched, but the date filter might apply
                self.setRowHidden(row_num, QModelIndex(), False)
                break
        else:
            # we did not find the filter in any columns, hide the item
            is_now_hidden = True
            self.setRowHidden(row_num, QModelIndex(), True)
        return is_now_hidden

    def filter(self, p=None) -> List[bool]:
        "Returns a [row0_is_now_hidden, row1_is_now_hidden, ...]"
        if p is not None:
            p = p.lower()
            self.current_filter = p
        return self.hide_rows()

    def hide_rows(self) -> List[bool]:
        "Returns a [row0_is_now_hidden, row1_is_now_hidden, ...]"
        return [self.hide_row(row) for row in range(self.model().rowCount())]

    def export_as_csv(self, file_path=None) -> None:
        if not file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self, self.tr("Export csv"), "", self.tr("All Files (*);;Text Files (*.csv)")
            )
            if not file_path:
                logger.info(self.tr("No file selected"))
                return

        self.proxy.csv_drag_keys_to_file_path(file_path=file_path)

    def place_text_on_clipboard(self, text: str, *, title: str | None = None) -> None:
        do_copy(text, title=title)

    def showEvent(self, e: QShowEvent | None) -> None:
        super().showEvent(e)
        if e and e.isAccepted() and self._pending_update:
            self._forced_update = True
            self.update_content()
            self._forced_update = False

    def maybe_defer_update(self) -> bool:
        """Returns whether we should defer an update/refresh."""
        defer = not self._forced_update and (not self.isVisible() or self.is_editor_open)
        # side-effect: if we decide to defer update, the state will become stale:
        self._pending_update = defer
        return defer

    def find_row_by_key(self, key: str) -> Optional[int]:
        for row in range(0, self._source_model.rowCount()):
            item = self._source_model.item(row, self.key_column)
            if item and item.data(MyItemDataRole.ROLE_KEY) == key:
                return row
        return None

    def refresh_all(self) -> None:
        if self.maybe_defer_update():
            return
        for row in range(0, self._source_model.rowCount()):
            item = self._source_model.item(row, self.key_column)
            if not item:
                continue
            key = item.data(MyItemDataRole.ROLE_KEY)
            self.refresh_row(key, row)

    def refresh_row(self, key: str, row: int) -> None:
        pass

    def refresh_item(self, key: str) -> None:
        row = self.find_row_by_key(key)
        if row is not None:
            self.refresh_row(key, row)

    def delete_item(self, key: str) -> None:
        row = self.find_row_by_key(key)
        if row is not None:
            self._source_model.takeRow(row)

    @staticmethod
    def _recognized_files(mime_data: QMimeData) -> List[str]:
        result: List[str] = []
        if mime_data.hasUrls():
            # Iterate through the list of dropped file URLs
            for url in mime_data.urls():
                # Convert URL to local file path
                file_path = url.toLocalFile()
                if file_path.endswith(".wallet") or file_path.endswith(".tx") or file_path.endswith(".psbt"):
                    result.append(file_path)
        return result

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        if not event:
            return
        if (mime_data := event.mimeData()) and self._recognized_files(mime_data):
            event.accept()
            return

        if not event.isAccepted():
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent | None) -> None:
        if not event:
            return
        if (mime_data := event.mimeData()) and self._recognized_files(mime_data):
            event.accept()
            return

        if not event.isAccepted():
            event.ignore()

    def dropEvent(self, event: QDropEvent | None) -> None:
        if not event:
            return
        mime_data = event.mimeData()
        if mime_data:
            file_paths = self._recognized_files(mime_data)
            for file_path in file_paths:
                if file_path.endswith(".wallet"):
                    logger.debug(file_path)
                    event.accept()
                    self.signals.open_wallet.emit(file_path)

                if file_path.endswith(".tx") or file_path.endswith(".psbt"):
                    logger.debug(file_path)
                    event.accept()

                    data = Data.from_str(file_to_str(file_path), network=self.config.network)
                    self.signals.open_tx_like.emit(data.data)

        if not event.isAccepted():
            event.ignore()

    def _save_selection(self):
        self.selected_ids = []
        selection_model = self.selectionModel()
        if not selection_model:
            return

        # Save the current scroll position
        scrollbar = self.verticalScrollBar()
        if scrollbar:
            self._scroll_position = scrollbar.value()

        selected_indexes = selection_model.selectedRows(self.key_column)
        for index in selected_indexes:
            if index.isValid():
                # Map the index to the source model if using a proxy
                source_index = self.proxy.mapToSource(index)
                id = source_index.data(MyItemDataRole.ROLE_KEY)
                if id is not None:
                    self.selected_ids.append(id)

    def _restore_selection(self):
        selection_model = self.selectionModel()
        if not selection_model:
            return

        selection_model.clearSelection()
        scrollbar = self.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(self._scroll_position)  # Restore the scroll position

        # Iterate through all rows in the model to find items with matching IDs
        for row in range(self._source_model.rowCount()):
            index = self._source_model.index(row, self.key_column)
            id = index.data(MyItemDataRole.ROLE_KEY)
            if id in self.selected_ids:
                # Map the source index to the proxy model
                proxy_index = self.proxy.mapFromSource(index)
                # Select the item
                selection_model.select(
                    proxy_index,
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                )

    def _before_update_content(self):
        self._currently_updating = True
        self._save_selection()
        if not isinstance(header := self.header(), QHeaderView):
            return
        self._current_column = header.sortIndicatorSection()
        self._current_order = header.sortIndicatorOrder()
        self.proxy.setDynamicSortFilter(False)  # temp. disable re-sorting after every change

    def _after_update_content(self):
        # the following 2 lines (in this order)
        # call the sorting only once, in the default case
        # since sorting is slow (~1s, for 3k entries), DO NOT CHANGE the order here,
        # or you double the sorting time
        self.proxy.setDynamicSortFilter(True)
        self.sortByColumn(self._current_column, self._current_order)

        # show/hide self.Columns
        self.filter()

        for hidden_column in self.hidden_columns:
            self.hideColumn(hidden_column)

        self._restore_selection()
        # this MUST be after the selection,
        # such that on_selection_change is not triggered
        self._currently_updating = False

    def update_content(self) -> None:
        super().update()
        logger.debug(f"{self.__class__.__name__} done updating")
        # sort again just as before
        self.signal_update.emit()

    @classmethod
    def get_json_mime_data(cls, mime_data: QMimeData) -> Optional[Dict]:
        if mime_data.hasFormat("application/json"):
            data_bytes = mime_data.data("application/json")
            try:
                json_string = data_bytes.data().decode()
                logger.debug(f"dragEnterEvent: {json_string}")
                d = json.loads(json_string)
                return d
            except Exception as e:
                logger.debug(f"{cls.__name__}: {e}")
                return None

        return None

    def close(self):
        self.proxy.close()
        self._source_model.clear()
        self.setParent(None)
        super().close()


class SearchableTab(QWidget):

    def __init__(self, parent=None, **kwargs) -> None:
        super().__init__(parent=parent)

        self.searchable_list: MyTreeView | None = None

    def close(self):
        if self.searchable_list:
            self.searchable_list.close()
        self.searchable_list = None
        self.setParent(None)
        super().close()


class TreeViewWithToolbar(SearchableTab):
    def __init__(
        self, searchable_list: MyTreeView, config: UserConfig, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent=parent)
        self.config = config
        self.toolbar_is_visible = False
        self.searchable_list = searchable_list

        # signals
        self.searchable_list.signal_update.connect(self.update)
        # in searchable_list signal_update will be sent after the update. and since this
        # is relevant for the balance to show, i need to update also the balance label
        # which is done in updateUi

    def create_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.create_toolbar_with_menu("")
        layout.addLayout(self.toolbar)
        layout.addWidget(self.searchable_list)

    def _searchable_list_export_as_csv(self):
        if self.searchable_list:
            self.searchable_list.export_as_csv()

    def create_toolbar_with_menu(self, title):
        self.menu = MyMenu(self.config)
        self.action_export_as_csv = self.menu.add_action(
            "", self._searchable_list_export_as_csv, icon=read_QIcon("csv-file.svg")
        )

        toolbar_button = QToolButton()

        toolbar_button.clicked.connect(partial(self.menu.exec, QCursor.pos()))
        toolbar_button.setIcon(read_QIcon("preferences.svg"))
        toolbar_button.setMenu(self.menu)
        toolbar_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toolbar = QHBoxLayout()

        self.balance_label = QLabel()

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        if self.searchable_list:
            self.search_edit.textChanged.connect(self.searchable_list.filter)

        self.toolbar.addWidget(self.balance_label)
        self.toolbar.addStretch()
        self.toolbar.addWidget(self.search_edit)
        self.toolbar.addWidget(toolbar_button)
        return self.toolbar, self.menu, self.balance_label, self.search_edit, self.action_export_as_csv

    def show_toolbar(self, is_visible: bool, config=None) -> None:
        if is_visible == self.toolbar_is_visible:
            return
        self.toolbar_is_visible = is_visible
        if not is_visible:
            self.on_hide_toolbar()

    def on_hide_toolbar(self) -> None:
        pass

    def toggle_toolbar(self, config=None) -> None:
        self.show_toolbar(not self.toolbar_is_visible, config)

    def updateUi(self) -> None:
        self.search_edit.setPlaceholderText(translate("mytreeview", "Type to filter"))
        self.action_export_as_csv.setText(translate("mytreeview", "Export as CSV"))

    def close(self):
        if self.searchable_list:
            self.searchable_list.close()
            self.searchable_list = None
        self.setParent(None)
        super().close()
