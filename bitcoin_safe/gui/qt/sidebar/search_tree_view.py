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

import logging
import sys
from collections.abc import Callable

from PyQt6.QtCore import QItemSelectionModel, QModelIndex, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QShortcut,
    QStandardItem,
    QStandardItemModel,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------
# Search result rendering (unchanged except for imports/translate fix)
# --------------------------------------------------------------------
class SearchHTMLDelegate(QStyledItemDelegate):
    def __init__(self, parent: QWidget) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self._parent = parent
        # cache: html → (QTextDocument, width)
        self._doc_cache: dict[str, tuple[QTextDocument, int]] = {}

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Paint."""
        if not painter:
            return

        # Start from a fully initialized option so the style can compute layout
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        style = _style if opt.widget and (_style := opt.widget.style()) else QStyle()

        # ---- background / selection ----
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, opt.widget)

        # ---- sub-rects computed by the current style ----
        icon_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, opt, opt.widget)
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)

        # ---- icon (DecorationRole) ----
        deco = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(deco, QIcon) and not deco.isNull():
            icon_size = opt.decorationSize if opt.decorationSize.isValid() else QSize(16, 16)
            if not (opt.state & QStyle.StateFlag.State_Enabled):
                mode = QIcon.Mode.Disabled
            elif opt.state & QStyle.StateFlag.State_Selected:
                mode = QIcon.Mode.Selected
            else:
                mode = QIcon.Mode.Normal
            state = QIcon.State.On if (opt.state & QStyle.StateFlag.State_On) else QIcon.State.Off
            pm = deco.pixmap(icon_size, mode, state)

            # center the pixmap inside icon_rect
            x_icon = icon_rect.left() + (icon_rect.width() - pm.width()) // 2
            y_icon = icon_rect.top() + (icon_rect.height() - pm.height()) // 2
            painter.drawPixmap(x_icon, y_icon, pm)

        # ---- HTML text ----
        html = index.data(Qt.ItemDataRole.DisplayRole) or ""
        doc, _ideal_w = self._get_doc_and_width(html, opt.font)

        # Use a paint context to adapt text color to selection without mutating the cached doc
        from PyQt6.QtGui import (
            QAbstractTextDocumentLayout,  # local import to avoid clutter
        )

        ctx = QAbstractTextDocumentLayout.PaintContext()
        if opt.state & QStyle.StateFlag.State_Selected:
            ctx.palette.setColor(QPalette.ColorRole.Text, opt.palette.highlightedText().color())
        else:
            ctx.palette.setColor(QPalette.ColorRole.Text, opt.palette.text().color())

        # vertically center the document within text_rect, honoring clip
        natural_h = doc.size().height()
        drawn_h = min(natural_h, text_rect.height())
        y = text_rect.top() + (text_rect.height() - drawn_h) / 2

        painter.save()
        painter.translate(text_rect.left(), y)
        ctx.clip = QRectF(0, 0, text_rect.width(), text_rect.height())
        if _layout := doc.documentLayout():
            _layout.draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """SizeHint."""
        org = super().sizeHint(option, index)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        # reuse the same helper to fill cache
        _, width = self._get_doc_and_width(text, option.font)

        # add a bit of padding
        return QSize(width + 4, org.height())

    def _get_doc_and_width(self, html: str, font: QFont) -> tuple[QTextDocument, int]:
        """Returns a cached (doc, width) for this HTML; creates and caches it on first
        use."""
        entry = self._doc_cache.get(html)
        if entry is None:
            doc = QTextDocument()
            doc.setDefaultFont(font)
            doc.setHtml(html)
            w = int(doc.idealWidth())
            self._doc_cache[html] = (doc, w)
            return doc, w
        return entry

    def parent(self) -> QWidget:
        """Parent."""
        return self._parent


class ResultItem:
    def __init__(
        self,
        text: str,
        parent: ResultItem | None = None,
        icon: QIcon | None = None,
        obj=None,
        obj_key: str | None = None,
    ) -> None:
        """Initialize instance."""
        self.text = text
        self.icon = icon
        self.obj = obj
        self.obj_key = obj_key
        self.children: list[ResultItem] = []
        self.set_parent(parent)

    def set_parent(self, parent: ResultItem | None = None) -> None:
        """Set parent."""
        self.parent = parent
        if self.parent and self not in self.parent.children:
            self.parent.children.append(self)


def format_result_text(full_text: str, search_text: str) -> str:
    """Format result text."""
    return full_text.replace(search_text, f"<span style='background-color: #ADD8E6;'>{search_text}</span>")


# ----------------------------
# Demo search (replace as needed)
# ----------------------------
def demo_do_search(search_text: str) -> ResultItem:
    """Demo do search."""
    root = ResultItem("")
    s = (search_text or "").strip()
    if not s:
        return root

    wallet = ResultItem("test", parent=root)
    addresses = ResultItem("addresses", parent=wallet)
    utxo = ResultItem("utxo", parent=wallet)
    history = ResultItem("history", parent=wallet)

    for result_lists in [addresses, utxo, history]:
        for txt in ["aaaa", "bbbb"]:
            text = txt + s + txt
            ResultItem(format_result_text(full_text=text, search_text=search_text), parent=result_lists)
    return root


def demo_on_click(item: ResultItem) -> None:
    """Demo on click."""
    print("Item Clicked:", item.text)


# --------------------------------
# Model/view for hierarchical results
# --------------------------------
class CustomItem(QStandardItem):
    def __init__(self, *args) -> None:
        """Initialize instance."""
        super().__init__(*args)
        self.result_item: ResultItem | None = None


class CustomItemModel(QStandardItemModel):
    def invisibleRootItem(self) -> CustomItem | None:
        """InvisibleRootItem."""
        return super().invisibleRootItem()  # type: ignore


class CustomTreeView(QTreeView):
    def __init__(self, parent=None, on_click=None, on_double_click=None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.on_click = on_click
        self.on_double_click = on_double_click
        self.setModel(CustomItemModel())

        # existing config
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        if _header := self.header():
            _header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.clicked.connect(self.handle_item_clicked)
        self.doubleClicked.connect(self.handle_item_double_clicked)

        # sidebar-like feel
        self.setRootIsDecorated(False)
        self.setIndentation(16)
        self.setUniformRowHeights(False)  # delegate controls height
        # self.setWordWrap(True)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self.setExpandsOnDoubleClick(False)
        self.setItemsExpandable(True)  # default; arrow still toggles on single click

        self.clicked.connect(self._toggle_parent_on_single_click)  # add

        # ---- important: apply style once and set guard for later updates
        self._style_updating = False
        self._apply_sidebar_like_style()

    # add this method to CustomTreeView
    def _toggle_parent_on_single_click(self, index: QModelIndex) -> None:
        """Toggle parent on single click."""
        if not index.isValid():
            return
        model = self.model()
        if not model:
            return
        # only act on parents
        if model.hasChildren(index):
            if self.isExpanded(index):
                self.collapse(index)
            else:
                self.expand(index)

    def _apply_sidebar_like_style(self) -> None:
        """Apply sidebar like style."""
        pal = self.palette()
        hl = pal.color(QPalette.ColorRole.Highlight)
        hltxt = pal.color(QPalette.ColorRole.HighlightedText)

        hover_rgba = f"rgba({hl.red()},{hl.green()},{hl.blue()},0.15)"
        selected_bg = hl.name()
        selected_fg = hltxt.name()

        self.setStyleSheet(
            f"""
            QTreeView {{
                background: transparent;
                border: none;
                outline: 0;
            }}
            QTreeView::item {{
                padding: 8px 10px;
            }}
            QTreeView::item:hover {{
                background: {hover_rgba};
            }}
            QTreeView::item:selected {{
                background: {selected_bg};
                color: {selected_fg};
            }}
            QTreeView::item:selected:hover {{
                background: {selected_bg};
                color: {selected_fg};
            }}
            QTreeView::branch,
            QTreeView::branch:!has-children:!has-siblings:adjoins-item {{
                background: transparent;
            }}
            """
        )

    def setModel(self, model: CustomItemModel | None) -> None:  # type: ignore[override]
        """SetModel."""
        self._source_model = model
        super().setModel(model)

    def model(self) -> CustomItemModel:
        """Model."""
        if self._source_model:
            return self._source_model
        raise Exception("model not set")

    def set_data(self, data: ResultItem) -> None:
        """Set data."""
        self.model().clear()
        self._populate_model(data)
        self.expandAll()
        self.resizeColumnToContents(0)
        self._apply_sidebar_like_style()

    def _populate_model(self, result_item: ResultItem, model_parent: CustomItem | None = None) -> None:
        """Populate model."""

        def add_child(child: ResultItem) -> CustomItem:
            """Add child."""
            model_item = CustomItem()
            model_item.setText(child.text)
            if child.icon:
                model_item.setIcon(child.icon)
            model_item.setEditable(False)
            model_item.result_item = child
            if model_parent:
                model_parent.appendRow(model_item)
            return model_item

        model_parent = self.model().invisibleRootItem() if model_parent is None else add_child(result_item)  # type: ignore[assignment]

        for child in result_item.children:
            self._populate_model(child, model_parent=model_parent)

    def handle_item_clicked(self, index: QModelIndex) -> None:
        """Handle item clicked."""
        if self.on_click and index.isValid():
            item = self.model().itemFromIndex(index)
            if not item or not isinstance(item, CustomItem):
                return
            self.on_click(item.result_item)

    def handle_item_double_clicked(self, index: QModelIndex) -> None:
        """Handle item double clicked."""
        if self.on_double_click and index.isValid():
            item = self.model().itemFromIndex(index)
            if not item or not isinstance(item, CustomItem):
                return
            self.on_double_click(item.result_item)


# --------------------------------
# NEW: SearchTreeView
#  - owns the search field + results view
#  - no popup option
#  - emits searchActiveChanged(bool)
# --------------------------------
class SearchTreeView(QWidget):
    searchActiveChanged = pyqtSignal(bool)

    def __init__(
        self,
        do_search: Callable[[str], ResultItem],
        parent: QWidget | None = None,
        on_click: Callable[[ResultItem], None] | None = None,
        search_box_on_bottom=True,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.do_search = do_search
        self.on_click = on_click
        self._is_active = False  # whether there is any non-empty search text

        self._layout = QVBoxLayout(self)
        # self._layout.setContentsMargins(0, 0, 0, 0)
        # self._layout.setSpacing(0)

        # Search field
        self.search_field = QLineEdit(self)
        self.search_field.setClearButtonEnabled(True)

        # Results view (hidden until there is text)
        self.tree_view = CustomTreeView(self, on_click=on_click, on_double_click=self._on_double_click)
        self.tree_view.setVisible(False)

        self._layout.addWidget(self.tree_view)
        if search_box_on_bottom:
            self._layout.insertWidget(1, self.search_field)
        else:
            self._layout.insertWidget(0, self.search_field)

        # HTML highlight delegate (kept from your version)
        self.tree_view.setItemDelegate(SearchHTMLDelegate(self.tree_view))

        # Wire up changes
        self.search_field.textChanged.connect(self._on_text_changed)

        # Optional: F3 navigation while results are visible
        self.shortcut_next = QShortcut("F3", self)
        self.shortcut_next.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_next.activated.connect(self.on_search_next)

        self.shortcut_prev = QShortcut("Shift+F3", self)
        self.shortcut_prev.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_prev.activated.connect(self.on_search_previous)

        self.shortcut_clear = QShortcut("ESC", self)
        self.shortcut_clear.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut_clear.activated.connect(self.clear_search)

        self.updateUi()

    # ---- Public helpers ----
    def isSearchActive(self) -> bool:
        """IsSearchActive."""
        return self._is_active

    def lineEdit(self) -> QLineEdit:
        """LineEdit."""
        return self.search_field

    # ---- Internal behaviors ----
    def _on_double_click(self, result_item: ResultItem) -> None:
        # Nothing special by default; keep as hook
        """On double click."""
        pass

    def _on_text_changed(self, text: str) -> None:
        """On text changed."""
        s = (text or "").strip()
        self._set_search_active(bool(s))

        results = self.do_search(text)
        self.tree_view.set_data(results)
        self.tree_view.update()
        # Show results pane only when there is text
        self.tree_view.setVisible(self._is_active)

    def _set_search_active(self, value: bool) -> None:
        """Set search active."""
        if self._is_active == value:
            return
        self._is_active = value
        self.searchActiveChanged.emit(self._is_active)

    # ---- F3 navigation in the results view ----
    def on_search_next(self):
        """On search next."""
        if not self.tree_view.isVisible():
            return
        model = self.tree_view.model()
        if model is None or model.rowCount() == 0:
            return

        current = self.tree_view.currentIndex()
        next_index = (
            model.index(0, 0, QModelIndex()) if not current.isValid() else self.tree_view.indexBelow(current)
        )

        if next_index.isValid():
            sel = self.tree_view.selectionModel()
            if not sel:
                return
            self.tree_view.setCurrentIndex(next_index)
            sel.select(next_index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.tree_view.scrollTo(next_index)
            self.tree_view.handle_item_clicked(next_index)

    def on_search_previous(self):
        """On search previous."""
        if not self.tree_view.isVisible():
            return
        model = self.tree_view.model()
        if model is None or model.rowCount() == 0:
            return

        current = self.tree_view.currentIndex()
        if not current.isValid():
            idx = model.index(0, 0, QModelIndex())
            nxt = self.tree_view.indexBelow(idx)
            while nxt.isValid():
                idx = nxt
                nxt = self.tree_view.indexBelow(idx)
            prev_index = idx
        else:
            prev_index = self.tree_view.indexAbove(current)

        if prev_index.isValid():
            sel = self.tree_view.selectionModel()
            if not sel:
                return
            self.tree_view.setCurrentIndex(prev_index)
            sel.select(prev_index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.tree_view.scrollTo(prev_index)
            self.tree_view.handle_item_clicked(prev_index)

    def clear_search(self):
        """Clear search."""
        self.search_field.clear()

    def updateUi(self):
        """UpdateUi."""
        self.search_field.setPlaceholderText(self.tr("Type to search..."))


if __name__ == "__main__":

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            """Initialize instance."""
            super().__init__()

            self.central_widget = QWidget()
            self.setCentralWidget(self.central_widget)

            self.central_widget_layout = QVBoxLayout(self.central_widget)

            self.search_tree_view = SearchTreeView(demo_do_search, on_click=demo_on_click, parent=self)
            self.central_widget_layout.addWidget(self.search_tree_view)
            self.central_widget_layout.addWidget(QPushButton("dummy"))

    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())
