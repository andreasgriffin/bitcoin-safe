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
from functools import partial
from typing import Generic, TypeVar, cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.util import is_dark_mode
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFocusEvent, QIcon, QKeySequence, QPalette, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.qr_components.square_buttons import (
    CloseButton,
    FlatSquareButton,
)
from bitcoin_safe.gui.qt.util import (
    set_no_margins,
    set_translucent,
    to_color_name,
)

logger = logging.getLogger(__name__)


def modify_color(color: QColor, alpha: int):
    """Modify color."""
    color.setAlpha(alpha)
    return color


class SidebarRow(QWidget):
    """Holds the wide sidebar button + optional square trailing buttons."""

    def __init__(
        self,
        sidebar_btn: SidebarButton,
        hover_color: str | None | QPalette.ColorRole,
        selected_color: str | None | QPalette.ColorRole,
        selected_hover_color: str | None | QPalette.ColorRole,
        parent=None,
    ):
        """Initialize instance."""
        super().__init__(parent)
        self.hover_color = hover_color
        self.selected_color = selected_color
        self.selected_hover_color = selected_hover_color
        self.setObjectName(str(id(self)) + "row")

        # Dynamic property we will toggle from the main button
        self.setProperty("selected", False)
        self.setProperty("kbd_focus", False)

        self.style_widget(self)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # --- keep trailing buttons always visible; let main button shrink
        sidebar_btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        sidebar_btn.setMinimumWidth(0)  # allow squeezing below size hint

        self.sidebar_btn = sidebar_btn
        self._layout.addWidget(self.sidebar_btn)
        self.square_buttons: list[QWidget] = []

        # Qt6: enable stylesheet background painting + hover events
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

        # Mirror the main button's checked state onto the row
        if self.sidebar_btn.isCheckable():
            self.sidebar_btn.toggled.connect(self.set_selected)

    def is_selected(self) -> bool:
        """Is selected."""
        return self.property("selected")

    def set_selected(self, selected: bool) -> None:
        """Set or clear selection on this row."""
        if self.property("selected") == selected:
            return

        self.set_focus(False)

        self.setProperty("selected", selected)
        if style := self.style():
            style.unpolish(self)
            style.polish(self)
        self.update()

    def add_square_button(self, btn: QWidget) -> None:
        """Add square button."""
        self._layout.addWidget(btn)
        self.square_buttons.append(btn)

    def get_css(self, widget: QWidget):
        # NOTE: QWidget doesn't support :checked, so use a dynamic property instead.
        """Get css."""
        base = f"#{widget.objectName()}"
        css = ""
        if self.hover_color:
            css += f"\n{base}:hover {{ background-color: {to_color_name(self.hover_color)}; }}"
        if self.selected_color:
            css += f'\n{base}[selected="true"] {{ background-color: {to_color_name(self.selected_color)}; }}'  # noqa: E501
            css += f'\n{base}[selected="false"][kbd_focus="true"] {{ background-color: {to_color_name(self.selected_color)}; }}'
        if self.selected_hover_color:
            css += f'\n{base}[selected="true"]:hover {{ background-color: {to_color_name(self.selected_hover_color)}; }}'  # noqa: E501
            css += f'\n{base}[selected="false"][kbd_focus="true"]:hover {{ background-color: {to_color_name(self.selected_hover_color)}; }}'
        return css

    def style_widget(self, widget: QWidget):
        """Style widget."""
        self.setStyleSheet(self.get_css(widget=widget))

    def set_focus(self, focused: bool) -> None:
        """Mirror focus state onto the parent row for custom styling."""
        self.setProperty("kbd_focus", focused)
        if style := self.style():
            style.unpolish(self)
            style.polish(self)
        self.update()


class SidebarButton(QPushButton):
    """Checkable sidebar button with instance-scoped styles and adjustable indent."""

    def __init__(self, text: str, icon: QIcon | None = None, indent: float = 0, bf=False):
        """Initialize instance."""
        super().__init__(text)
        self._bold = bf
        self._indent = indent
        self.setFlat(True)
        set_translucent(self)

        if icon:
            self.setIcon(icon)

        self.setObjectName(str(id(self)) + "button")
        self.setFixedHeight(36)
        self._apply_style()

    def _update_row_focus(self, focused: bool) -> None:
        """Mirror focus state onto the parent row for custom styling."""
        parent = self.parentWidget()
        while parent and not isinstance(parent, SidebarRow):
            parent = parent.parentWidget()
        if isinstance(parent, SidebarRow):
            parent.set_focus(focused)

    def focusInEvent(self, a0: QFocusEvent | None) -> None:
        super().focusInEvent(a0)
        self._update_row_focus(True)

    def focusOutEvent(self, a0: QFocusEvent | None) -> None:
        super().focusOutEvent(a0)
        self._update_row_focus(False)

    def setIndent(self, indent: float, bf=False) -> None:
        """SetIndent."""
        self._indent = indent
        self._bold = bf
        self._apply_style()

    def _apply_style(self) -> None:
        """Apply style."""
        padding = 12 + self._indent * 16
        # Add font-weight when bf=True
        font_weight = "font-weight: bold;" if self._bold else ""
        css = f"""
#{self.objectName()} {{
    border: none;
    text-align: left;
    padding-left: {padding}px;
    {font_weight}
}}"""
        css += f"\n#{self.objectName()}:focus {{\n    outline: none;\n    background-color: transparent;\n}}"
        self.setStyleSheet(css)


TT = TypeVar("TT")


class HideButton(CloseButton):
    pass


