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

import logging

from bitcoin_safe.gui.qt.dialog_import import file_to_str

from ...config import UserConfig
from ...i18n import translate

logger = logging.getLogger(__name__)

import csv
import enum
import io
import json
import os
import os.path
import tempfile
from decimal import Decimal
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

from .util import do_copy, read_QIcon


class MyMenu(QMenu):
    def __init__(self, config: UserConfig) -> None:
        QMenu.__init__(self)
        self.setToolTipsVisible(True)
        self.config = config

    def addToggle(self, text: str, callback: Callable, *, tooltip="") -> QAction:
        m = self.addAction(text, callback)
        m.setCheckable(True)
        m.setToolTip(tooltip)
        return m


class MyStandardItemModel(QStandardItemModel):
    def __init__(
        self,
        parent,
        drag_key: str = "item",
        drag_keys_to_file_paths=None,
    ) -> None:
        super().__init__(parent)
        self.mytreeview: MyTreeView = parent
        self.drag_key = drag_key
        self.drag_keys_to_file_paths = self.csv_drag_keys_to_file_paths
        if drag_keys_to_file_paths:
            self.drag_keys_to_file_paths = drag_keys_to_file_paths

    def csv_drag_keys_to_file_paths(
        self, drag_keys: Iterable[str], save_directory: Optional[str] = None
    ) -> List[str]:
        """Writes the selected rows in a csv file (the directory is )"""
        file_path = os.path.join(save_directory, f"export.csv") if save_directory else None
        return [self.mytreeview.csv_drag_keys_to_file_path(drag_keys=drag_keys, file_path=file_path)]

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        if index.column() == self.mytreeview.key_column:  # only enable dragging for column 1
            return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled
        else:
            return super().flags(index)

    def mimeData(self, indexes: List[QtCore.QModelIndex]) -> QMimeData:
        mime_data = QMimeData()
        keys = set()
        for index in indexes:
            if index.isValid():
                key = self.item(index.row(), self.mytreeview.key_column).data(role=MyTreeView.ROLE_KEY)
                keys.add(key)

        # set the key data for internal drags
        d = {
            "type": f"drag_{self.drag_key}",
            self.drag_key: list(keys),
        }

        json_string = json.dumps(d).encode()
        mime_data.setData("application/json", json_string)

        # set the key data for files

        file_urls = []
        for file_path in self.drag_keys_to_file_paths(keys):
            # Add the file URL to the list
            file_urls.append(QUrl.fromLocalFile(file_path))

        # Set the URLs of the files in the mime data
        mime_data.setUrls(file_urls)

        return mime_data


class MySortModel(QSortFilterProxyModel):
    def __init__(self, parent, *, sort_role: int) -> None:
        super().__init__(parent)
        self._sort_role = sort_role

    def lessThan(self, source_left: QModelIndex, source_right: QModelIndex) -> bool:
        item1 = self.sourceModel().itemFromIndex(source_left)
        item2 = self.sourceModel().itemFromIndex(source_right)
        data1 = item1.data(self._sort_role)
        data2 = item2.data(self._sort_role)
        if data1 is not None and data2 is not None:
            return data1 < data2
        v1 = item1.text()
        v2 = item2.text()
        try:
            return Decimal(v1) < Decimal(v2)
        except:
            return v1 < v2


