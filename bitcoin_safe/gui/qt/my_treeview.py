#!/usr/bin/env python
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

logger = logging.getLogger(__name__)

import enum
import os.path
import time
import sys
import platform
import queue
import traceback
import os
import webbrowser
from decimal import Decimal
from functools import partial, lru_cache, wraps
from typing import (
    NamedTuple,
    Callable,
    Optional,
    TYPE_CHECKING,
    Union,
    List,
    Dict,
    Any,
    Sequence,
    Iterable,
    Tuple,
    Type,
)

from PySide2 import QtWidgets, QtCore
from PySide2.QtGui import (
    QFont,
    QColor,
    QCursor,
    QPixmap,
    QStandardItem,
    QImage,
    QPalette,
    QIcon,
    QFontMetrics,
    QShowEvent,
    QPainter,
    QHelpEvent,
    QMouseEvent,
)
from PySide2.QtCore import Signal
from PySide2.QtCore import (
    Qt,
    QPersistentModelIndex,
    QModelIndex,
    QCoreApplication,
    QItemSelectionModel,
    QThread,
    QSortFilterProxyModel,
    QSize,
    QLocale,
    QAbstractItemModel,
    QEvent,
    QRect,
    QPoint,
    QObject,
)
from PySide2.QtWidgets import (
    QPushButton,
    QLabel,
    QMessageBox,
    QHBoxLayout,
    QAbstractItemView,
    QVBoxLayout,
    QLineEdit,
    QStyle,
    QDialog,
    QGroupBox,
    QButtonGroup,
    QRadioButton,
    QFileDialog,
    QWidget,
    QToolButton,
    QTreeView,
    QPlainTextEdit,
    QHeaderView,
    QApplication,
    QToolTip,
    QTreeWidget,
    QStyledItemDelegate,
    QMenu,
    QStyleOptionViewItem,
    QLayout,
    QLayoutItem,
    QAbstractButton,
    QGraphicsEffect,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QSizePolicy,
)

from .util import read_QIcon, do_copy
from PySide2.QtWidgets import QApplication, QTreeView, QStyledItemDelegate
from PySide2.QtGui import QTextDocument, QAbstractTextDocumentLayout, QPalette
from PySide2.QtCore import QSize, Qt
from ...i18n import _
import csv
import io, json
from PySide2 import QtCore, QtWidgets, QtGui

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
from PySide2.QtCore import QMimeData, QUrl
import tempfile


class MyMenu(QMenu):
    def __init__(self, config):
        QMenu.__init__(self)
        self.setToolTipsVisible(True)
        self.config = config

    def addToggle(self, text: str, callback, *, tooltip=""):
        m = self.addAction(text, callback)
        m.setCheckable(True)
        m.setToolTip(tooltip)
        return m

    def addConfig(
        self, text: str, name: str, default: bool, *, tooltip="", callback=None
    ):
        b = self.config.get(name, default)
        m = self.addAction(
            text, lambda: self._do_toggle_config(name, default, callback)
        )
        m.setCheckable(True)
        m.setChecked(b)
        m.setToolTip(tooltip)
        return m

    def _do_toggle_config(self, name, default, callback):
        b = self.config.get(name, default)
        self.config.set_key(name, not b)
        if callback:
            callback()


def create_toolbar_with_menu(config, title, export_as_csv=None):
    menu = MyMenu(config)
    if export_as_csv:
        menu.addAction(_("Export as CSV"), export_as_csv)

    toolbar_button = QToolButton()
    toolbar_button.clicked.connect(lambda: menu.exec_(QCursor.pos()))
    toolbar_button.setIcon(read_QIcon("preferences.png"))
    toolbar_button.setMenu(menu)
    toolbar_button.setPopupMode(QToolButton.InstantPopup)
    toolbar_button.setFocusPolicy(Qt.NoFocus)
    toolbar = QHBoxLayout()
    toolbar.addWidget(QLabel(title))
    toolbar.addStretch()
    toolbar.addWidget(toolbar_button)
    return toolbar, menu


