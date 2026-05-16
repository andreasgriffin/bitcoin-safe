#
# Bitcoin Safe
# Copyright (C) 2023-2026 Andreas Griffin
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
#

from __future__ import annotations

import logging
import random
from typing import TypeVar

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QAction, QColor, QFont, QPainter, QPaintEvent
from PyQt6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class DebugWidget(QWidget):
    def _add_submenu(self, menu: QMenu, title: str) -> QMenu:
        """Create and attach a submenu with a non-optional type."""
        submenu = QMenu(title, menu)
        menu.addMenu(submenu)
        return submenu

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """PaintEvent."""
        super().paintEvent(a0)
        self.drawDebugInfo(self)

    def _cleaned_size_policy(self, policy: QSizePolicy.Policy) -> str:
        """Cleaned size policy."""
        return str(policy).split(".")[-1]

    def _widget_label(self, widget: QWidget) -> str:
        """Readable widget label."""
        object_name = widget.objectName()
        if object_name:
            return f"{object_name} ({widget.__class__.__name__})"
        return f"<unnamed> ({widget.__class__.__name__})"

    def _widget_log_label(self, widget: QWidget) -> str:
        """Stable-ish widget label for logs."""
        return (
            f"{self._widget_label(widget)} "
            f"id={id(widget)} "
            f"size={self._size_text(widget.size())} "
            f"hint={self._size_text(widget.sizeHint())}"
        )

    def _policy_pair_text(self, policy: QSizePolicy) -> str:
        """Format QSizePolicy pair."""
        return (
            f"H-{self._cleaned_size_policy(policy.horizontalPolicy())}, "
            f"V-{self._cleaned_size_policy(policy.verticalPolicy())}"
        )

    def _size_text(self, size: QSize) -> str:
        """Format QSize."""
        return f"{size.width()}x{size.height()}"

    def _rect_text(self, rect: QRect) -> str:
        """Format QRect."""
        return f"x={rect.x()}, y={rect.y()}, w={rect.width()}, h={rect.height()}"

    def _point_text(self, point: QPoint) -> str:
        """Format QPoint."""
        return f"x={point.x()}, y={point.y()}"

    def _policy_options(self) -> list[QSizePolicy.Policy]:
        """Return useful QSizePolicy options."""
        return [
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding,
            QSizePolicy.Policy.Ignored,
        ]

    def _install_context_menu(self, widget: QWidget) -> None:
        """Install right-click debug context menu on a widget."""
        if widget.property("_debug_context_menu_installed"):
            return

        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, watched_widget=widget: self._show_debug_menu(watched_widget, pos)
        )
        widget.setProperty("_debug_context_menu_installed", True)

    def _show_debug_menu(self, widget: QWidget, pos: QPoint) -> None:
        """Show right-click debug menu."""
        menu = QMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        title_action = QAction(self._widget_label(widget), menu)
        title_action.setEnabled(False)
        menu.addAction(title_action)

        info_action = QAction(
            (f"Size: {self._size_text(widget.size())}, hint: {self._size_text(widget.sizeHint())}"),
            menu,
        )
        info_action.setEnabled(False)
        menu.addAction(info_action)

        menu.addSeparator()

        this_widget_menu = self._add_submenu(menu, "This widget")
        self._add_widget_debug_menu(this_widget_menu, widget)

        children = self._direct_widget_children(widget)
        if children:
            children_menu = self._add_submenu(menu, "Children")
            self._add_children_menus(children_menu, widget, depth=0, max_depth=8)

        menu.addSeparator()

        refresh_menu = self._add_submenu(menu, "Refresh")

        refresh_action = QAction("Refresh this widget", refresh_menu)
        refresh_action.triggered.connect(lambda checked=False, w=widget: self._refresh_widget_geometry(w))
        refresh_menu.addAction(refresh_action)

        refresh_subtree_action = QAction("Refresh subtree", refresh_menu)
        refresh_subtree_action.triggered.connect(
            lambda checked=False, w=widget: self._refresh_subtree_geometry(w)
        )
        refresh_menu.addAction(refresh_subtree_action)

        menu.exec(widget.mapToGlobal(pos))
        menu.deleteLater()

    def _direct_widget_children(self, widget: QWidget) -> list[QWidget]:
        """Return direct real QWidget children only.

        Excludes debug menus/popups, otherwise repeated right-clicks create QMenu
        children that appear recursively in the debug menu.
        """
        children: list[QWidget] = []

        for child in widget.children():
            if not isinstance(child, QWidget):
                continue

            if isinstance(child, QMenu):
                continue

            if child.windowType() == Qt.WindowType.Popup:
                continue

            children.append(child)

        return children

    def _add_children_menus(
        self,
        menu: QMenu,
        parent_widget: QWidget,
        depth: int,
        max_depth: int,
    ) -> None:
        """Add recursive child widget submenus."""
        if depth >= max_depth:
            stopped_action = QAction("Maximum debug menu depth reached", menu)
            stopped_action.setEnabled(False)
            menu.addAction(stopped_action)
            return

        children = self._direct_widget_children(parent_widget)
        if not children:
            empty_action = QAction("No QWidget children", menu)
            empty_action.setEnabled(False)
            menu.addAction(empty_action)
            return

        for index, child in enumerate(children):
            child_menu = self._add_submenu(menu, f"{index}: {self._widget_label(child)}")
            self._add_widget_debug_menu(child_menu, child)

            grandchildren = self._direct_widget_children(child)
            if grandchildren:
                child_menu.addSeparator()
                grandchild_menu = self._add_submenu(child_menu, "Children")
                self._add_children_menus(
                    grandchild_menu,
                    child,
                    depth=depth + 1,
                    max_depth=max_depth,
                )

    def _add_widget_debug_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add organized debug actions for one widget."""
        current_policy = widget.sizePolicy()

        summary_action = QAction(
            (
                f"H-{self._cleaned_size_policy(current_policy.horizontalPolicy())}, "
                f"V-{self._cleaned_size_policy(current_policy.verticalPolicy())}, "
                f"size={self._size_text(widget.size())}, "
                f"hint={self._size_text(widget.sizeHint())}"
            ),
            menu,
        )
        summary_action.setEnabled(False)
        menu.addAction(summary_action)

        menu.addSeparator()

        size_policy_menu = self._add_submenu(menu, "Size policy")
        self._add_size_policy_menu(size_policy_menu, widget)

        visibility_menu = menu.addMenu("Visibility")
        self._add_visibility_menu(visibility_menu, widget)

        constraints_menu = menu.addMenu("Constraints")
        self._add_constraints_menu(constraints_menu, widget)

        own_layout_menu = self._add_submenu(menu, "Own layout")
        self._add_own_layout_menu(own_layout_menu, widget)

        parent_layout_menu = self._add_submenu(menu, "Parent layout")
        self._add_parent_layout_menu(parent_layout_menu, widget)

        subtree_menu = self._add_submenu(menu, "Subtree")
        self._add_subtree_menu(subtree_menu, widget)

    def _add_own_layout_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add actions for the widget's own layout."""
        layout = widget.layout()

        if layout is None:
            unavailable_action = QAction("This widget has no layout", menu)
            unavailable_action.setEnabled(False)
            menu.addAction(unavailable_action)
            return

        info_action = QAction(
            (
                f"{layout.__class__.__name__}, "
                f"count={layout.count()}, "
                f"spacing={layout.spacing()}, "
                f"margins={layout.getContentsMargins()}"
            ),
            menu,
        )
        info_action.setEnabled(False)
        menu.addAction(info_action)

        menu.addSeparator()

        margins_menu = self._add_submenu(menu, "Contents margins")
        self._add_layout_margins_menu(margins_menu, widget)

        spacing_menu = self._add_submenu(menu, "Spacing")
        self._add_layout_spacing_menu(spacing_menu, widget)

        if isinstance(layout, QBoxLayout):
            direction_menu = self._add_submenu(menu, "Direction")
            self._add_box_layout_direction_menu(direction_menu, widget)

            stretch_menu = self._add_submenu(menu, "Stretch factors")
            self._add_box_layout_stretch_menu(stretch_menu, widget)

            spacer_menu = self._add_submenu(menu, "Spacers")
            self._add_box_layout_spacer_menu(spacer_menu, widget)

        constraints_menu = self._add_submenu(menu, "Size constraint")
        self._add_layout_size_constraint_menu(constraints_menu, widget)

        menu.addSeparator()

        refresh_action = QAction("Refresh layout", menu)
        refresh_action.triggered.connect(lambda checked=False, w=widget: self._refresh_own_layout(w))
        menu.addAction(refresh_action)

    def _add_layout_margins_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add layout margin actions."""
        layout = widget.layout()
        if layout is None:
            return

        current = layout.getContentsMargins()

        current_action = QAction(f"Current: {current}", menu)
        current_action.setEnabled(False)
        menu.addAction(current_action)

        menu.addSeparator()

        presets = [
            ("0", (0, 0, 0, 0)),
            ("4", (4, 4, 4, 4)),
            ("8", (8, 8, 8, 8)),
            ("10", (10, 10, 10, 10)),
            ("12", (12, 12, 12, 12)),
            ("16", (16, 16, 16, 16)),
            ("24", (24, 24, 24, 24)),
        ]

        for label, margins in presets:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(current == margins)
            action.triggered.connect(
                lambda checked=False, w=widget, m=margins: self._set_layout_margins(w, *m)
            )
            menu.addAction(action)

        menu.addSeparator()

        compact_action = QAction("Horizontal 0, Vertical 8", menu)
        compact_action.triggered.connect(
            lambda checked=False, w=widget: self._set_layout_margins(w, 0, 8, 0, 8)
        )
        menu.addAction(compact_action)

        card_action = QAction("Card 10, 10, 10, 10", menu)
        card_action.triggered.connect(
            lambda checked=False, w=widget: self._set_layout_margins(w, 10, 10, 10, 10)
        )
        menu.addAction(card_action)

    def _add_layout_spacing_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add layout spacing actions."""
        layout = widget.layout()
        if layout is None:
            return

        current = layout.spacing()

        current_action = QAction(f"Current: {current}", menu)
        current_action.setEnabled(False)
        menu.addAction(current_action)

        menu.addSeparator()

        for spacing in (-1, 0, 2, 4, 6, 8, 10, 12, 16, 24):
            label = "Default (-1)" if spacing == -1 else f"{spacing}px"
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(current == spacing)
            action.triggered.connect(
                lambda checked=False, w=widget, s=spacing: self._set_layout_spacing(w, s)
            )
            menu.addAction(action)

    def _add_box_layout_direction_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add QBoxLayout direction actions."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):
            return

        current = layout.direction()

        directions = [
            ("Left to Right", QBoxLayout.Direction.LeftToRight),
            ("Right to Left", QBoxLayout.Direction.RightToLeft),
            ("Top to Bottom", QBoxLayout.Direction.TopToBottom),
            ("Bottom to Top", QBoxLayout.Direction.BottomToTop),
        ]

        for label, direction in directions:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(current == direction)
            action.triggered.connect(
                lambda checked=False, w=widget, d=direction: self._set_box_layout_direction(w, d)
            )
            menu.addAction(action)

    def _add_box_layout_stretch_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add QBoxLayout stretch factor actions."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):
            unavailable_action = QAction("Layout is not a QBoxLayout", menu)
            unavailable_action.setEnabled(False)
            menu.addAction(unavailable_action)
            return

        if layout.count() == 0:
            empty_action = QAction("Layout has no items", menu)
            empty_action.setEnabled(False)
            menu.addAction(empty_action)
            return

        for index in range(layout.count()):
            item = layout.itemAt(index)
            label = self._layout_item_label(layout, index, item)

            item_menu = self._add_submenu(menu, label)

            current_action = QAction(f"Current stretch: {layout.stretch(index)}", item_menu)
            current_action.setEnabled(False)
            item_menu.addAction(current_action)

            item_menu.addSeparator()

            for stretch in (0, 1, 2, 3, 4, 5, 10):
                action = QAction(str(stretch), item_menu)
                action.setCheckable(True)
                action.setChecked(layout.stretch(index) == stretch)
                action.triggered.connect(
                    lambda checked=False, w=widget, i=index, s=stretch: self._set_box_layout_stretch(
                        w,
                        i,
                        s,
                    )
                )
                item_menu.addAction(action)

        menu.addSeparator()

        clear_all_action = QAction("Set all stretches to 0", menu)
        clear_all_action.triggered.connect(
            lambda checked=False, w=widget: self._set_all_box_layout_stretches(w, 0)
        )
        menu.addAction(clear_all_action)

    def _add_box_layout_spacer_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add spacer actions for the widget's own QBoxLayout."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):
            return

        add_start_menu = self._add_submenu(menu, "Add at start")
        self._add_own_layout_spacer_insert_actions(add_start_menu, widget, index=0)

        add_end_menu = self._add_submenu(menu, "Add at end")
        self._add_own_layout_spacer_insert_actions(add_end_menu, widget, index=layout.count())

        menu.addSeparator()

        remove_stretchers_action = QAction("Remove all stretch spacers", menu)
        remove_stretchers_action.triggered.connect(
            lambda checked=False, w=widget: self._remove_stretch_spacers_from_own_layout(w)
        )
        menu.addAction(remove_stretchers_action)

    def _add_own_layout_spacer_insert_actions(
        self,
        menu: QMenu,
        widget: QWidget,
        index: int,
    ) -> None:
        """Add spacer insertion actions for own layout."""
        for pixels in (4, 8, 12, 16, 24, 32, 48):
            action = QAction(f"Fixed spacing: {pixels}px", menu)
            action.triggered.connect(
                lambda checked=False, w=widget, i=index, p=pixels: self._insert_spacing_in_own_layout(
                    w,
                    i,
                    p,
                )
            )
            menu.addAction(action)

        menu.addSeparator()

        stretch_action = QAction("Stretch spacer", menu)
        stretch_action.triggered.connect(
            lambda checked=False, w=widget, i=index: self._insert_stretch_in_own_layout(w, i)
        )
        menu.addAction(stretch_action)

    def _add_layout_size_constraint_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add layout size constraint actions."""
        layout = widget.layout()
        if layout is None:
            return

        current = layout.sizeConstraint()

        constraints = [
            ("Default", layout.SizeConstraint.SetDefaultConstraint),
            ("No constraint", layout.SizeConstraint.SetNoConstraint),
            ("Minimum size", layout.SizeConstraint.SetMinimumSize),
            ("Fixed size", layout.SizeConstraint.SetFixedSize),
            ("Maximum size", layout.SizeConstraint.SetMaximumSize),
            ("Min and max size", layout.SizeConstraint.SetMinAndMaxSize),
        ]

        current_action = QAction(f"Current: {current.name}", menu)
        current_action.setEnabled(False)
        menu.addAction(current_action)

        menu.addSeparator()

        for label, constraint in constraints:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(current == constraint)
            action.triggered.connect(
                lambda checked=False, w=widget, c=constraint: self._set_layout_size_constraint(w, c)
            )
            menu.addAction(action)

    def _layout_item_label(self, layout: QBoxLayout, index: int, item) -> str:
        """Return a readable layout-item label."""
        if item is None:
            return f"{index}: <None>"

        child_widget = item.widget()
        if child_widget is not None:
            return f"{index}: Widget {self._widget_label(child_widget)}"

        child_layout = item.layout()
        if child_layout is not None:
            return f"{index}: Layout {child_layout.__class__.__name__}"

        spacer = item.spacerItem()
        if spacer is not None:
            return f"{index}: Spacer {self._size_text(spacer.sizeHint())}"

        return f"{index}: Unknown item"

    def _set_layout_margins(
        self,
        widget: QWidget,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None:
        """Set contents margins on the widget's own layout."""
        layout = widget.layout()
        if layout is None:
            logger.info(
                "DebugWidget could not set own layout margins: widget=%s reason=no layout",
                self._widget_log_label(widget),
            )
            return

        old_margins = layout.getContentsMargins()
        layout.setContentsMargins(left, top, right, bottom)
        new_margins = layout.getContentsMargins()

        logger.info(
            "DebugWidget changed own layout margins: widget=%s layout=%s old=%s new=%s",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            old_margins,
            new_margins,
        )

        self._refresh_own_layout(widget)

    def _set_layout_spacing(self, widget: QWidget, spacing: int) -> None:
        """Set spacing on the widget's own layout."""
        layout = widget.layout()
        if layout is None:
            logger.info(
                "DebugWidget could not set own layout spacing: widget=%s reason=no layout",
                self._widget_log_label(widget),
            )
            return

        old_spacing = layout.spacing()
        layout.setSpacing(spacing)
        new_spacing = layout.spacing()

        logger.info(
            "DebugWidget changed own layout spacing: widget=%s layout=%s old=%s new=%s",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            old_spacing,
            new_spacing,
        )

        self._refresh_own_layout(widget)

    def _set_box_layout_direction(
        self,
        widget: QWidget,
        direction: QBoxLayout.Direction,
    ) -> None:
        """Set direction on the widget's own QBoxLayout."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):
            logger.info(
                "DebugWidget could not set own layout direction: widget=%s reason=no QBoxLayout",
                self._widget_log_label(widget),
            )
            return

        old_direction = layout.direction()
        layout.setDirection(direction)
        new_direction = layout.direction()

        logger.info(
            "DebugWidget changed own layout direction: widget=%s layout=%s old=%s new=%s",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            old_direction.name,
            new_direction.name,
        )

        self._refresh_own_layout(widget)

    def _set_box_layout_stretch(self, widget: QWidget, index: int, stretch: int) -> None:
        """Set stretch factor for an item in the widget's own QBoxLayout."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout) or index < 0 or index >= layout.count():
            logger.info(
                "DebugWidget could not set own layout stretch: widget=%s index=%s reason=invalid layout item",
                self._widget_log_label(widget),
                index,
            )
            return

        old_stretch = layout.stretch(index)
        layout.setStretch(index, stretch)
        new_stretch = layout.stretch(index)

        logger.info(
            "DebugWidget changed own layout stretch: widget=%s layout=%s index=%s item=%s old=%s new=%s",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            index,
            self._layout_item_label(layout, index, layout.itemAt(index)),
            old_stretch,
            new_stretch,
        )

        self._refresh_own_layout(widget)

    def _set_all_box_layout_stretches(self, widget: QWidget, stretch: int) -> None:
        """Set all stretch factors in the widget's own QBoxLayout."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):
            logger.info(
                "DebugWidget could not set all own layout stretches: widget=%s reason=no QBoxLayout",
                self._widget_log_label(widget),
            )
            return

        logger.info(
            "DebugWidget changing all own layout stretches: widget=%s layout=%s count=%s new=%s",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            layout.count(),
            stretch,
        )

        for index in range(layout.count()):
            old_stretch = layout.stretch(index)
            layout.setStretch(index, stretch)

            logger.info(
                "DebugWidget changed own layout stretch item: widget=%s layout=%s index=%s item=%s old=%s new=%s",
                self._widget_log_label(widget),
                layout.__class__.__name__,
                index,
                self._layout_item_label(layout, index, layout.itemAt(index)),
                old_stretch,
                layout.stretch(index),
            )

        self._refresh_own_layout(widget)

    def _insert_spacing_in_own_layout(
        self,
        widget: QWidget,
        index: int,
        pixels: int,
    ) -> None:
        """Insert fixed spacing into the widget's own QBoxLayout."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):
            logger.info(
                "DebugWidget could not insert spacing in own layout: widget=%s reason=no QBoxLayout",
                self._widget_log_label(widget),
            )
            return

        insert_index = max(0, min(index, layout.count()))
        layout.insertSpacing(insert_index, pixels)

        logger.info(
            "DebugWidget inserted fixed spacing in own layout: widget=%s layout=%s insertIndex=%s pixels=%s",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            insert_index,
            pixels,
        )

        self._refresh_own_layout(widget)

    def _insert_stretch_in_own_layout(self, widget: QWidget, index: int) -> None:
        """Insert stretch spacer into the widget's own QBoxLayout."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):
            logger.info(
                "DebugWidget could not insert stretch in own layout: widget=%s reason=no QBoxLayout",
                self._widget_log_label(widget),
            )
            return

        insert_index = max(0, min(index, layout.count()))
        layout.insertStretch(insert_index, 1)

        logger.info(
            "DebugWidget inserted stretch spacer in own layout: widget=%s layout=%s insertIndex=%s stretch=1",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            insert_index,
        )

        self._refresh_own_layout(widget)

    def _remove_stretch_spacers_from_own_layout(self, widget: QWidget) -> None:
        """Remove all stretch spacer items from the widget's own QBoxLayout."""
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):
            logger.info(
                "DebugWidget could not remove own layout stretch spacers: widget=%s reason=no QBoxLayout",
                self._widget_log_label(widget),
            )
            return

        removed_count = self._remove_stretch_spacers_from_layout(layout)

        logger.info(
            "DebugWidget removed stretch spacers from own layout: widget=%s layout=%s removed=%s",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            removed_count,
        )

        self._refresh_own_layout(widget)

    def _remove_stretch_spacers_from_layout(self, layout: QBoxLayout) -> int:
        """Remove stretch spacer items from a QBoxLayout."""
        removed_count = 0

        for item_index in reversed(range(layout.count())):
            item = layout.itemAt(item_index)
            if item is None:
                continue

            if item.widget() is not None or item.layout() is not None:
                continue

            spacer = item.spacerItem()
            if spacer is None:
                continue

            size_policy = spacer.sizePolicy()
            is_vertical_layout = layout.direction() in (
                QBoxLayout.Direction.TopToBottom,
                QBoxLayout.Direction.BottomToTop,
            )

            if is_vertical_layout:
                is_stretch_spacer = size_policy.verticalPolicy() == QSizePolicy.Policy.Expanding
            else:
                is_stretch_spacer = size_policy.horizontalPolicy() == QSizePolicy.Policy.Expanding

            if not is_stretch_spacer:
                continue

            removed_item = layout.takeAt(item_index)
            del removed_item
            removed_count += 1

        return removed_count

    def _set_layout_size_constraint(self, widget: QWidget, constraint) -> None:
        """Set size constraint on the widget's own layout."""
        layout = widget.layout()
        if layout is None:
            logger.info(
                "DebugWidget could not set own layout size constraint: widget=%s reason=no layout",
                self._widget_log_label(widget),
            )
            return

        old_constraint = layout.sizeConstraint()
        layout.setSizeConstraint(constraint)
        new_constraint = layout.sizeConstraint()

        logger.info(
            "DebugWidget changed own layout size constraint: widget=%s layout=%s old=%s new=%s",
            self._widget_log_label(widget),
            layout.__class__.__name__,
            old_constraint.name,
            new_constraint.name,
        )

        self._refresh_own_layout(widget)

    def _refresh_own_layout(self, widget: QWidget) -> None:
        """Refresh the widget's own layout and geometry."""
        layout = widget.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

        self._refresh_widget_geometry(widget)

    def _parent_layout_item_index(self, widget: QWidget) -> tuple[QBoxLayout | None, int]:
        """Return parent QBoxLayout and widget index in that layout."""
        parent = widget.parentWidget()
        if parent is None:
            return None, -1

        layout = parent.layout()
        if not isinstance(layout, QBoxLayout):
            return None, -1

        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item and item.widget() is widget:
                return layout, index

        return None, -1

    def _add_parent_layout_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add parent-layout operations for this widget."""
        layout, index = self._parent_layout_item_index(widget)

        if layout is None or index < 0:
            unavailable_action = QAction("No parent QBoxLayout item found", menu)
            unavailable_action.setEnabled(False)
            menu.addAction(unavailable_action)
            return

        info_action = QAction(
            (f"Parent layout: {layout.__class__.__name__}, index={index}, count={layout.count()}"),
            menu,
        )
        info_action.setEnabled(False)
        menu.addAction(info_action)

        menu.addSeparator()

        before_menu = self._add_submenu(menu, "Add spacer before")
        self._add_spacer_insert_actions(
            before_menu,
            widget,
            before=True,
        )

        after_menu = self._add_submenu(menu, "Add spacer after")
        self._add_spacer_insert_actions(
            after_menu,
            widget,
            before=False,
        )

        alignment_menu = self._add_submenu(menu, "Set alignment")
        self._add_parent_layout_alignment_menu(alignment_menu, widget)

        menu.addSeparator()

        remove_stretchers_action = QAction("Remove all stretch spacers from parent layout", menu)
        remove_stretchers_action.triggered.connect(
            lambda checked=False, w=widget: self._remove_stretch_spacers_from_parent_layout(w)
        )
        menu.addAction(remove_stretchers_action)

    def _alignment_text(self, alignment: Qt.AlignmentFlag) -> str:
        """Format alignment flags."""
        if not alignment:
            return "None"

        parts: list[str] = []

        flag_pairs = [
            (Qt.AlignmentFlag.AlignLeft, "Left"),
            (Qt.AlignmentFlag.AlignHCenter, "HCenter"),
            (Qt.AlignmentFlag.AlignRight, "Right"),
            (Qt.AlignmentFlag.AlignJustify, "Justify"),
            (Qt.AlignmentFlag.AlignTop, "Top"),
            (Qt.AlignmentFlag.AlignVCenter, "VCenter"),
            (Qt.AlignmentFlag.AlignBottom, "Bottom"),
            (Qt.AlignmentFlag.AlignBaseline, "Baseline"),
        ]

        for flag, name in flag_pairs:
            if alignment & flag:
                parts.append(name)

        return " | ".join(parts) if parts else str(alignment)

    def _parent_layout_item(self, widget: QWidget):
        """Return parent layout, widget index, and item."""
        layout, index = self._parent_layout_item_index(widget)
        if layout is None or index < 0:
            return None, -1, None

        item = layout.itemAt(index)
        return layout, index, item

    def _add_parent_layout_alignment_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add parent-layout alignment actions."""
        layout, index, item = self._parent_layout_item(widget)

        if layout is None or index < 0 or item is None:
            unavailable_action = QAction("No parent QBoxLayout item found", menu)
            unavailable_action.setEnabled(False)
            menu.addAction(unavailable_action)
            return

        current_alignment = item.alignment()

        current_action = QAction(
            f"Current: {self._alignment_text(current_alignment)}",
            menu,
        )
        current_action.setEnabled(False)
        menu.addAction(current_action)

        menu.addSeparator()

        presets: list[tuple[str, Qt.AlignmentFlag]] = [
            ("None / Fill layout cell", Qt.AlignmentFlag(0)),
            ("Left", Qt.AlignmentFlag.AlignLeft),
            ("HCenter", Qt.AlignmentFlag.AlignHCenter),
            ("Right", Qt.AlignmentFlag.AlignRight),
            ("Top", Qt.AlignmentFlag.AlignTop),
            ("VCenter", Qt.AlignmentFlag.AlignVCenter),
            ("Bottom", Qt.AlignmentFlag.AlignBottom),
            ("Top Left", Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft),
            ("Top Center", Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter),
            ("Top Right", Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight),
            ("Center Left", Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            ("Center", Qt.AlignmentFlag.AlignCenter),
            ("Center Right", Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
            ("Bottom Left", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft),
            ("Bottom Center", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter),
            ("Bottom Right", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight),
        ]

        for label, alignment in presets:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(current_alignment == alignment)
            action.triggered.connect(
                lambda checked=False, w=widget, a=alignment: self._set_parent_layout_alignment(
                    w,
                    a,
                )
            )
            menu.addAction(action)

    def _set_parent_layout_alignment(
        self,
        widget: QWidget,
        alignment: Qt.AlignmentFlag,
    ) -> None:
        """Set alignment for this widget inside its parent QBoxLayout."""
        layout, index, item = self._parent_layout_item(widget)

        if layout is None or index < 0 or item is None:
            logger.info(
                "DebugWidget could not set parent-layout alignment: "
                "widget=%s reason=no parent QBoxLayout item",
                self._widget_log_label(widget),
            )
            return

        old_alignment = item.alignment()

        layout.setAlignment(widget, alignment)

        new_item = layout.itemAt(index)
        new_alignment = new_item.alignment() if new_item is not None else Qt.AlignmentFlag(0)

        logger.info(
            ("DebugWidget changed parent-layout alignment: widget=%s parentLayout=%s index=%s old=%s new=%s"),
            self._widget_log_label(widget),
            layout.__class__.__name__,
            index,
            self._alignment_text(old_alignment),
            self._alignment_text(new_alignment),
        )

        self._refresh_widget_geometry(widget)

    def _remove_stretch_spacers_from_parent_layout(self, widget: QWidget) -> None:
        """Remove all stretch spacer items from the widget's parent QBoxLayout."""
        layout, index = self._parent_layout_item_index(widget)
        if layout is None or index < 0:
            logger.info(
                "DebugWidget could not remove stretch spacers: widget=%s reason=no parent QBoxLayout item",
                self._widget_log_label(widget),
            )
            return

        removed_count = self._remove_stretch_spacers_from_layout(layout)

        logger.info(
            ("DebugWidget removed stretch spacers from parent layout: widget=%s parentLayout=%s removed=%s"),
            self._widget_log_label(widget),
            layout.__class__.__name__,
            removed_count,
        )

        self._refresh_widget_geometry(widget)

    def _add_spacer_insert_actions(
        self,
        menu: QMenu,
        widget: QWidget,
        before: bool,
    ) -> None:
        """Add spacer insertion actions."""
        for pixels in (4, 8, 12, 16, 24, 32, 48):
            action = QAction(f"Fixed spacing: {pixels}px", menu)
            action.triggered.connect(
                lambda checked=False, w=widget, p=pixels, b=before: self._insert_spacing_near_widget(
                    w,
                    pixels=p,
                    before=b,
                )
            )
            menu.addAction(action)

        menu.addSeparator()

        stretch_action = QAction("Stretch spacer", menu)
        stretch_action.triggered.connect(
            lambda checked=False, w=widget, b=before: self._insert_stretch_near_widget(
                w,
                before=b,
            )
        )
        menu.addAction(stretch_action)

    def _insert_spacing_near_widget(
        self,
        widget: QWidget,
        pixels: int,
        before: bool,
    ) -> None:
        """Insert fixed spacing before or after a widget in its parent QBoxLayout."""
        layout, index = self._parent_layout_item_index(widget)
        if layout is None or index < 0:
            logger.info(
                "DebugWidget could not insert spacing: widget=%s reason=no parent QBoxLayout item",
                self._widget_log_label(widget),
            )
            return

        insert_index = index if before else index + 1
        layout.insertSpacing(insert_index, pixels)

        logger.info(
            (
                "DebugWidget inserted fixed spacing: widget=%s parentLayout=%s "
                "widgetIndex=%s insertIndex=%s position=%s pixels=%s"
            ),
            self._widget_log_label(widget),
            layout.__class__.__name__,
            index,
            insert_index,
            "before" if before else "after",
            pixels,
        )

        self._refresh_widget_geometry(widget)

    def _insert_stretch_near_widget(
        self,
        widget: QWidget,
        before: bool,
    ) -> None:
        """Insert stretch spacer before or after a widget in its parent QBoxLayout."""
        layout, index = self._parent_layout_item_index(widget)
        if layout is None or index < 0:
            logger.info(
                "DebugWidget could not insert stretch: widget=%s reason=no parent QBoxLayout item",
                self._widget_log_label(widget),
            )
            return

        insert_index = index if before else index + 1
        layout.insertStretch(insert_index, 1)

        logger.info(
            (
                "DebugWidget inserted stretch spacer: widget=%s parentLayout=%s "
                "widgetIndex=%s insertIndex=%s position=%s stretch=%s"
            ),
            self._widget_log_label(widget),
            layout.__class__.__name__,
            index,
            insert_index,
            "before" if before else "after",
            1,
        )

        self._refresh_widget_geometry(widget)

    def _add_size_policy_menu(self, menu: QMenu, widget: QWidget) -> None:
        """Add size policy submenu."""
        current_policy = widget.sizePolicy()

        current_action = QAction(
            f"Current: {self._policy_pair_text(current_policy)}",
            menu,
        )
        current_action.setEnabled(False)
        menu.addAction(current_action)

        menu.addSeparator()

        horizontal_menu = self._add_submenu(menu, "Horizontal")
        for policy in self._policy_options():
            action = QAction(self._cleaned_size_policy(policy), horizontal_menu)
            action.setCheckable(True)
            action.setChecked(policy == current_policy.horizontalPolicy())
            action.triggered.connect(
                lambda checked=False, p=policy, w=widget: self._set_horizontal_policy(w, p)
            )
            horizontal_menu.addAction(action)

        vertical_menu = self._add_submenu(menu, "Vertical")
        for policy in self._policy_options():
            action = QAction(self._cleaned_size_policy(policy), vertical_menu)
            action.setCheckable(True)
            action.setChecked(policy == current_policy.verticalPolicy())
            action.triggered.connect(
                lambda checked=False, p=policy, w=widget: self._set_vertical_policy(w, p)
            )
            vertical_menu.addAction(action)

        both_menu = self._add_submenu(menu, "Both")
        for policy in self._policy_options():
            action = QAction(self._cleaned_size_policy(policy), both_menu)
            action.triggered.connect(lambda checked=False, p=policy, w=widget: self._set_both_policies(w, p))
            both_menu.addAction(action)

        menu.addSeparator()

        common_menu = self._add_submenu(menu, "Common presets")

        preferred_action = QAction("Preferred / Preferred", common_menu)
        preferred_action.triggered.connect(
            lambda checked=False, w=widget: self._set_policy_pair(
                w,
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Preferred,
            )
        )
        common_menu.addAction(preferred_action)

        fixed_action = QAction("Fixed / Fixed", common_menu)
        fixed_action.triggered.connect(
            lambda checked=False, w=widget: self._set_policy_pair(
                w,
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
        )
        common_menu.addAction(fixed_action)

        expanding_action = QAction("Preferred / Expanding", common_menu)
        expanding_action.triggered.connect(
            lambda checked=False, w=widget: self._set_policy_pair(
                w,
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Expanding,
            )
        )
        common_menu.addAction(expanding_action)

        max_vertical_action = QAction("Preferred / Maximum", common_menu)
        max_vertical_action.triggered.connect(
            lambda checked=False, w=widget: self._set_policy_pair(
                w,
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Maximum,
            )
        )
        common_menu.addAction(max_vertical_action)

    def _set_widget_visible(self, widget: QWidget, visible: bool) -> None:
        """Set widget visibility."""
        old_visible = widget.isVisible()

        widget.setVisible(visible)

        logger.info(
            "DebugWidget changed widget visibility: widget=%s old=%s new=%s",
            self._widget_log_label(widget),
            old_visible,
            widget.isVisible(),
        )

        self._refresh_widget_geometry(widget)

    def _set_minimum_size(self, widget: QWidget, size: QSize) -> None:
        """Set widget minimum size."""
        old_minimum = widget.minimumSize()

        widget.setMinimumSize(size)

        logger.info(
            "DebugWidget changed widget minimum size: widget=%s old=%s new=%s",
            self._widget_log_label(widget),
            self._size_text(old_minimum),
            self._size_text(widget.minimumSize()),
        )

        self._refresh_widget_geometry(widget)

    def _set_maximum_size(self, widget: QWidget, size: QSize) -> None:
        """Set widget maximum size."""
        old_maximum = widget.maximumSize()

        widget.setMaximumSize(size)

        logger.info(
            "DebugWidget changed widget maximum size: widget=%s old=%s new=%s",
            self._widget_log_label(widget),
            self._size_text(old_maximum),
            self._size_text(widget.maximumSize()),
        )

        self._refresh_widget_geometry(widget)

    def _set_fixed_size(self, widget: QWidget, size: QSize) -> None:
        """Set widget fixed size."""
        old_minimum = widget.minimumSize()
        old_maximum = widget.maximumSize()
        old_policy = widget.sizePolicy()

        widget.setFixedSize(size)
        widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        logger.info(
            (
                "DebugWidget changed widget fixed size: "
                "widget=%s size=%s oldMin=%s oldMax=%s newMin=%s newMax=%s "
                "oldPolicy=%s newPolicy=%s"
            ),
            self._widget_log_label(widget),
            self._size_text(size),
            self._size_text(old_minimum),
            self._size_text(old_maximum),
            self._size_text(widget.minimumSize()),
            self._size_text(widget.maximumSize()),
            self._policy_pair_text(old_policy),
            self._policy_pair_text(widget.sizePolicy()),
        )

        self._refresh_widget_geometry(widget)

    def _add_visibility_menu(self, menu: QMenu | None, widget: QWidget) -> None:
        """Add visibility actions."""
        if menu is None:
            return
        visible_action = QAction("Visible", menu)
        visible_action.setCheckable(True)
        visible_action.setChecked(widget.isVisible())
        visible_action.triggered.connect(lambda checked=False, w=widget: self._set_widget_visible(w, True))
        menu.addAction(visible_action)

        invisible_action = QAction("Invisible", menu)
        invisible_action.setCheckable(True)
        invisible_action.setChecked(not widget.isVisible())
        invisible_action.triggered.connect(lambda checked=False, w=widget: self._set_widget_visible(w, False))
        menu.addAction(invisible_action)

        menu.addSeparator()

        toggle_action = QAction("Toggle visibility", menu)
        toggle_action.triggered.connect(
            lambda checked=False, w=widget: self._set_widget_visible(w, not w.isVisible())
        )
        menu.addAction(toggle_action)

    def _add_constraints_menu(self, menu: QMenu | None, widget: QWidget) -> None:
        """Add constraints submenu."""
        if menu is None:
            return

        current_min = widget.minimumSize()
        current_max = widget.maximumSize()

        min_action = QAction(f"Current minimum: {self._size_text(current_min)}", menu)
        min_action.setEnabled(False)
        menu.addAction(min_action)

        max_action = QAction(f"Current maximum: {self._size_text(current_max)}", menu)
        max_action.setEnabled(False)
        menu.addAction(max_action)

        menu.addSeparator()

        minimum_menu = menu.addMenu("Set minimum size")
        self._add_minimum_size_preset_menu(minimum_menu, widget)

        maximum_menu = menu.addMenu("Set maximum size")
        self._add_maximum_size_preset_menu(maximum_menu, widget)

        fixed_menu = menu.addMenu("Set fixed size")
        self._add_fixed_size_preset_menu(fixed_menu, widget)

        menu.addSeparator()

        fixed_current_action = QAction("Set fixed to current size", menu)
        fixed_current_action.triggered.connect(
            lambda checked=False, w=widget: self._set_fixed_to_current_size(w)
        )
        menu.addAction(fixed_current_action)

        minimum_current_action = QAction("Set minimum to current size", menu)
        minimum_current_action.triggered.connect(
            lambda checked=False, w=widget: self._set_minimum_size(w, w.size())
        )
        menu.addAction(minimum_current_action)

        maximum_current_action = QAction("Set maximum to current size", menu)
        maximum_current_action.triggered.connect(
            lambda checked=False, w=widget: self._set_maximum_size(w, w.size())
        )
        menu.addAction(maximum_current_action)

        menu.addSeparator()

        clear_minimum_action = QAction("Clear minimum size", menu)
        clear_minimum_action.triggered.connect(
            lambda checked=False, w=widget: self._set_minimum_size(w, QSize(0, 0))
        )
        menu.addAction(clear_minimum_action)

        clear_maximum_action = QAction("Clear maximum size", menu)
        clear_maximum_action.triggered.connect(
            lambda checked=False, w=widget: self._set_maximum_size(w, QSize(16777215, 16777215))
        )
        menu.addAction(clear_maximum_action)

        clear_fixed_action = QAction("Clear min/max constraints", menu)
        clear_fixed_action.triggered.connect(lambda checked=False, w=widget: self._clear_fixed_constraints(w))
        menu.addAction(clear_fixed_action)

    def _size_presets(self) -> list[tuple[str, QSize]]:
        """Common size presets."""
        return [
            ("0 x 0", QSize(0, 0)),
            ("16 x 16", QSize(16, 16)),
            ("18 x 18", QSize(18, 18)),
            ("24 x 24", QSize(24, 24)),
            ("32 x 32", QSize(32, 32)),
            ("40 x 40", QSize(40, 40)),
            ("48 x 48", QSize(48, 48)),
            ("64 x 64", QSize(64, 64)),
            ("80 x 24", QSize(80, 24)),
            ("100 x 30", QSize(100, 30)),
            ("120 x 40", QSize(120, 40)),
            ("160 x 40", QSize(160, 40)),
            ("200 x 50", QSize(200, 50)),
            ("320 x 80", QSize(320, 80)),
            ("640 x 120", QSize(640, 120)),
        ]

    def _add_minimum_size_preset_menu(self, menu: QMenu | None, widget: QWidget) -> None:
        """Add minimum size preset actions."""
        if menu is None:
            return
        for label, size in self._size_presets():
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(widget.minimumSize() == size)
            action.triggered.connect(lambda checked=False, w=widget, s=size: self._set_minimum_size(w, s))
            menu.addAction(action)

    def _add_maximum_size_preset_menu(self, menu: QMenu | None, widget: QWidget) -> None:
        """Add maximum size preset actions."""
        if menu is None:
            return
        for label, size in self._size_presets():
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(widget.maximumSize() == size)
            action.triggered.connect(lambda checked=False, w=widget, s=size: self._set_maximum_size(w, s))
            menu.addAction(action)

        menu.addSeparator()

        unlimited_action = QAction("Unlimited / default", menu)
        unlimited_action.setCheckable(True)
        unlimited_action.setChecked(widget.maximumSize() == QSize(16777215, 16777215))
        unlimited_action.triggered.connect(
            lambda checked=False, w=widget: self._set_maximum_size(w, QSize(16777215, 16777215))
        )
        menu.addAction(unlimited_action)

    def _add_fixed_size_preset_menu(self, menu: QMenu | None, widget: QWidget) -> None:
        """Add fixed size preset actions."""
        if menu is None:
            return
        for label, size in self._size_presets():
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(widget.minimumSize() == size and widget.maximumSize() == size)
            action.triggered.connect(lambda checked=False, w=widget, s=size: self._set_fixed_size(w, s))
            menu.addAction(action)

    def _add_subtree_menu(self, menu: QMenu, root_widget: QWidget) -> None:
        """Add subtree operations submenu."""
        size_policy_menu = self._add_submenu(menu, "Apply size policy to subtree")

        for policy in self._policy_options():
            action = QAction(f"Both: {self._cleaned_size_policy(policy)}", size_policy_menu)
            action.triggered.connect(
                lambda checked=False, p=policy, w=root_widget: self._apply_policy_to_subtree(
                    w,
                    p,
                    p,
                )
            )
            size_policy_menu.addAction(action)

        size_policy_menu.addSeparator()

        preferred_action = QAction("Preferred / Preferred", size_policy_menu)
        preferred_action.triggered.connect(
            lambda checked=False, w=root_widget: self._apply_policy_to_subtree(
                w,
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Preferred,
            )
        )
        size_policy_menu.addAction(preferred_action)

        fixed_action = QAction("Fixed / Fixed", size_policy_menu)
        fixed_action.triggered.connect(
            lambda checked=False, w=root_widget: self._apply_policy_to_subtree(
                w,
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
        )
        size_policy_menu.addAction(fixed_action)

        constraints_menu = self._add_submenu(menu, "Constraints")

        clear_constraints_action = QAction("Clear min/max constraints in subtree", constraints_menu)
        clear_constraints_action.triggered.connect(
            lambda checked=False, w=root_widget: self._clear_constraints_in_subtree(w)
        )
        constraints_menu.addAction(clear_constraints_action)

        refresh_action = QAction("Refresh subtree geometry", menu)
        refresh_action.triggered.connect(
            lambda checked=False, w=root_widget: self._refresh_subtree_geometry(w)
        )
        menu.addAction(refresh_action)

    def _iter_widget_subtree(self, widget: QWidget) -> list[QWidget]:
        """Return widget and QWidget descendants."""
        widgets = [widget]
        for child in self._direct_widget_children(widget):
            widgets.extend(self._iter_widget_subtree(child))
        return widgets

    def _set_horizontal_policy(self, widget: QWidget, policy: QSizePolicy.Policy) -> None:
        """Set only horizontal size policy."""
        old_policy = widget.sizePolicy()
        new_policy = QSizePolicy(old_policy)
        new_policy.setHorizontalPolicy(policy)

        widget.setSizePolicy(new_policy)

        logger.info(
            "DebugWidget changed horizontal size policy: widget=%s old=%s new=%s",
            self._widget_log_label(widget),
            self._policy_pair_text(old_policy),
            self._policy_pair_text(new_policy),
        )

        self._refresh_widget_geometry(widget)

    def _set_vertical_policy(self, widget: QWidget, policy: QSizePolicy.Policy) -> None:
        """Set only vertical size policy."""
        old_policy = widget.sizePolicy()
        new_policy = QSizePolicy(old_policy)
        new_policy.setVerticalPolicy(policy)

        widget.setSizePolicy(new_policy)

        logger.info(
            "DebugWidget changed vertical size policy: widget=%s old=%s new=%s",
            self._widget_log_label(widget),
            self._policy_pair_text(old_policy),
            self._policy_pair_text(new_policy),
        )

        self._refresh_widget_geometry(widget)

    def _set_both_policies(self, widget: QWidget, policy: QSizePolicy.Policy) -> None:
        """Set horizontal and vertical size policy to the same value."""
        self._set_policy_pair(widget, policy, policy)

    def _set_policy_pair(
        self,
        widget: QWidget,
        horizontal: QSizePolicy.Policy,
        vertical: QSizePolicy.Policy,
    ) -> None:
        """Set horizontal and vertical size policy."""
        old_policy = widget.sizePolicy()

        widget.setSizePolicy(horizontal, vertical)
        new_policy = widget.sizePolicy()

        logger.info(
            "DebugWidget changed size policy: widget=%s old=%s new=%s",
            self._widget_log_label(widget),
            self._policy_pair_text(old_policy),
            self._policy_pair_text(new_policy),
        )

        self._refresh_widget_geometry(widget)

    def _apply_policy_to_subtree(
        self,
        root_widget: QWidget,
        horizontal: QSizePolicy.Policy,
        vertical: QSizePolicy.Policy,
    ) -> None:
        """Apply size policy to widget and descendants."""
        widgets = self._iter_widget_subtree(root_widget)

        logger.info(
            "DebugWidget applying size policy to subtree: root=%s count=%s new=H-%s, V-%s",
            self._widget_log_label(root_widget),
            len(widgets),
            self._cleaned_size_policy(horizontal),
            self._cleaned_size_policy(vertical),
        )

        for widget in widgets:
            old_policy = widget.sizePolicy()

            widget.setSizePolicy(horizontal, vertical)
            new_policy = widget.sizePolicy()

            logger.info(
                "DebugWidget changed subtree widget size policy: widget=%s old=%s new=%s",
                self._widget_log_label(widget),
                self._policy_pair_text(old_policy),
                self._policy_pair_text(new_policy),
            )

            widget.updateGeometry()
            widget.update()

        self._refresh_subtree_geometry(root_widget)

    def _set_fixed_to_current_size(self, widget: QWidget) -> None:
        """Fix widget to its current size."""
        old_policy = widget.sizePolicy()
        old_min = widget.minimumSize()
        old_max = widget.maximumSize()
        fixed_size = widget.size()

        widget.setFixedSize(fixed_size)
        widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        logger.info(
            (
                "DebugWidget fixed widget to current size: "
                "widget=%s fixedSize=%s oldPolicy=%s newPolicy=%s "
                "oldMin=%s oldMax=%s newMin=%s newMax=%s"
            ),
            self._widget_log_label(widget),
            self._size_text(fixed_size),
            self._policy_pair_text(old_policy),
            self._policy_pair_text(widget.sizePolicy()),
            self._size_text(old_min),
            self._size_text(old_max),
            self._size_text(widget.minimumSize()),
            self._size_text(widget.maximumSize()),
        )

        self._refresh_widget_geometry(widget)

    def _clear_fixed_constraints(self, widget: QWidget) -> None:
        """Clear explicit min/max constraints."""
        old_min = widget.minimumSize()
        old_max = widget.maximumSize()

        widget.setMinimumSize(QSize(0, 0))
        widget.setMaximumSize(QSize(16777215, 16777215))

        logger.info(
            (
                "DebugWidget cleared widget min/max constraints: "
                "widget=%s oldMin=%s oldMax=%s newMin=%s newMax=%s"
            ),
            self._widget_log_label(widget),
            self._size_text(old_min),
            self._size_text(old_max),
            self._size_text(widget.minimumSize()),
            self._size_text(widget.maximumSize()),
        )

        self._refresh_widget_geometry(widget)

    def _clear_constraints_in_subtree(self, root_widget: QWidget) -> None:
        """Clear explicit min/max constraints in subtree."""
        widgets = self._iter_widget_subtree(root_widget)

        logger.info(
            "DebugWidget clearing min/max constraints in subtree: root=%s count=%s",
            self._widget_log_label(root_widget),
            len(widgets),
        )

        for widget in widgets:
            old_min = widget.minimumSize()
            old_max = widget.maximumSize()

            widget.setMinimumSize(QSize(0, 0))
            widget.setMaximumSize(QSize(16777215, 16777215))

            logger.info(
                (
                    "DebugWidget cleared subtree widget min/max constraints: "
                    "widget=%s oldMin=%s oldMax=%s newMin=%s newMax=%s"
                ),
                self._widget_log_label(widget),
                self._size_text(old_min),
                self._size_text(old_max),
                self._size_text(widget.minimumSize()),
                self._size_text(widget.maximumSize()),
            )

            widget.updateGeometry()
            widget.update()

        self._refresh_subtree_geometry(root_widget)

    def _refresh_widget_geometry(self, widget: QWidget) -> None:
        """Refresh widget and parent geometry after policy changes."""
        widget.updateGeometry()
        widget.update()

        parent = widget.parentWidget()
        while parent is not None:
            parent.updateGeometry()
            parent.update()

            layout = parent.layout()
            if layout:
                layout.invalidate()
                layout.activate()

            parent = parent.parentWidget()

    def _refresh_subtree_geometry(self, root_widget: QWidget) -> None:
        """Refresh a widget subtree and its parent chain."""
        for widget in self._iter_widget_subtree(root_widget):
            widget.updateGeometry()
            widget.update()

            layout = widget.layout()
            if layout:
                layout.invalidate()
                layout.activate()

        self._refresh_widget_geometry(root_widget)

    def _collect_debug_info(self, widget: QWidget, level: int = 0) -> str:
        """Collect debug info."""
        indent = "    " * level

        self._install_context_menu(widget)

        size_policy = widget.sizePolicy()

        class_name_text = f"{indent}{self._widget_label(widget)}"

        size_policy_text = f"{indent}SizePolicy: {self._policy_pair_text(size_policy)}"

        if size_policy.horizontalStretch() or size_policy.verticalStretch():
            size_policy_text += (
                f", hStretch={size_policy.horizontalStretch()}, vStretch={size_policy.verticalStretch()}"
            )

        if size_policy.hasHeightForWidth():
            size_policy_text += ", hasHeightForWidth=True"

        lines = [
            class_name_text,
            size_policy_text,
            (
                f"{indent}Sizes: "
                f"current={self._size_text(widget.size())}, "
                f"sizeHint={self._size_text(widget.sizeHint())}, "
                f"minimumSizeHint={self._size_text(widget.minimumSizeHint())}"
            ),
        ]

        constraint_parts = []

        if widget.minimumSize() != QSize(0, 0):
            constraint_parts.append(f"minSize={self._size_text(widget.minimumSize())}")

        if widget.maximumSize() != QSize(16777215, 16777215):
            constraint_parts.append(f"maxSize={self._size_text(widget.maximumSize())}")

        if widget.baseSize() != QSize(0, 0):
            constraint_parts.append(f"baseSize={self._size_text(widget.baseSize())}")

        if constraint_parts:
            lines.append(f"{indent}Constraints: " + ", ".join(constraint_parts))

        lines.append(
            f"{indent}Geometry: "
            f"pos=({self._point_text(widget.pos())}), "
            f"geometry=({self._rect_text(widget.geometry())}), "
            f"contentsRect=({self._rect_text(widget.contentsRect())})"
        )

        layout = widget.layout()
        if layout:
            margins = layout.getContentsMargins()
            layout_parts = [layout.__class__.__name__]

            if margins != (0, 0, 0, 0):
                layout_parts.append(f"margins={margins}")

            if layout.spacing() != -1:
                layout_parts.append(f"spacing={layout.spacing()}")

            if layout.sizeConstraint().name != "SetDefaultConstraint":
                layout_parts.append(f"sizeConstraint={layout.sizeConstraint().name}")

            lines.append(f"{indent}Own Layout: " + ", ".join(layout_parts))

        parent = widget.parentWidget()
        if parent:
            parent_layout = parent.layout()

            parent_parts = [
                self._widget_label(parent),
                f"parentSize={self._size_text(parent.size())}",
            ]

            if parent_layout:
                parent_parts.append(f"parentLayout={parent_layout.__class__.__name__}")

            lines.append(f"{indent}Parent: " + ", ".join(parent_parts))

            if parent_layout:
                for index in range(parent_layout.count()):
                    item = parent_layout.itemAt(index)

                    if item and item.widget() is widget:
                        item_parts = [
                            f"index={index}",
                            f"itemGeometry=({self._rect_text(item.geometry())})",
                        ]

                        stretch = (
                            parent_layout.stretch(index) if isinstance(parent_layout, QBoxLayout) else None
                        )

                        if stretch:
                            item_parts.append(f"stretch={stretch}")

                        extra_height = item.geometry().height() - item.sizeHint().height()
                        if extra_height > 0:
                            item_parts.append(f"extraHeight={extra_height}")

                        alignment = item.alignment()
                        if alignment:
                            item_parts.append(f"alignment={alignment}")

                        item_parts.append(f"itemMin={self._size_text(item.minimumSize())}")
                        item_parts.append(f"itemHint={self._size_text(item.sizeHint())}")

                        if item.maximumSize() != QSize(16777215, 16777215):
                            item_parts.append(f"itemMax={self._size_text(item.maximumSize())}")

                        lines.append(f"{indent}Parent Layout Item: " + ", ".join(item_parts))
                        break

        children = self._direct_widget_children(widget)
        if children:
            lines.append(f"{indent}Children: {len(children)}")

        lines.append(f"{indent}Right-click: Debug → This widget / Children")

        tooltip_text = "\n".join(lines)

        for child in children:
            if level < 2:
                tooltip_text += "\n\n" + self._collect_debug_info(child, level + 1)

        return tooltip_text

    def drawDebugInfo(self, widget: QWidget) -> None:
        """DrawDebugInfo."""
        self._install_context_menu(widget)

        widget_hash = hash(widget)
        random.seed(widget_hash)
        color = QColor(
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
        )

        painter = QPainter(widget)
        painter.setPen(color)
        painter.drawRect(widget.rect().adjusted(0, 0, -1, -1))

        # widget.setToolTip(self._collect_debug_info(widget))

        font = QFont("Arial", 8)
        painter.setFont(font)
        painter.drawText(
            widget.rect().adjusted(5, 5, -5, -5),
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignLeft,
            widget.__class__.__name__,
        )


W = TypeVar("W", bound=QWidget)


def generate_debug_class(BaseClass: type[W]) -> type[W]:
    """Generate debug class."""

    class DebugClass(BaseClass):  # type: ignore
        def paintEvent(self, a0: QPaintEvent | None) -> None:
            """PaintEvent."""
            super().paintEvent(a0)
            DebugWidget().drawDebugInfo(self)

    DebugClass.__name__ = f"{BaseClass.__name__}"
    return DebugClass  # type: ignore


if __name__ == "__main__":
    app = QApplication([])

    DebugButton = generate_debug_class(QPushButton)

    main_widget = DebugWidget()
    main_widget.setObjectName("main_widget")

    layout = QVBoxLayout(main_widget)

    button_1 = DebugButton("Button 1")
    button_1.setObjectName("button_1")

    button_2 = DebugButton("Button 2")
    button_2.setObjectName("button_2")

    layout.addWidget(button_1)
    layout.addWidget(button_2)

    main_widget.show()
    app.exec()