class ElectrumItemDelegate(QStyledItemDelegate):
    def __init__(self, tv: "MyTreeView") -> None:
        super().__init__(tv)
        self.icon_shift_right = 30
        self.tv = tv
        self.opened = None

        def on_closeEditor(editor: QLineEdit, hint) -> None:
            self.opened = None
            self.tv.is_editor_open = False
            if self.tv._pending_update:
                self.tv.update()

        def on_commitData(editor: QLineEdit) -> None:
            new_text = editor.text()
            idx = QModelIndex(self.opened)
            row, col = idx.row(), idx.column()
            edit_key = self.tv.get_edit_key_from_coordinate(row, col)
            assert edit_key is not None, (idx.row(), idx.column())
            self.tv.on_edited(idx, edit_key=edit_key, text=new_text)

        self.closeEditor.connect(on_closeEditor)
        self.commitData.connect(on_commitData)

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        option.displayAlignment = self.tv.column_alignments.get(index.column(), Qt.AlignmentFlag.AlignLeft)

    def createEditor(self, parent, option: QStyleOptionViewItem, idx: QModelIndex) -> QWidget:
        self.opened = QPersistentModelIndex(idx)
        self.tv.is_editor_open = True
        return super().createEditor(parent, option, idx)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, idx: QModelIndex) -> None:
        custom_data = idx.data(MyTreeView.ROLE_CUSTOM_PAINT)
        if custom_data is None:
            return super().paint(painter, option, idx)
        else:
            custom_data.paint(painter, option, idx)

    def helpEvent(
        self,
        evt: QHelpEvent,
        view: QAbstractItemView,
        option: QStyleOptionViewItem,
        idx: QModelIndex,
    ) -> bool:
        custom_data = idx.data(MyTreeView.ROLE_CUSTOM_PAINT)
        if custom_data is None:
            return super().helpEvent(evt, view, option, idx)
        else:
            if evt.type() == QEvent.ToolTip:
                if custom_data.show_tooltip(evt):
                    return True
        return super().helpEvent(evt, view, option, idx)

    def sizeHint(self, option: QStyleOptionViewItem, idx: QModelIndex) -> QSize:
        custom_data = idx.data(MyTreeView.ROLE_CUSTOM_PAINT)
        if custom_data is None:
            return super().sizeHint(option, idx)
        else:
            # default_size = super().sizeHint(option, idx)
            return custom_data.sizeHint(option, idx)