class MyStandardItemModel(QStandardItemModel):
    def __init__(
        self, parent, drag_key="addresses", get_file_data=None, file_extension="dat"
    ):
        super().__init__(parent)
        self.drag_key = drag_key
        self.get_file_data = get_file_data
        self.file_extension = file_extension

    def flags(self, index):
        if (
            index.column() == self.parent().key_column
        ):  # only enable dragging for column 1
            return super().flags(index) | Qt.ItemIsDragEnabled
        else:
            return super().flags(index)

    def mimeData(self, indexes):
        mime_data = QMimeData()
        keys = set()
        for index in indexes:
            if index.isValid():
                key = self.item(index.row(), self.parent().key_column).data(
                    role=MyTreeView.ROLE_KEY
                )
                keys.add(key)

        # set the key data for internal drags
        d = {
            "type": f"drag_{self.drag_key}",
            self.drag_key: [],
        }

        for key in keys:
            d[self.drag_key].append(key)

        json_string = json.dumps(d).encode()
        mime_data.setData("application/json", json_string)

        # set the key data for files

        # List to store the file URLs
        if self.get_file_data:
            file_urls = []

            # Iterate through indexes to fetch serialized data using drag keys
            for key in keys:
                # Fetch the serialized data using the drag_key
                data_item = self.get_file_data(key)
                if not data_item:
                    continue

                # Create a temporary file
                file_handle, file_path = tempfile.mkstemp(
                    suffix=f"_{key}.{self.file_extension}", prefix=""
                )

                # Write the serialized data to the file
                with os.fdopen(file_handle, "w") as file:
                    file.write(data_item)

                # Add the file URL to the list
                file_urls.append(QUrl.fromLocalFile(file_path))

            # Set the URLs of the files in the mime data
            mime_data.setUrls(file_urls)

        return mime_data