class SidebarNode(QFrame, Generic[TT]):
    """A single, mutable sidebar node: combines both data and UI.

    Signals (emit the SidebarNode instance):
    - closeClicked(node)
    - nodeSelected(node)
    - nodeToggled(node, expanded: bool)
    """

    # PyQt only supports built-ins; use 'object' here to carry the node itself.
    closeClicked = cast(SignalProtocol[[object]], pyqtSignal(object))
    hideClicked = cast(SignalProtocol[[object]], pyqtSignal(object))
    nodeSelected = cast(SignalProtocol[[object]], pyqtSignal(object))
    nodeUnSelected = cast(SignalProtocol[[object]], pyqtSignal(object))
    nodeToggled = cast(SignalProtocol[[object, bool]], pyqtSignal(object, bool))

    hide_icon_name = "close.svg"

    def __init__(
        self,
        title: str,
        data: TT,
        widget: QWidget | None = None,
        hide_header: bool = False,
        icon: QIcon | None = None,
        closable: bool = False,
        hidable: bool = False,
        collapsible: bool = True,
        auto_collapse_siblings: bool = False,
        show_expand_button: bool = False,
        initially_collapsed: bool = False,
        background_color: str | None | QPalette.ColorRole = None,
        selected_color: str | None | QPalette.ColorRole = QPalette.ColorRole.Base,
        hover_color: str | None | QPalette.ColorRole = QPalette.ColorRole.Midlight,
        selected_hover_color: str | None | QPalette.ColorRole = None,
        indent: float = 0,
        indent_factor: float = 1,
        bf_top_level: bool = True,
        parent_node: SidebarNode[TT] | None = None,
        parent: QWidget | None = None,
    ):
        """Initialize instance."""
        super().__init__(parent)
        # --- Data / config ---
        self.bf_top_level = bf_top_level
        self.title = title
        self.data = data
        self.widget = widget
        self.icon = icon
        self.closable = closable
        self.hidable = hidable
        self.hide_header = hide_header
        self.collapsible = collapsible
        self.auto_collapse_siblings = auto_collapse_siblings
        self.show_expand_button = show_expand_button
        self.initially_collapsed = initially_collapsed
        self.indent_factor = indent_factor

        self.background_color = background_color
        self.selected_color = selected_color
        self.hover_color = hover_color
        self.selected_hover_color = selected_hover_color or selected_color

        self.indent = indent
        self.parent_node = parent_node
        self.child_nodes: list[SidebarNode[TT]] = []
        self.stack: QStackedWidget | None = None  # wired by SidebarTree

        self.setObjectName(str(id(self)))

        # Optional background for whole frame
        style = ""
        if self.background_color:
            style += f"#{self.objectName()} {{ background-color: {self.background_color}; }}"
        if style:
            self.setStyleSheet(style)

        self._build_ui()

    def setVisible(self, visible: bool) -> None:
        """SetVisible."""
        self.header_row.setVisible(not self.hide_header and visible)
        super().setVisible(visible)
        if not visible and self.header_row.is_selected():
            self.nodeUnSelected.emit(self)

    # -------------------- Public API: mutation-friendly --------------------

    def setTitle(self, text: str) -> None:
        """SetTitle."""
        self.title = text
        if "&&" not in text and "&" in text:
            text = text.replace("&", "&&")
        self.header_btn.setText(text)

    def setIcon(self, icon: QIcon) -> None:
        """SetIcon."""
        self.icon = icon
        self.header_btn.setIcon(icon)

    def setToolTip(self, a0: str | None) -> None:
        """SetToolTip."""
        self.header_btn.setToolTip(a0)

    def setClosable(self, closable: bool) -> None:
        """SetClosable."""
        self.closable = closable
        self._rebuild_trailing_buttons()

    def setHidable(self, hidable: bool) -> None:
        """SetHidable."""
        self.hidable = hidable
        self._rebuild_trailing_buttons()

    def setCollapsible(self, collapsible: bool) -> None:
        """SetCollapsible."""
        self.collapsible = collapsible
        self._sync_toggle_button_visibility()

    def setAutoCollapseSiblings(self, enabled: bool) -> None:
        """SetAutoCollapseSiblings."""
        self.auto_collapse_siblings = enabled

    def setWidget(self, widget: QWidget | None) -> None:
        """Assign or replace the widget for this node and (re)register in the stack."""
        self.widget = widget
        self.header_btn.setCheckable(widget is not None)
        if self.stack and self.widget is not None and self.stack.indexOf(self.widget) != -1:
            self.stack.removeWidget(self.widget)
        if self.stack and widget is not None and self.stack.indexOf(widget) == -1:
            self.stack.addWidget(widget)

    def addButton(self, button: QPushButton) -> None:
        """Add a custom trailing button to this node's header row."""
        self.header_row.add_square_button(button)

    def addChildNode(self, node: SidebarNode[TT], focus: bool = True) -> None:
        """Append a child node and wire it up (indent, stack, signals)."""
        self.insertChildNode(len(self.child_nodes), node, focus=focus)

    def insertChildNode(self, index: int, node: SidebarNode[TT], focus: bool = True) -> None:
        """InsertChildNode."""
        node.setParent(self)
        node.parent_node = self
        node._indent_me(parent_indent=self.indent)

        # If the parent is already attached, attach the whole subtree to the stack.
        if self.stack is not None:
            node._attach_to_stack(self.stack)

        # Wire signals
        node.closeClicked.connect(self.closeClicked)
        node.nodeSelected.connect(self._bubble_selected)
        node.nodeUnSelected.connect(self._bubble_unselected)
        node.nodeToggled.connect(self._bubble_toggled)

        # Insert into layout/list
        self.child_nodes.insert(index, node)
        self.content_layout.insertWidget(index, node)

        # NEW: make sure the entire inserted branch reflects the new depth
        node._recompute_indents_from_here()

        self._sync_content_visibility()
        self._sync_toggle_button_visibility()
        if focus:
            node.select()

    def removeChildNode(self, node: SidebarNode[TT]) -> None:
        """RemoveChildNode."""
        node.clearChildren()

        try:
            idx = self.child_nodes.index(node)
        except ValueError:
            return

        # 1) Remove from our model/layout
        node.setParent(None)
        self.child_nodes.pop(idx)
        self.content_layout.removeWidget(node)

        # 2) Also purge its widget page if present
        if node.widget and self.stack and self.stack.indexOf(node.widget) != -1:
            self.stack.removeWidget(node.widget)

        self._sync_content_visibility()
        self._sync_toggle_button_visibility()

    def clearChildren(self) -> None:
        """ClearChildren."""
        for child in list(self.child_nodes):
            self.removeChildNode(child)

    def _indent_me(self, parent_indent: float):
        self.indent = parent_indent + 1 * self.indent_factor

    def _recompute_indents_from_here(self) -> None:
        """Apply this node's current indent to itself and all descendants."""
        self.header_btn.setIndent(self.indent, bf=self.bf_top_level and self.indent <= 0)
        for child in self.child_nodes:
            child._indent_me(parent_indent=self.indent)
            child._recompute_indents_from_here()

    def _ensure_stack_link(self) -> bool:
        """If this subtree isn't attached to a QStackedWidget yet, discover and attach
        it."""
        if self.stack:
            return True
        p = self.parent()
        while p is not None:
            st = getattr(p, "stack", None)
            if isinstance(st, QStackedWidget):
                self._attach_to_stack(st)  # attach this node + descendants
                return True
            p = p.parent()
        return False

    def select(self) -> bool:
        """Select."""
        self._expand_ancestors()

        if self.widget is None:
            self.set_collapsed(False)
            leaf = self._first_leaf_with_widget()
            return leaf.select() if leaf else False

        if not self.stack:
            self._ensure_stack_link()
        if not self.stack:
            logger.warning(
                f"SidebarNode {self.title}.select(): node {self.objectName()} "
                "is not attached to a SidebarTree stack"
            )
            return False

        self._root()._uncheck_all_recursively()
        self.header_row.set_selected(True)
        self.stack.setCurrentWidget(self.widget)
        self.nodeSelected.emit(self)
        return True

    def findNodeByWidget(self, widget: QWidget) -> SidebarNode[TT] | None:
        """FindNodeByWidget."""
        return self._find(lambda n: n.widget is widget)

    def findNodeByTitle(self, title: str) -> SidebarNode[TT] | None:
        """FindNodeByTitle."""
        return self._find(lambda n: n.title == title)

    def set_collapsed(self, value: bool, emit: bool = True) -> None:
        """Set collapsed."""
        new_expanded = not value
        if getattr(self, "expanded", None) == new_expanded:
            return
        self.expanded = new_expanded

        self._sync_content_visibility()

        if self.toggle_btn:
            self.toggle_btn.setChecked(self.expanded)

        if self.parent_node and self.auto_collapse_siblings and self.expanded:
            for sibling in self.parent_node.child_nodes:
                if sibling is not self:
                    sibling.set_collapsed(True, emit=False)

        if emit:
            self.nodeToggled.emit(self, self.expanded)

    # -------------------- Internal UI build / wiring --------------------

    def _build_ui(self) -> None:
        """Build ui."""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.header_btn = SidebarButton(
            text=self.title,
            icon=self.icon,
            indent=self.indent,
        )
        self.header_btn.setCheckable(self.widget is not None)
        self.header_btn.clicked.connect(self._maybe_select_self)

        self.header_row = SidebarRow(
            self.header_btn,
            hover_color=self.hover_color,
            selected_color=self.selected_color,
            selected_hover_color=self.selected_hover_color,
        )
        self.main_layout.addWidget(self.header_row)

        if self.hide_header:
            self.header_row.hide()  # <- no visible header for root

        self.toggle_btn: FlatSquareButton | None = None
        self._rebuild_trailing_buttons()

        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self.main_layout.addWidget(self.content)

        self.expanded = not self.initially_collapsed
        self._sync_content_visibility()
        self._sync_toggle_button_visibility()

    def _rebuild_trailing_buttons(self) -> None:
        # Clear existing trailing buttons (except the sidebar_btn)
        """Rebuild trailing buttons."""
        for btn in list(self.header_row.square_buttons):
            btn.setParent(None)
        self.header_row.square_buttons.clear()

        if self.closable:
            close_btn = CloseButton()
            close_btn.clicked.connect(partial(self.closeClicked.emit, self))
            self.header_row.add_square_button(close_btn)

        if self.hidable:
            hide_btn = HideButton()
            hide_btn.clicked.connect(partial(self.hideClicked.emit, self))
            hide_btn.clicked.connect(partial(self.setVisible, False))
            self.header_row.add_square_button(hide_btn)

        # Recreate toggle button if desired (order: ... [toggle])
        if self.show_expand_button and self.child_nodes and self.collapsible:
            self._ensure_toggle_button()
        else:
            if self.toggle_btn:
                self.toggle_btn.setParent(None)
                self.toggle_btn = None

    def _ensure_toggle_button(self) -> None:
        """Ensure toggle button."""
        if self.toggle_btn:
            return
        self.toggle_btn = FlatSquareButton(
            (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.toggle_btn.setChecked(not self.initially_collapsed)
        self.toggle_btn.clicked.connect(self._toggle_children)
        self.header_row.add_square_button(self.toggle_btn)

    def _sync_toggle_button_visibility(self) -> None:
        """Sync toggle button visibility."""
        has_children = bool(self.child_nodes)
        if self.show_expand_button and has_children and self.collapsible:
            self._ensure_toggle_button()
        else:
            if self.toggle_btn:
                self.toggle_btn.setParent(None)
                self.toggle_btn = None

    def _sync_content_visibility(self) -> None:
        """Sync content visibility."""
        self.content.setVisible(bool(self.child_nodes and self.expanded and self.collapsible))

    # -------------------- Tree helpers --------------------

    def _attach_to_stack(self, stack: QStackedWidget) -> None:
        """Wire this subtree to the shared stack and register all widgets."""
        self.stack = stack
        if self.widget is not None and self.stack.indexOf(self.widget) == -1:
            self.stack.addWidget(self.widget)
        for child in self.child_nodes:
            child._attach_to_stack(stack)

    def _root(self) -> SidebarNode[TT]:
        """Root."""
        n = self
        while n.parent_node is not None:
            n = n.parent_node
        return n

    def _maybe_select_self(self) -> None:
        """Maybe select self."""
        if self.widget is not None:
            self.select()
        elif self.child_nodes and self.collapsible:
            self._toggle_children()

    def _toggle_children(self) -> None:
        """Toggle children."""
        self.set_collapsed(self.expanded)

    def _bubble_selected(self, entry: object) -> None:
        """Bubble selected."""
        if not isinstance(entry, SidebarNode):
            return
        self.nodeSelected.emit(entry)

    def _bubble_unselected(self, entry: object) -> None:
        """Bubble unselected."""
        if not isinstance(entry, SidebarNode):
            return
        # REMOVE checked sync
        self.nodeUnSelected.emit(entry)

    def _bubble_toggled(self, entry: object, expanded: bool) -> None:
        """Bubble toggled."""
        if not isinstance(entry, SidebarNode):
            return
        self.nodeToggled.emit(entry, expanded)

    def _uncheck_all_recursively(self) -> None:
        """Uncheck all recursively."""
        self.header_row.set_selected(False)
        for child in self.child_nodes:
            child._uncheck_all_recursively()

    def _expand_ancestors(self) -> None:
        """Expand ancestors."""
        p = self.parent_node
        while p:
            p.set_collapsed(False)
            p = p.parent_node

    def _first_leaf_with_widget(self, must_be_visible=True) -> SidebarNode[TT] | None:
        """First leaf with widget."""
        if self.widget is not None:
            return self
        for child in self.child_nodes:
            found = child._first_leaf_with_widget(must_be_visible=must_be_visible)
            if found and not found.isHidden():
                return found
        return None

    def _find(self, predicate: Callable[[SidebarNode[TT]], bool]) -> SidebarNode[TT] | None:
        """Find."""
        if predicate(self):
            return self
        for c in self.child_nodes:
            r = c._find(predicate)
            if r is not None:
                return r
        return None

    def _node_by_index_path(self, index_path: list[int]) -> SidebarNode[TT] | None:
        """Node by index path."""
        node = self
        for i in index_path:
            if not node.child_nodes or i < 0 or i >= len(node.child_nodes):
                return None
            node.set_collapsed(False)
            node = node.child_nodes[i]
        return node

    # Convenience selection by different keys
    def setCurrentWidget(self, widget: QWidget) -> bool:
        """SetCurrentWidget."""
        node = self._find(lambda n: n.widget is widget)
        return node.select() if node else False

    def setCurrentNode(self, node: SidebarNode[TT]) -> bool:
        """SetCurrentNode."""
        target = self._find(lambda n: n is node)
        return target.select() if target else False

    def setCurrentIndex(self, index_path: list[int]) -> bool:
        """SetCurrentIndex."""
        node = self._node_by_index_path(index_path)
        return node.select() if node else False

    def removeNode(self) -> None:
        """Remove this node from its parent and, if possible, select a neighboring
        node's page."""
        self.clearChildren()

        # Root nodes aren't closed here (match the example semantics).
        if self.parent_node is None:
            return

        parent = self.parent_node

        # Remove the node from the UI tree
        parent.removeChildNode(self)

        if self.header_row.is_selected():
            self.nodeUnSelected.emit(self)

    def _iter_selectable_leaves(self, must_be_visible: bool = True):
        """Yield leaves that have a widget (and are visible, unless disabled)."""
        if self.widget is not None:
            if not must_be_visible or not self.isHidden():
                yield self
        for child in self.child_nodes:
            yield from child._iter_selectable_leaves(must_be_visible=must_be_visible)

    def select_relative(self, delta: int, wrap: bool = True) -> bool:
        """Move selection by `delta` within the flattened list of visible, selectable
        leaves.

        Positive delta goes down; negative goes up.
        """
        root = self._root()
        items = list(root._iter_selectable_leaves(must_be_visible=True))
        if not items:
            return False

        current = root.currentChildNode()
        if current is None:
            return items[0].select()

        try:
            idx = items.index(current)
        except ValueError:
            idx = 0

        if wrap:
            new_idx = (idx + delta) % len(items)
        else:
            new_idx = max(0, min(idx + delta, len(items) - 1))
        return items[new_idx].select()

    def _select_adjacent_sibling(self, idx_hint: int | None = None) -> bool:
        """Pick the next *reachable* selectable leaf after this node has been removed.

        Strategy
        --------
        1.  Look at the remaining siblings of the former parent, starting with the
            position where *this* node used to sit (``idx_hint``) and moving
            forwards.  For every sibling we take its first selectable leaf
            (depth-first, left-most) via ``_first_leaf_with_widget``.
        2.  If nothing suitable is found, scan the siblings **before** the
            original position.
        3.  Still nothing?  Recurse **upward**: ask the parent to find its own
            neighbour.  This lets the selection jump across branches until a
            viable page is located.
        """
        # 0) Abort at the top of the tree
        if self.parent_node is None:
            return False

        parent = self.parent_node
        siblings = parent.child_nodes
        if not siblings:
            return parent._select_adjacent_sibling()  # try higher up

        # 1) Where did we live in the sibling list?
        start = max(0, min(idx_hint if idx_hint is not None else len(siblings), len(siblings)))

        # 2) Search siblings *after* the removed node
        for i in range(start, len(siblings)):
            leaf = siblings[i]._first_leaf_with_widget()
            if leaf and leaf.widget and not leaf.isHidden():
                return leaf.select()

        # 3) …then siblings *before* the removed node (reverse order)
        for i in range(start - 1, -1, -1):
            leaf = siblings[i]._first_leaf_with_widget()
            if leaf and leaf.widget and not leaf.isHidden():
                return leaf.select()

        # 4) Nothing on this level – move up and repeat
        return parent._select_adjacent_sibling()

    def select_neighbor(self, idx: int | None = None):
        # Root nodes aren't closed here (match the example semantics).
        """Select neighbor."""
        if self.parent_node is None:
            return
        self._select_adjacent_sibling(idx_hint=idx)

    def get_nested_titles(
        self,
    ) -> list[str]:
        if not self.parent_node:
            return [self.title]
        else:
            return self.parent_node.get_nested_titles() + [self.title]

    def select_by_titles(self, titles: list[str]):
        if not titles:
            return
        node = self.findNodeByTitle(titles[0])
        if not node:
            return

        new_titles = titles[1:]
        if not new_titles:
            node.select()
        else:
            node.select_by_titles(new_titles)

    def set_current_tab_by_text(self, title: str):
        """Set current tab by text."""
        node = self.findNodeByTitle(title)
        if node:
            node.select()

    def currentChildNode(self) -> SidebarNode[TT] | None:
        """CurrentChildNode."""
        if not self.stack:
            return None
        w = self.stack.currentWidget()
        if w is None:
            return None
        for child in self.child_nodes:
            n = child.findNodeByWidget(w)
            if n:
                return n
        return None

    def currentWidget(self) -> QWidget | None:
        """CurrentWidget."""
        return node.widget if (node := self.currentChildNode()) else None


class SidebarTree(QWidget, Generic[TT]):
    """Container with a left column (vertical layout) and a right shared stack.

    Left column (new):
      - self.left_panel: QWidget that hosts the left UI
      - self.left_vbox:  QVBoxLayout inside left_panel
      - self.scroll_area (existing) is added into self.left_vbox
        (other widgets like a SearchTreeView can be inserted above it)

    Signals (emit the SidebarNode instance):
    - nodeSelected(node)
    - closeRequested(node)
    - nodeToggled(node)
    - currentChanged(node)
    """

    nodeToggled = cast(SignalProtocol[[SidebarNode[TT], bool]], pyqtSignal(object, bool))
    nodeSelected = cast(SignalProtocol[[SidebarNode[TT]]], pyqtSignal(object))
    nodeUnSelected = cast(SignalProtocol[[SidebarNode[TT]]], pyqtSignal(object))
    closeClicked = cast(SignalProtocol[[SidebarNode[TT]]], pyqtSignal(object))
    currentChanged = cast(
        SignalProtocol[[SidebarNode[TT]]], pyqtSignal(object)
    )  # emits the SidebarNode (or None) for the new current page

    nodeContextMenuRequested = pyqtSignal(object, object)  # (node: SidebarNode|None, global_pos: QPoint)
    emptyContextMenuRequested = pyqtSignal(object)  # (global_pos: QPoint)

    scroll_bg = "rgba(255,255,255,0.1)" if is_dark_mode() else "rgba(0,0,0,0.1)"

    def __init__(self, parent=None):
        """Initialize instance."""
        super().__init__(parent)
        self.stack = QStackedWidget(self)
        self._selection_history: list[SidebarNode[TT]] = []
        self._navigation_index = -1
        self._navigating_history = False
        self._current_node: SidebarNode[TT] | None = None

        self.stack.setAutoFillBackground(True)  # ensure it actually fills from its palette
        pal = self.stack.palette()
        pal.setColor(QPalette.ColorRole.Window, pal.color(QPalette.ColorRole.Base))
        self.stack.setPalette(pal)

        self.stack.currentChanged.connect(self._on_stack_current_changed)  # NEW

        # --- Left: scroll area with the sidebar content (unchanged)
        self.scroll_area = QScrollArea(self)
        # self.scroll_area.setFixedWidth(260)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setFrameShadow(QFrame.Shadow.Plain)

        if vp := self.scroll_area.viewport():
            vp.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            vp.customContextMenuRequested.connect(self._on_context_menu_requested)

        self.container = QWidget()  # holds the sidebar nodes
        self.v_layout = QVBoxLayout(self.container)
        self.v_layout.setContentsMargins(0, 0, 0, 0)
        self.v_layout.setSpacing(0)
        self.v_layout.addStretch()
        self.scroll_area.setWidget(self.container)

        # make the container itself emit customContextMenuRequested
        self.container.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.container.customContextMenuRequested.connect(self._on_context_menu_requested)
        self.scroll_area.setWidget(self.container)

        # --- NEW: Wrap the left side in a QWidget with a QVBoxLayout
        #          so other widgets (e.g., a SearchTreeView) can be inserted above the sidebar
        self.left_panel = QWidget(self)
        self.left_vbox = QVBoxLayout(self.left_panel)
        self.left_vbox.setContentsMargins(0, 0, 0, 0)
        self.left_vbox.setSpacing(0)
        # put the existing scroll_area into the left column layout
        self.left_vbox.addWidget(self.scroll_area, 1)

        # --- Main 2-column layout: left_panel | right stack
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.left_panel.setFixedWidth(200)
        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(self.stack, 1)

        # Create master root (no header shown)
        self.root = SidebarNode[TT](
            title="__root__",
            data=None,  # type: ignore
            widget=None,
            closable=False,
            collapsible=True,
            show_expand_button=False,
            initially_collapsed=False,
            indent=-1,
            parent=self.container,
            hide_header=True,
        )
        self.root._attach_to_stack(self.stack)
        # Bubble node signals once from the master root
        self.root.closeClicked.connect(self._on_close_clicked)
        self.root.nodeSelected.connect(self._on_node_selected)
        self.root.nodeUnSelected.connect(self._on_node_unselected)
        self.root.nodeToggled.connect(self._on_node_toggled)

        # Put the hidden root into the container
        self.v_layout.insertWidget(0, self.root)

        # --- Keyboard shortcuts: Ctrl+PgUp / Ctrl+PgDown to move between items
        self._shortcut_prev = QShortcut(QKeySequence("Ctrl+PgUp"), self)
        self._shortcut_next = QShortcut(QKeySequence("Ctrl+PgDown"), self)
        self._shortcut_prev.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut_next.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut_prev.activated.connect(lambda: self._select_relative(-1))
        self._shortcut_next.activated.connect(lambda: self._select_relative(+1))

    @property
    def roots(self) -> list[SidebarNode[TT]]:
        """Roots."""
        return self.root.child_nodes

    def currentNode(self):
        """CurrentNode."""
        return self.root.currentChildNode()

    def _select_relative(self, delta: int, wrap: bool = True) -> None:
        """Move selection up/down across the visible, selectable leaves."""
        node = self.root.currentChildNode()
        if node is not None:
            node.select_relative(delta, wrap=wrap)
            return

        # Nothing selected yet: pick the first selectable page if any
        first = next(self.root._iter_selectable_leaves(must_be_visible=True), None)
        if first is not None:
            first.select()

    def _on_stack_current_changed(self, idx: int) -> None:
        """On stack current changed."""
        node = self.currentNode()

        # --- skip pages whose row is invisible *and* not already selected ----
        if node and not node.header_row.isVisible() and not node.header_row.is_selected():
            self._on_node_unselected(node)
            return  # wait for the second currentChanged
        # ---------------------------------------------------------------------

        # keep header-row flags in sync
        if node is not None:
            node._root()._uncheck_all_recursively()
            node.header_row.set_selected(True)
        else:
            for t in self.root.child_nodes:
                t._root()._uncheck_all_recursively()
            self._current_node = None

        if node:
            self._scroll_node_into_view(node)
            self.currentChanged.emit(node)

    def _select_previous_from_history(self, excluding: SidebarNode[TT] | None = None) -> bool:
        """Select the most recent valid node from history, ignoring exclusions."""

        # Walk the history from newest to oldest, pruning hidden/invalid entries as we go.
        idx = len(self._selection_history) - 1
        while idx >= 0:
            candidate = self._selection_history[idx]
            if candidate is excluding:
                idx -= 1
                continue

            if candidate.widget is None or candidate.isHidden():
                # Drop stale entries and shift the navigation index left when we remove
                # an element at or before the current navigation position.
                self._selection_history.pop(idx)
                if idx <= self._navigation_index:
                    self._navigation_index -= 1
                idx -= 1
                continue

            # Keep the navigation index aligned with the candidate we select and avoid
            # adding new history entries while we revisit past selections.
            self._navigating_history = True
            try:
                if candidate.select():
                    self._navigation_index = idx
                    return True
            finally:
                self._navigating_history = False

            idx -= 1

        self._navigation_index = len(self._selection_history) - 1
        return False

    def _navigate_history(self, step: int) -> bool:
        """Navigate forward/backward through the selection history."""

        if not self._selection_history:
            return False

        # Start one step away from the current navigation index and advance until we find
        # a selectable node or exhaust history in the chosen direction.
        target_index = self._navigation_index + step
        while 0 <= target_index < len(self._selection_history):
            target_node = self._selection_history[target_index]
            if target_node.widget is None or target_node.isHidden():
                # Remove hidden/invalid entries and adjust the index when they sit at or
                # before the current navigation position.
                self._selection_history.pop(target_index)
                if target_index <= self._navigation_index:
                    self._navigation_index -= 1
                continue

            # Temporarily suppress history mutation while re-selecting past nodes so we
            # don't append duplicates or truncate future entries mid-navigation.
            self._navigating_history = True
            try:
                if target_node.select():
                    self._navigation_index = target_index
                    return True
            finally:
                self._navigating_history = False

            target_index += step

        self._navigation_index = min(self._navigation_index, len(self._selection_history) - 1)
        return False

    def navigate_history_backward(self) -> bool:
        """Select the previous tab from the navigation history."""

        return self._navigate_history(step=-1)

    def navigate_history_forward(self) -> bool:
        """Select the next tab from the navigation history."""

        return self._navigate_history(step=1)

    def nodeAtGlobalPos(self, global_pos: QPoint) -> SidebarNode[TT] | None:
        """NodeAtGlobalPos."""
        container_pos = self.container.mapFromGlobal(global_pos)
        w = self.container.childAt(container_pos)
        while w and not isinstance(w, SidebarNode):
            w = w.parentWidget()
        return w if isinstance(w, SidebarNode) else None

    def _scroll_node_into_view(self, node: SidebarNode[TT], margin: int = 12) -> None:
        """Ensure the selected node is visible inside the sidebar scroll area."""
        if not node.header_row.isVisible():
            return
        try:
            self.scroll_area.ensureWidgetVisible(node.header_row, 0, margin)
            return
        except Exception:
            # Fallback: manual adjustments if ensureWidgetVisible is unavailable.
            pass

        bar = self.scroll_area.verticalScrollBar()
        vp = self.scroll_area.viewport()
        if not bar or not vp:
            return

        top_left = node.header_row.mapTo(vp, QPoint(0, 0))
        bottom = top_left.y() + node.header_row.height()

        if top_left.y() < margin:
            bar.setValue(bar.value() + top_left.y() - margin)
        elif bottom > vp.height() - margin:
            bar.setValue(bar.value() + bottom - vp.height() + margin)

    def _on_context_menu_requested(self, pos: QPoint) -> None:
        """On context menu requested."""
        vp = self.scroll_area.viewport()
        if not vp:
            return
        global_pos = vp.mapToGlobal(pos)

        node = self.nodeAtGlobalPos(global_pos)
        if node:
            self.nodeContextMenuRequested.emit(node, global_pos)
        else:
            self.emptyContextMenuRequested.emit(global_pos)

    # -------- Forwarders / queries --------

    def _on_close_clicked(self, node: object) -> None:
        """On close clicked."""
        if not isinstance(node, SidebarNode):
            return
        self.closeClicked.emit(node)

    def _on_node_unselected(self, node: object) -> None:
        """On node unselected."""
        if not isinstance(node, SidebarNode):
            return
        successful_new_selection = self._select_previous_from_history()
        if not successful_new_selection:
            idx = None
            if node.parent_node:
                try:
                    idx = node.parent_node.child_nodes.index(node)
                except ValueError:
                    # Already removed
                    return
            node.select_neighbor(idx=idx)

        self.nodeUnSelected.emit(node)

    def _append_to_slection_history(self, node: SidebarNode):
        """Append to slection history."""
        if 0 <= self._navigation_index < len(self._selection_history):
            self._selection_history = self._selection_history[: self._navigation_index + 1]

        self._selection_history = [n for n in self._selection_history if n is not node]
        self._selection_history.append(node)
        self._navigation_index = len(self._selection_history) - 1

    def _on_node_selected(self, node: object) -> None:
        """On node selected."""
        if not isinstance(node, SidebarNode):
            return
        if not self._navigating_history:
            prev = self._current_node
            if prev is not None and prev is not node:
                self._append_to_slection_history(prev)
            self._append_to_slection_history(node)
        else:
            try:
                self._navigation_index = self._selection_history.index(node)
            except ValueError:
                self._append_to_slection_history(node)
        self._current_node = node
        self._scroll_node_into_view(node)
        self.nodeSelected.emit(node)

    def _on_node_toggled(self, node: object, expanded: bool) -> None:
        """On node toggled."""
        if not isinstance(node, SidebarNode):
            return
        self.nodeToggled.emit(node, expanded)

    def setCurrentWidget(self, widget: QWidget) -> None:
        """SetCurrentWidget."""
        for root in self.roots:
            if root.setCurrentWidget(widget):
                return

    def currentWidget(self) -> QWidget | None:
        """CurrentWidget."""
        return self.stack.currentWidget()

    def count(self) -> int:
        """Count."""
        return self.stack.count()


# ---------------- Example MainWindow using 3 levels (no SidebarModel) ----------------
if __name__ == "__main__":
    # 1) Set up standard Python logging to the console at DEBUG level
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s", stream=sys.stdout
    )

    class MainWindow(QMainWindow):
        def __init__(self):
            """Initialize instance."""
            super().__init__()
            self.setWindowTitle("PyQt6 SidebarTree Example (3 levels, no model)")
            self.resize(1000, 600)
            self.wallet_counter = 0
            self.tab_counter = 0

            # Menu
            menu_bar = self.menuBar()
            assert menu_bar

            add_wallet_act = QAction("Add Wallet", self)
            add_wallet_act.triggered.connect(self._add_wallet)
            menu_bar.addAction(add_wallet_act)

            add_tab_act = QAction("Add Tab", self)
            add_tab_act.triggered.connect(self._add_tab_to_current_wallet)
            menu_bar.addAction(add_tab_act)

            remove_tab_act = QAction("Remove Current Tab", self)
            remove_tab_act.triggered.connect(self._remove_current_tab)
            menu_bar.addAction(remove_tab_act)

            remove_wallet_act = QAction("Remove Current Wallet", self)
            remove_wallet_act.triggered.connect(self._remove_current_wallet)
            menu_bar.addAction(remove_wallet_act)

            # # --- NEW: demo actions for SidebarNode.move_me()/squash_me() ---
            # move_to_last_child_act = QAction("Move to Last Child", self)
            # move_to_last_child_act.triggered.connect(self._move_current_to_last_child)
            # menu_bar.addAction(move_to_last_child_act)

            # move_to_parent_act = QAction("Move to Parent", self)
            # move_to_parent_act.triggered.connect(self._move_current_to_parent)
            # menu_bar.addAction(move_to_parent_act)

            # Central layout
            central = QWidget()
            hl = QVBoxLayout(central)
            set_no_margins(hl)
            self.setCentralWidget(central)

            # SidebarTree
            self.tree = SidebarTree[str](self)
            self.tree.nodeSelected.connect(self._on_node_selected)
            self.tree.closeClicked.connect(self._on_close_requested)
            hl.addWidget(self.tree)

            # Root group
            self.root = SidebarNode[str](
                title="All Wallets",
                data="root",
                widget=None,
                collapsible=True,
                initially_collapsed=False,
                auto_collapse_siblings=False,
            )
            self.tree.root.addChildNode(self.root)

            # Initialize with two wallets
            self._add_wallet()
            self._add_wallet()

        # ---------- Helpers ----------
        def _mk_page(self, title: str) -> QWidget:
            """Mk page."""
            page = QWidget()
            vl = QVBoxLayout(page)
            lbl = QLabel(f"<h1>{title}</h1>")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl.addWidget(lbl)
            return page

        def _mk_wallet_node(self, wallet_name: str) -> SidebarNode[str]:
            """Mk wallet node."""
            icons = {
                "History": QIcon.fromTheme("view-history"),
                "Send": QIcon.fromTheme("mail-send"),
                "Receive": QIcon.fromTheme("mail-receive"),
                "Descriptor": QIcon.fromTheme("view-list-details"),
                "Tools & Services": QIcon.fromTheme("applications-system"),
            }

            wallet_node = SidebarNode[str](
                title=wallet_name,
                data=wallet_name,
                icon=QIcon.fromTheme("wallet"),
                closable=True,
                collapsible=True,
                auto_collapse_siblings=False,
                show_expand_button=False,  # click header to expand/collapse
            )

            for cat, icon in icons.items():
                title = f"{wallet_name} - {cat}"
                child = SidebarNode[str](
                    title=cat,
                    data=title,
                    widget=self._mk_page(title),
                    icon=icon,
                    closable=False,
                )
                wallet_node.addChildNode(child)

            return wallet_node

        # ---------- Menu actions ----------
        def _add_wallet(self):
            """Add wallet."""
            self.wallet_counter += 1
            wallet_name = f"Wallet {chr(ord('A') + self.wallet_counter - 1)} with long name"
            wallet_node = self._mk_wallet_node(wallet_name)
            self.root.addChildNode(wallet_node)
            # auto-select first tab
            first_leaf = wallet_node._first_leaf_with_widget()
            if first_leaf and first_leaf.widget:
                self.tree.setCurrentWidget(first_leaf.widget)

        def _wallet_of_widget(self, w: QWidget) -> SidebarNode[str] | None:
            # root > wallet > tab
            """Wallet of widget."""
            node = self.root.findNodeByWidget(w)
            if not node:
                return None
            # walk up to the wallet (parent of tab)
            return node.parent_node

        def _add_tab_to_current_wallet(self):
            """Add tab to current wallet."""
            current_widget = self.tree.currentWidget()
            if not current_widget:
                return
            wallet = self._wallet_of_widget(current_widget)
            if not wallet:
                return

            self.tab_counter += 1
            title = f"{wallet.title} - New Tab {self.tab_counter}"
            new_leaf = SidebarNode[str](
                title=self.tr("New Tab {n}").format(n=self.tab_counter),
                data=title,
                widget=self._mk_page(title),
                closable=True,
            )

            wallet.addChildNode(new_leaf)
            if new_leaf.widget:
                self.tree.setCurrentWidget(new_leaf.widget)

        def _remove_current_tab(self):
            """Remove current tab."""
            current_widget = self.tree.currentWidget()
            if not current_widget:
                return
            wallet = self._wallet_of_widget(current_widget)
            if not wallet:
                return
            # find the tab node
            tab = wallet.findNodeByWidget(current_widget)
            if not tab or tab is wallet:
                return

            # choose neighbor to select
            try:
                idx = wallet.child_nodes.index(tab)
            except ValueError:
                return

            wallet.removeChildNode(tab)

            next_widget: QWidget | None = None
            if wallet.child_nodes:
                new_idx = min(idx, len(wallet.child_nodes) - 1)
                candidate = wallet.child_nodes[new_idx]._first_leaf_with_widget()
                next_widget = candidate.widget if candidate else None
            if next_widget:
                self.tree.setCurrentWidget(next_widget)

        def _remove_current_wallet(self):
            """Remove current wallet."""
            current_widget = self.tree.currentWidget()
            if not current_widget:
                return
            wallet = self._wallet_of_widget(current_widget)
            if not wallet or wallet is self.root:
                return
            self.root.removeChildNode(wallet)

            next_widget = None
            if self.root.child_nodes:
                candidate = self.root.child_nodes[0]._first_leaf_with_widget()
                next_widget = candidate.widget if candidate else None
            if next_widget:
                self.tree.setCurrentWidget(next_widget)

        # --- NEW: helpers to get the currently selected SidebarNode ---
        def _current_node(self) -> SidebarNode[str] | None:
            """Current node."""
            return self.tree.currentNode()

        # # --- NEW: demonstrate moving the selected node under the last wallet ---
        # def _move_current_to_last_child(self):
        #     node = self._current_node()
        #     if not node or not node.parent_node:
        #         return
        #     if not self.root.child_nodes:
        #         return
        #     target_parent = self.root.child_nodes[-1]  # last wallet under "All Wallets"
        #     if target_parent is node:
        #         return
        #     node.move_me(target_parent)  # uses your SidebarNode.move_me(...)

        # # --- NEW: demonstrate promoting the selected node to its grandparent ---
        # def _move_current_to_parent(self):
        #     node = self._current_node()
        #     if not node or not node.parent_node or not node.parent_node.parent_node:
        #         return
        #     target_parent = node.parent_node.parent_node
        #     node.move_me(target_parent)  # append under grandparent

        # ---------- Signal handlers ----------
        def _on_node_selected(self, node: SidebarNode[TT]):
            # Build a breadcrumb like "All Wallets > Wallet A > History"
            """On node selected."""
            parts = []
            n = node
            while n:
                parts.append(n.title)
                if not n.parent_node:
                    break
                n = n.parent_node
            breadcrumb = " > ".join(reversed(parts))
            print(breadcrumb, "| data:", node.data)

        def _on_close_requested(self, node: SidebarNode[TT]):
            """On close requested."""
            node.removeNode()

    app = QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec())