class MyTreeView(QTreeView):
    on_selection_changed = pyqtSignal()
    signal_update = pyqtSignal()

    ROLE_CLIPBOARD_DATA = Qt.ItemDataRole.UserRole + 100
    ROLE_CUSTOM_PAINT = Qt.ItemDataRole.UserRole + 101
    ROLE_EDIT_KEY = Qt.ItemDataRole.UserRole + 102
    ROLE_FILTER_DATA = Qt.ItemDataRole.UserRole + 103
    ROLE_SORT_ORDER = Qt.ItemDataRole.UserRole + 1000
    ROLE_KEY = Qt.ItemDataRole.UserRole + 1001

    filter_columns: Iterable[int]
    column_alignments: Dict[int, int] = {}

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
        parent: Optional[QWidget] = None,
        stretch_column: Optional[int] = None,
        column_widths: Optional[Dict[int, int]] = None,
        editable_columns: Optional[Sequence[int]] = None,
    ) -> None:
        parent = parent
        super().__init__(parent)
        self.std_model = MyStandardItemModel(parent)
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

        self.setRootIsDecorated(False)  # remove left margin

        # When figuring out the size of columns, Qt by default looks at
        # the first 1000 rows (at least if resize mode is QHeaderView.ResizeToContents).
        # This would be REALLY SLOW, and it's not perfect anyway.
        # So to speed the UI up considerably, set it to
        # only look at as many rows as currently visible.
        self.header().setResizeContentsPrecision(0)
        self._pending_update = False
        self._forced_update = False

        self._default_bg_brush = QStandardItem().background()
        self.proxy = QSortFilterProxyModel()

        # Here's where we set the font globally for the view
        font = QFont("Arial", 10)
        self.setFont(font)

        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragEnabled(True)  # this must be after the other drag toggles

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
                self.viewport().render(temp_pixmap, QPoint(), QRegion(rect))
                painter.drawPixmap(0, int(current_height), temp_pixmap)
                current_height += rect.height()
            painter.end()

            cursor_pos = self.mapFromGlobal(QCursor.pos())
            visual_rect = self.visualRect(indexes[0]).bottomLeft()
            hotspot_pos = cursor_pos - visual_rect
            # the y offset is always off, so just set it completely to 0
            hotspot_pos.setY(0)
            drag.setPixmap(pixmap)
            drag.setHotSpot(hotspot_pos)

            drag.exec(action)

    def create_menu(self, position: QPoint) -> None:
        selected = self.selected_in_column(self.key_column)
        if not selected:
            return
        menu = QMenu()

        menu.addAction(
            self.tr("Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
        )

        # run_hook('receive_menu', menu, addrs, self.wallet)
        menu.exec(self.viewport().mapToGlobal(position))

    def set_editability(self, items: List[QStandardItem]) -> None:
        for idx, i in enumerate(items):
            i.setEditable(idx in self.editable_columns)

    def selected_in_column(self, column: int) -> List[QModelIndex]:
        items = self.selectionModel().selectedIndexes()
        return list(x for x in items if x.column() == column)

    def current_row_in_column(self, column: int) -> Optional[QModelIndex]:
        idx = self.selectionModel().currentIndex()
        if idx.isValid():
            # Retrieve data for a specific role from the current index
            # Replace 'YourSpecificRole' with the role you are interested in
            # For example, QtCore.Qt.DisplayRole for the display text
            return idx.sibling(idx.row(), column)
        return None

    def get_role_data_for_current_item(self, *, col, role) -> Any:
        idx = self.selectionModel().currentIndex()
        idx = idx.sibling(idx.row(), col)
        item = self.item_from_index(idx)
        if item:
            return item.data(role)

    def model(self) -> MyStandardItemModel:
        return super().model()

    def itemDelegate(self) -> ElectrumItemDelegate:
        return super().itemDelegate()

    def item_from_index(self, idx: QModelIndex) -> Optional[QStandardItem]:
        model = self.model()
        if isinstance(model, QSortFilterProxyModel):
            idx = model.mapToSource(idx)
            return model.sourceModel().itemFromIndex(idx)
        else:
            return model.itemFromIndex(idx)

    def original_model(self) -> QAbstractItemModel:
        model = self.model()
        if isinstance(model, QSortFilterProxyModel):
            return model.sourceModel()
        else:
            return model

    def set_current_idx(self, set_current: QPersistentModelIndex) -> None:
        if set_current:
            assert isinstance(set_current, QPersistentModelIndex)
            assert set_current.isValid()
            self.selectionModel().select(
                QModelIndex(set_current), QItemSelectionModel.SelectionFlag.SelectCurrent
            )

    def select_row(self, content, column, role=Qt.ItemDataRole.DisplayRole) -> None:
        return self.select_rows([content], column, role)

    def select_rows(
        self, content_list, column, role=Qt.ItemDataRole.DisplayRole, clear_previous_selection=True
    ) -> None:
        last_selected_index = None
        model = self.model()
        selection_model = self.selectionModel()
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
        self.viewport().update()

    def update_headers(
        self,
        headers: Union[Dict[Any, str], Iterable[str]],
    ) -> None:
        # Get the current sorting column and order
        current_column = self.header().sortIndicatorSection()
        current_order = self.header().sortIndicatorOrder()

        # headers is either a list of column names, or a dict: (col_idx->col_name)
        if not isinstance(headers, dict):  # convert to dict
            headers = dict(enumerate(headers))
        col_names = [headers[col_idx] for col_idx in sorted(headers.keys())]
        self.original_model().setHorizontalHeaderLabels(col_names)
        self.sortByColumn(current_column, current_order)  # reapply old sorting
        self.header().setStretchLastSection(False)
        for col_idx in headers:
            sm = (
                QHeaderView.ResizeMode.Stretch
                if col_idx == self.stretch_column or col_idx in self.column_widths.keys()
                else QHeaderView.ResizeMode.ResizeToContents
            )
            self.header().setSectionResizeMode(col_idx, sm)

        for col_idx, width in self.column_widths.items():
            self.header().setSectionResizeMode(col_idx, QHeaderView.ResizeMode.Interactive)
            self.header().resizeSection(col_idx, width)

    def selectionChanged(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        super().selectionChanged(selected, deselected)
        self.on_selection_changed.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.itemDelegate().opened:
            return
        if event.key() in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            self.on_activated(self.selectionModel().currentIndex())
            return
        if event.key() in [Qt.Key.Key_F2]:
            if not self.editable_columns:
                return
            idx = self.selectionModel().currentIndex()
            idx = idx.sibling(idx.row(), list(self.editable_columns)[0])
            self.edit(QModelIndex(QPersistentModelIndex(idx)))
            return

        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and (event.key() == Qt.Key.Key_C):
            selection = self.selectionModel().selection().indexes()
            if selection:
                self.copyKeyRoleToClipboard(set([index.row() for index in selection]))
        else:
            super().keyPressEvent(event)

    def copyKeyRoleToClipboard(self, row_numbers) -> None:
        def get_data(row, col) -> Any:
            model = self.model()
            index = model.index(row, self.key_column)

            if hasattr(model, "data"):
                key = model.data(index, self.ROLE_KEY)
                return key
            else:
                item = self.item_from_index(index)
                if item:
                    key = item.data(self.ROLE_KEY)
                    return key

        row_numbers = sorted(row_numbers)

        stream = io.StringIO()
        for row in row_numbers:
            stream.write(str(get_data(row, self.ROLE_KEY)) + "\n")  # append newline character after each row
        do_copy(stream.getvalue(), title=f"{len(row_numbers)} rows have been copied as text")

    def get_rows_as_list(self, row_numbers) -> Any:
        def get_data(row, col) -> Any:
            model = self.model()  # assuming this is a QAbstractItemModel or subclass
            index = model.index(row, col)

            if hasattr(model, "data"):
                return model.data(index, self.ROLE_CLIPBOARD_DATA)
            else:
                item = self.item_from_index(index)
                if item:
                    return item.data(self.ROLE_CLIPBOARD_DATA)

        row_numbers = sorted(row_numbers)

        table = []
        headers = [
            self.model().headerData(i, QtCore.Qt.Orientation.Horizontal)
            for i in range(self.model().columnCount())
        ]  # retrieve headers
        table.append(headers)  # write headers to table

        for row in row_numbers:
            row_data = []
            for column in self.Columns:
                row_data.append(get_data(row, column))
            table.append(row_data)

        return table

    def copyRowsToClipboardAsCSV(self, row_numbers) -> None:
        table = self.get_rows_as_list(row_numbers)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerows(table)
        do_copy(stream.getvalue(), title=f"{len(row_numbers)} rows have ben copied as csv")

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
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

    def edit(self, idx, trigger=QAbstractItemView.EditTrigger.AllEditTriggers, event=None) -> bool:
        """
        this is to prevent:
           edit: editing failed
        from inside qt
        """
        return super().edit(idx, trigger, event)

    def on_edited(self, idx: QModelIndex, edit_key, *, text: str) -> None:
        raise NotImplementedError()

    def should_hide(self, row: int) -> bool:
        """row_num is for self.model().

        So if there is a proxy, it is the row number in that!
        """
        return False

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
        return self.get_role_data_from_coordinate(row, col, role=self.ROLE_EDIT_KEY)

    def get_filter_data_from_coordinate(self, row: int, col: int) -> str:
        filter_data = self.get_role_data_from_coordinate(row, col, role=self.ROLE_FILTER_DATA)
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

        should_hide = self.should_hide(row_num)
        if not self.current_filter and should_hide is None:
            # no filters at all, neither date nor search
            is_now_hidden = False
            self.setRowHidden(row_num, QModelIndex(), is_now_hidden)
            return is_now_hidden
        for column in self.filter_columns:
            filter_data = self.get_filter_data_from_coordinate(row_num, column)
            if self.current_filter in filter_data:
                # the filter matched, but the date filter might apply
                is_now_hidden = bool(should_hide)
                self.setRowHidden(row_num, QModelIndex(), is_now_hidden)
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

    def as_csv_string(self, row_numbers: Optional[List[int]] = None, export_all=False) -> str:
        table = self.get_rows_as_list(
            row_numbers=list(range(self.model().rowCount())) if export_all else row_numbers
        )

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerows(table)

        return stream.getvalue()

    def export_as_csv(self, file_path=None) -> None:
        if not file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Export csv", "", "All Files (*);;Text Files (*.csv)"
            )
            if not file_path:
                logger.debug("No file selected")
                return

        self.csv_drag_keys_to_file_path(file_path=file_path, export_all=True)

    def csv_drag_keys_to_file_path(
        self, drag_keys: Optional[Iterable[str]] = None, file_path: str = None, export_all=False
    ) -> str:
        row_numbers: List[int] = []
        if drag_keys and not export_all:
            for row_number in range(0, self.std_model.rowCount()):
                item = self.std_model.item(row_number, self.key_column)
                if item.data(self.ROLE_KEY) in drag_keys:
                    row_numbers.append(row_number)

        # Fetch the serialized data using the drag_keys
        csv_string = self.as_csv_string(row_numbers=row_numbers, export_all=export_all)

        if file_path:
            file_descriptor = os.open(file_path, os.O_CREAT | os.O_WRONLY)
        else:
            # Create a temporary file
            file_descriptor, file_path = tempfile.mkstemp(
                suffix=f".csv",
                prefix=f"{self.std_model.drag_key} ",
            )

        with os.fdopen(file_descriptor, "w") as file:
            file.write(csv_string)

        logger.info(f"CSV Table saved to {file_path}")
        return file_path

    def add_copy_menu(self, menu: QMenu, idx: QModelIndex, force_columns=None) -> QMenu:
        cc = menu.addMenu(self.tr("Copy"))
        for column in self.Columns:
            if self.isColumnHidden(column) and (force_columns is None or column not in force_columns):
                continue
            column_title = self.original_model().horizontalHeaderItem(column).text()
            if not column_title:
                continue
            item_col = self.item_from_index(idx.sibling(idx.row(), column))
            if not item_col:
                continue
            clipboard_data = item_col.data(self.ROLE_CLIPBOARD_DATA)
            if clipboard_data is None:
                clipboard_data = item_col.text().strip()
            cc.addAction(
                column_title,
                lambda text=clipboard_data, title=column_title: self.place_text_on_clipboard(
                    text, title=title
                ),
            )
        return cc

    def place_text_on_clipboard(self, text: str, *, title: str = None) -> None:
        do_copy(text, title=title)

    def showEvent(self, e: QShowEvent) -> None:
        super().showEvent(e)
        if e.isAccepted() and self._pending_update:
            self._forced_update = True
            self.update()
            self._forced_update = False

    def maybe_defer_update(self) -> bool:
        """Returns whether we should defer an update/refresh."""
        defer = not self._forced_update and (not self.isVisible() or self.is_editor_open)
        # side-effect: if we decide to defer update, the state will become stale:
        self._pending_update = defer
        return defer

    def find_row_by_key(self, key: str) -> Optional[int]:
        for row in range(0, self.std_model.rowCount()):
            item = self.std_model.item(row, self.key_column)
            if item.data(self.ROLE_KEY) == key:
                return row
        return None

    def refresh_all(self) -> None:
        if self.maybe_defer_update():
            return
        for row in range(0, self.std_model.rowCount()):
            item = self.std_model.item(row, self.key_column)
            key = item.data(self.ROLE_KEY)
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
            self.std_model.takeRow(row)
        self.hide_if_empty()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            # Iterate through the list of dropped file URLs
            for url in event.mimeData().urls():
                # Convert URL to local file path
                file_path = url.toLocalFile()

                if file_path.endswith(".wallet"):
                    event.accept()
                    return

                if file_path.endswith(".tx") or file_path.endswith(".psbt"):
                    event.accept()

                    return

        if not event.isAccepted():
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        return self.dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            # Iterate through the list of dropped file URLs
            for url in event.mimeData().urls():
                # Convert URL to local file path
                file_path = url.toLocalFile()

                if file_path.endswith(".wallet"):
                    logger.debug(file_path)
                    event.accept()
                    self.signals.open_wallet.emit(file_path)

                if file_path.endswith(".tx") or file_path.endswith(".psbt"):
                    logger.debug(file_path)
                    event.accept()

                    data = Data.from_str(file_to_str(file_path), self.config.network)
                    self.signals.open_tx_like.emit(data.data)

        if not event.isAccepted():
            event.ignore()

    def update(self) -> None:
        super().update()
        logger.debug(f"{self.__class__.__name__} done updating")
        self.signal_update.emit()


class SearchableTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.searchable_list: MyTreeView


class TreeViewWithToolbar(SearchableTab):
    def __init__(self, searchable_list: MyTreeView, config: UserConfig, parent: QWidget = None) -> None:
        super().__init__(parent=parent)
        self.config = config
        self.toolbar_is_visible = False
        self.searchable_list = searchable_list

        # signals
        self.searchable_list.signal_update.connect(self.update)
        # in searchable_list signal_update will be sent after the update. and since this
        # is relevant for the balance to show, i need to update also the balance label
        # which is done in updateUi
        self.searchable_list.signal_update.connect(self.updateUi)

    def create_layout(self) -> None:
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.create_toolbar_with_menu("")
        self.layout().addLayout(self.toolbar)
        self.layout().addWidget(self.searchable_list)

    def create_toolbar_with_menu(self, title):
        self.menu = MyMenu(self.config)
        self.action_export_as_csv = self.menu.addAction("", self.searchable_list.export_as_csv)

        toolbar_button = QToolButton()
        toolbar_button.clicked.connect(lambda: self.menu.exec(QCursor.pos()))
        toolbar_button.setIcon(read_QIcon("preferences.png"))
        toolbar_button.setMenu(self.menu)
        toolbar_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toolbar = QHBoxLayout()

        self.balance_label = QLabel()

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
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