class MySortModel(QSortFilterProxyModel):
    def __init__(self, parent, *, sort_role):
        super().__init__(parent)
        self._sort_role = sort_role

    def lessThan(self, source_left: QModelIndex, source_right: QModelIndex):
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
    def __init__(self, tv: "MyTreeView"):
        super().__init__(tv)
        self.icon_shift_right = 30
        self.tv = tv
        self.opened = None

        def on_closeEditor(editor: QLineEdit, hint):
            self.opened = None
            self.tv.is_editor_open = False
            if self.tv._pending_update:
                self.tv.update()

        def on_commitData(editor: QLineEdit):
            new_text = editor.text()
            idx = QModelIndex(self.opened)
            row, col = idx.row(), idx.column()
            edit_key = self.tv.get_edit_key_from_coordinate(row, col)
            assert edit_key is not None, (idx.row(), idx.column())
            self.tv.on_edited(idx, edit_key=edit_key, text=new_text)

        self.closeEditor.connect(on_closeEditor)
        self.commitData.connect(on_commitData)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = self.tv.column_alignments.get(
            index.column(), Qt.AlignLeft
        )

    def createEditor(self, parent, option, idx):
        self.opened = QPersistentModelIndex(idx)
        self.tv.is_editor_open = True
        return super().createEditor(parent, option, idx)

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, idx: QModelIndex
    ) -> None:
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

    ROLE_CLIPBOARD_DATA = Qt.UserRole + 100
    ROLE_CUSTOM_PAINT = Qt.UserRole + 101
    ROLE_EDIT_KEY = Qt.UserRole + 102
    ROLE_FILTER_DATA = Qt.UserRole + 103
    ROLE_SORT_ORDER = Qt.UserRole + 1000
    ROLE_KEY = Qt.UserRole + 1001

    filter_columns: Iterable[int]
    column_alignments: Dict[int, int] = {}

    key_column = 0

    class BaseColumnsEnum(enum.IntEnum):
        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values):
            # this is overridden to get a 0-based counter
            return count

    Columns: Type[BaseColumnsEnum]

    def __init__(
        self,
        *,
        parent: Optional[QWidget] = None,
        config=None,
        stretch_column: Optional[int] = None,
        editable_columns: Optional[Sequence[int]] = None,
    ):
        parent = parent
        super().__init__(parent)
        self.config = config
        self.stretch_column = stretch_column
        self.setContextMenuPolicy(Qt.CustomContextMenu)
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
        self.toolbar_shown = False

        # When figuring out the size of columns, Qt by default looks at
        # the first 1000 rows (at least if resize mode is QHeaderView.ResizeToContents).
        # This would be REALLY SLOW, and it's not perfect anyway.
        # So to speed the UI up considerably, set it to
        # only look at as many rows as currently visible.
        self.header().setResizeContentsPrecision(0)

        self._pending_update = False
        self._forced_update = False

        self._default_bg_brush = QStandardItem().background()
        self.proxy = None  # history, and address tabs use a proxy

        # Here's where we set the font globally for the view
        font = QFont("Arial", 10)
        self.setFont(font)

    def create_menu(self, position: QPoint) -> None:
        selected = self.selected_in_column(self.Columns.ADDRESS)
        if not selected:
            return
        menu = QMenu()

        menu.addAction(
            _("Copy as csv"),
            lambda: self.copyRowsToClipboardAsCSV([r.row() for r in selected]),
        )

        # run_hook('receive_menu', menu, addrs, self.wallet)
        menu.exec_(self.viewport().mapToGlobal(position))

    def set_editability(self, items):
        for idx, i in enumerate(items):
            i.setEditable(idx in self.editable_columns)

    def selected_in_column(self, column: int):
        items = self.selectionModel().selectedIndexes()
        return list(x for x in items if x.column() == column)

    def get_role_data_for_current_item(self, *, col, role) -> Any:
        idx = self.selectionModel().currentIndex()
        idx = idx.sibling(idx.row(), col)
        item = self.item_from_index(idx)
        if item:
            return item.data(role)

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

    def set_current_idx(self, set_current: QPersistentModelIndex):
        if set_current:
            assert isinstance(set_current, QPersistentModelIndex)
            assert set_current.isValid()
            self.selectionModel().select(
                QModelIndex(set_current), QItemSelectionModel.SelectCurrent
            )

    def select_rows(self, content, column, role=Qt.DisplayRole):
        last_selected_index = None
        model = self.model()
        selection_model = self.selectionModel()
        for row in range(model.rowCount()):
            index = model.index(row, column)
            this_content = model.data(index, role)
            if this_content == content:
                # Select the item
                selection_model.select(
                    index, QItemSelectionModel.Select | QItemSelectionModel.Rows
                )
                last_selected_index = index
        if last_selected_index:
            # Scroll to the last selected index
            self.scrollTo(last_selected_index)

    def update_headers(self, headers: Union[List[str], Dict[int, str]]):
        # headers is either a list of column names, or a dict: (col_idx->col_name)
        if not isinstance(headers, dict):  # convert to dict
            headers = dict(enumerate(headers))
        col_names = [headers[col_idx] for col_idx in sorted(headers.keys())]
        self.original_model().setHorizontalHeaderLabels(col_names)
        self.header().setStretchLastSection(False)
        for col_idx in headers:
            sm = (
                QHeaderView.Stretch
                if col_idx == self.stretch_column
                else QHeaderView.ResizeToContents
            )
            self.header().setSectionResizeMode(col_idx, sm)

    def keyPressEvent(self, event):
        if self.itemDelegate().opened:
            return
        if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
            self.on_activated(self.selectionModel().currentIndex())
            return
        if event.key() in [Qt.Key_F2]:
            if not self.editable_columns:
                return
            idx = self.selectionModel().currentIndex()
            idx = idx.sibling(idx.row(), list(self.editable_columns)[0])
            self.edit(QModelIndex(QPersistentModelIndex(idx)))
            return

        if (event.modifiers() & Qt.ControlModifier) and (event.key() == Qt.Key_C):
            selection = self.selectionModel().selection().indexes()
            if selection:
                self.copyKeyRoleToClipboard(set([index.row() for index in selection]))
        else:
            super().keyPressEvent(event)

    def copyKeyRoleToClipboard(self, row_numbers):
        def get_data(row, col):
            model = self.original_model()
            index = model.index(row, self.key_column)

            if hasattr(model, "data"):
                key = model.data(index, self.key_role)
                return key
            else:
                item = self.item_from_index(index)
                if item:
                    key = item.data(self.key_role)
                    return key

        row_numbers = sorted(row_numbers)

        stream = io.StringIO()
        for row in row_numbers:
            stream.write(
                get_data(row, self.key_role) + "\n"
            )  # append newline character after each row
        do_copy(
            stream.getvalue(), title=f"{len(row_numbers)} rows have been copied as text"
        )

    def get_rows_as_csv(self, row_numbers):
        def get_data(row, col):
            model = (
                self.original_model()
            )  # assuming this is a QAbstractItemModel or subclass
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
            self.model().headerData(i, QtCore.Qt.Horizontal)
            for i in range(self.model().columnCount())
        ]  # retrieve headers
        table.append(headers)  # write headers to table

        for row in row_numbers:
            row_data = []
            for column in self.Columns:
                row_data.append(get_data(row, column))
            table.append(row_data)

        return table

    def copyRowsToClipboardAsCSV(self, row_numbers):
        table = self.get_rows_as_csv(row_numbers)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerows(table)
        do_copy(
            stream.getvalue(), title=f"{len(row_numbers)} rows have ben copied as csv"
        )

    def mouseDoubleClickEvent(self, event: QMouseEvent):
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

    def on_double_click(self, idx):
        pass

    def on_activated(self, idx):
        # on 'enter' we show the menu
        pt = self.visualRect(idx).bottomLeft()
        pt.setX(50)
        self.customContextMenuRequested.emit(pt)

    def edit(self, idx, trigger=QAbstractItemView.AllEditTriggers, event=None):
        """
        this is to prevent:
           edit: editing failed
        from inside qt
        """
        return super().edit(idx, trigger, event)

    def on_edited(self, idx: QModelIndex, edit_key, *, text: str) -> None:
        raise NotImplementedError()

    def should_hide(self, row):
        """
        row_num is for self.model(). So if there is a proxy, it is the row number
        in that!
        """
        return False

    def get_text_from_coordinate(self, row, col) -> str:
        idx = self.model().index(row, col)
        item = self.item_from_index(idx)
        return item.text()

    def get_role_data_from_coordinate(self, row, col, *, role) -> Any:
        idx = self.model().index(row, col)
        item = self.item_from_index(idx)
        role_data = item.data(role)
        return role_data

    def get_edit_key_from_coordinate(self, row, col) -> Any:
        # overriding this might allow avoiding storing duplicate data
        return self.get_role_data_from_coordinate(row, col, role=self.ROLE_EDIT_KEY)

    def get_filter_data_from_coordinate(self, row, col) -> str:
        filter_data = self.get_role_data_from_coordinate(
            row, col, role=self.ROLE_FILTER_DATA
        )
        if filter_data:
            return filter_data
        txt = self.get_text_from_coordinate(row, col)
        txt = txt.lower()
        return txt

    def hide_row(self, row_num) -> bool:
        """
        row_num is for self.model(). So if there is a proxy, it is the row number
        in that!

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

    def create_toolbar(self, config):
        return

    def create_toolbar_buttons(self):
        hbox = QHBoxLayout()
        buttons = self.get_toolbar_buttons()
        for b in buttons:
            b.setVisible(False)
            hbox.addWidget(b)
        self.toolbar_buttons = buttons
        return hbox

    def export_as_csv(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Export csv", "", "All Files (*);;Text Files (*.csv)"
            )
            if not file_path:
                logger.debug("No file selected")
                return
        table = self.get_rows_as_csv(row_numbers=list(range(self.model().rowCount())))
        with open(file_path, "w") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerows(table)
        logger.info(f"Table with {len(table)} rows saved to {file_path}")

    def create_toolbar_with_menu(self, title):
        return create_toolbar_with_menu(
            self.config, title, export_as_csv=self.export_as_csv
        )

    def show_toolbar(self, state, config=None):
        if state == self.toolbar_shown:
            return
        self.toolbar_shown = state
        for b in self.toolbar_buttons:
            b.setVisible(state)
        if not state:
            self.on_hide_toolbar()

    def toggle_toolbar(self, config=None):
        self.show_toolbar(not self.toolbar_shown, config)

    def add_copy_menu(self, menu: QMenu, idx) -> QMenu:
        cc = menu.addMenu(_("Copy"))
        for column in self.Columns:
            if self.isColumnHidden(column):
                continue
            column_title = self.original_model().horizontalHeaderItem(column).text()
            if not column_title:
                continue
            item_col = self.item_from_index(idx.sibling(idx.row(), column))
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

    def showEvent(self, e: "QShowEvent"):
        super().showEvent(e)
        if e.isAccepted() and self._pending_update:
            self._forced_update = True
            self.update()
            self._forced_update = False

    def maybe_defer_update(self) -> bool:
        """Returns whether we should defer an update/refresh."""
        defer = not self._forced_update and (
            not self.isVisible() or self.is_editor_open
        )
        # side-effect: if we decide to defer update, the state will become stale:
        self._pending_update = defer
        return defer

    def find_row_by_key(self, key) -> Optional[int]:
        for row in range(0, self.std_model.rowCount()):
            item = self.std_model.item(row, self.key_column)
            if item.data(self.key_role) == key:
                return row

    def refresh_all(self):
        if self.maybe_defer_update():
            return
        for row in range(0, self.std_model.rowCount()):
            item = self.std_model.item(row, self.key_column)
            key = item.data(self.key_role)
            self.refresh_row(key, row)

    def refresh_row(self, key: str, row: int) -> None:
        pass

    def refresh_item(self, key):
        row = self.find_row_by_key(key)
        if row is not None:
            self.refresh_row(key, row)

    def delete_item(self, key):
        row = self.find_row_by_key(key)
        if row is not None:
            self.std_model.takeRow(row)
        self.hide_if_empty()
