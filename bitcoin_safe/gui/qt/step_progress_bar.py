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
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from math import ceil
from typing import cast

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygon
from PyQt6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.signals import SignalsMin

from .util import get_neutral_surface_colors, set_margins

logger = logging.getLogger(__name__)


class StepProgressBar(QWidget):
    signal_index_clicked = cast(SignalProtocol[[int]], pyqtSignal(int))

    def __init__(
        self,
        number_of_steps: int,
        current_index: int = 0,
        parent=None,
        mark_current_index_as_completed=False,
        clickable=True,
        use_checkmark_icon=True,
        circle_sizes: list[int] | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.current_index = current_index
        self.clickable = clickable
        self.enumeration_alphabet: list[str] | None = None
        self.cursor_set = False
        self.labels = [f"Step {i + 1}" for i in range(number_of_steps)]
        self.segment_gap = 16
        self.padding = 6
        self.use_checkmark_icon = use_checkmark_icon
        self.mark_current_index_as_completed = mark_current_index_as_completed
        self.circle_sizes: list[int] = []
        self.segment_heights: list[int] = []
        self.tooltips = self.labels.copy()
        self.set_circle_sizes(circle_sizes)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_circle_sizes(self, circle_sizes: list[int] | None = None) -> None:
        """Set segment heights based on the previous circle size input."""
        default_size = 20
        self.circle_sizes = (
            circle_sizes.copy() if circle_sizes else [default_size for _i in range(self.number_of_steps)]
        )
        if len(self.circle_sizes) < self.number_of_steps and self.circle_sizes:
            multiplier = ceil(self.number_of_steps / len(self.circle_sizes))
            self.circle_sizes = (self.circle_sizes * multiplier)[: self.number_of_steps]
        self.segment_heights = [max(4, int(round(size / 4))) for size in self.circle_sizes]
        self.updateGeometry()
        self.update()

    def set_enumeration_alphabet(self, enumeration_alphabet: list[str] | None) -> None:
        """Set enumeration alphabet."""
        self.enumeration_alphabet = enumeration_alphabet

    def set_current_index(self, index: int) -> None:
        """Set current index."""
        self.current_index = index
        self.update()

    @property
    def number_of_steps(self) -> int:
        """Number of steps."""
        return len(self.labels)

    def set_labels(self, labels: list[str]) -> None:
        """Set labels."""
        self.labels = labels
        self.tooltips = labels.copy()
        self.set_circle_sizes(self.circle_sizes if self.circle_sizes else None)

    def sizeHint(self) -> QSize:
        """Size hint for the segmented progress bar."""
        return QSize(self.width(), max(self.segment_heights, default=6) + self.padding * 2)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        """Emit the clicked step when a segment is pressed."""
        if not a0:
            super().mousePressEvent(a0)
            return

        for i in range(self.number_of_steps):
            if self._segment_rect(i).contains(a0.position()):
                self.signal_index_clicked.emit(i)
                break

        super().mousePressEvent(a0)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """Draw the segmented progress state."""
        del a0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        completed_color = QColor("#10B814")
        current_color = QColor("#2C7DD1")
        inactive_color = get_neutral_surface_colors().panel_background

        for i in range(self.number_of_steps):
            is_past_step = i < self.current_index or (
                i == self.current_index and self.mark_current_index_as_completed
            )
            if is_past_step:
                color = completed_color
            elif i == self.current_index:
                color = completed_color if self.mark_current_index_as_completed else current_color
            else:
                color = inactive_color

            segment_rect = self._segment_rect(i)
            radius = segment_rect.height() / 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(segment_rect, radius, radius)

        painter.end()

    def format_step(self, i: int) -> str:
        """Format step."""
        return (
            str(i + 1)
            if self.enumeration_alphabet is None
            else self.enumeration_alphabet[i % len(self.enumeration_alphabet)]
        )

    def _segment_rect(self, i: int) -> QRectF:
        """Return the geometry for a single step segment."""
        if not self.number_of_steps:
            return QRectF()

        total_gap = self.segment_gap * max(0, self.number_of_steps - 1)
        available_width = max(1.0, self.width() - total_gap)
        segment_width = max(1.0, available_width / self.number_of_steps)
        segment_height = self.segment_heights[min(i, len(self.segment_heights) - 1)]
        top = (self.height() - segment_height) / 2
        left = i * (segment_width + self.segment_gap)
        return QRectF(left, top, segment_width, segment_height)

    def set_mark_current_step_as_completed(self, value: bool) -> None:
        """Set mark current step as completed."""
        self.mark_current_index_as_completed = value
        self.update()

    def set_step_tooltips(self, tooltips: list[str]) -> None:
        """Set step tooltips."""
        self.tooltips = tooltips + ["" for _i in range(len(tooltips), self.number_of_steps)]

    def enterEvent(self, event: QEvent | None) -> None:
        """Enable mouse tracking on hover."""
        del event
        self.setMouseTracking(True)

    def leaveEvent(self, a0: QEvent | None) -> None:
        """Disable hover state when the cursor leaves the widget."""
        del a0
        self.setMouseTracking(False)
        QToolTip.hideText()
        self.restore_cursor()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        """Show the step tooltip for the hovered segment."""
        if not a0:
            super().mouseMoveEvent(a0)
            return

        hovered_index: int | None = None
        for i in range(self.number_of_steps):
            if self._segment_rect(i).contains(a0.position()):
                hovered_index = i
                break

        if hovered_index is None:
            QToolTip.hideText()
            self.restore_cursor()
        else:
            self.set_cursor()
            QToolTip.showText(a0.globalPosition().toPoint(), self.tooltips[hovered_index], self)

        super().mouseMoveEvent(a0)

    def restore_cursor(self) -> None:
        """Restore cursor."""
        if self.clickable and self.cursor_set:
            self.cursor_set = False
            QApplication.restoreOverrideCursor()

    def set_cursor(self) -> None:
        """Set cursor."""
        if self.clickable and not self.cursor_set:
            self.cursor_set = True
            QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)


class HorizontalIndicator(QWidget):
    def __init__(self, number_of_steps: int, current_index: int, parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.number_of_steps = number_of_steps
        self.current_index = current_index
        self.pen_width = 2
        self.triangle_size = 13 + self.pen_width  # Half-width of the triangle
        self.triangle_height = 1 * self.triangle_size
        self.setMinimumHeight(
            self.triangle_height + self.pen_width
        )  # Set minimum height to ensure there's enough space for the line and triangle

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_number_of_steps(self, number_of_steps: int) -> None:
        """Set number of steps."""
        self.number_of_steps = number_of_steps
        self.update()

    def set_current_index(self, index: int) -> None:
        """Set current index."""
        self.current_index = index
        self.update()  # Repaint the widget with the new step indicator

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """PaintEvent."""
        super().paintEvent(a0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Set background color using a QPalette
        # palette = self.palette()
        # palette.setColor(self.backgroundRole(), QColor("#ff0000"))  # Replace with your desired color
        # self.setPalette(palette)
        # self.setAutoFillBackground(True)

        gray = get_neutral_surface_colors().panel_background

        line_y = self.height() - self.pen_width / 2  # Adjust this as needed

        # Draw the gray horizontal line
        pen = QPen(gray, self.pen_width)
        painter.setPen(pen)
        painter.drawLine(0, int(line_y), int(self.width()), int(line_y))

        # Draw the triangle indicator pointing up
        step_width = self.width() / (self.number_of_steps + 1)
        triangle_center = QPoint(int(step_width * (self.current_index + 1)), int(line_y))
        triangle = QPolygon(
            [
                triangle_center - QPoint(int(self.triangle_size), 0),
                triangle_center + QPoint(int(self.triangle_size), 0),
                triangle_center - QPoint(0, int(self.triangle_height)),  # Pointing up
            ]
        )
        brush = QBrush(gray)
        painter.setBrush(brush)

        pen = QPen(gray, 1)
        painter.setPen(pen)
        painter.drawPolygon(triangle)


class AutoResizingStackedWidget(QWidget):
    def __init__(self, parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self.setLayout(self._layout)  # Explicitly setting the layout
        self._layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.widgets: list[QWidget] = []
        self._currentIndex = -1

    def addWidget(self, widget: QWidget) -> None:
        """AddWidget."""
        self.insertWidget(len(self.widgets), widget)

    def insertWidget(self, index, widget: QWidget) -> None:
        """InsertWidget."""
        if index < 0 or index > len(self.widgets):
            raise IndexError("Index out of bounds")
        widget.setVisible(False)
        self.widgets.insert(index, widget)
        self._layout.insertWidget(index, widget)
        if len(self.widgets) == 1:
            self.setCurrentIndex(0)

    def setCurrentIndex(self, index: int) -> None:
        """SetCurrentIndex."""
        if 0 <= index < len(self.widgets):
            if self._currentIndex != -1:
                if 0 <= self._currentIndex < len(self.widgets):
                    self.widgets[self._currentIndex].setVisible(False)
            self.widgets[index].setVisible(True)

            self._currentIndex = index

    def currentIndex(self) -> int:
        """CurrentIndex."""
        return self._currentIndex

    def count(self) -> int:
        """Count."""
        return len(self.widgets)

    def removeWidget(self, widget: QWidget) -> None:
        """RemoveWidget."""
        if widget in self.widgets:
            self.widgets.remove(widget)
            widget.setParent(None)  # type: ignore[call-overload]
            if self._currentIndex >= len(self.widgets):
                self.setCurrentIndex(len(self.widgets) - 1)

    def widget(self, index: int) -> QWidget | None:
        """Widget."""
        if 0 <= index < len(self.widgets):
            return self.widgets[index]
        return None

    def currentWidget(self) -> QWidget | None:
        """CurrentWidget."""
        if self._currentIndex != -1:
            return self.widgets[self._currentIndex]
        return None

    def indexOf(self, widget: QWidget) -> int:
        """IndexOf."""
        return self.widgets.index(widget) if widget in self.widgets else -1


class StepProgressContainer(QWidget):
    signal_set_current_widget = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))
    signal_widget_focus = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))
    signal_widget_unfocus = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(
        self,
        step_labels: list[str],
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        step_subtitles: list[str | None] | None = None,
        current_index: int = 0,
        collapsible_current_active=False,
        clickable=True,
        use_checkmark_icon=True,
        parent=None,
        sub_indices: list[int] | None = None,
        use_resizing_stacked_widget=True,
        hide_steps_if_only_1=True,
        show_step_state_legend=False,
        show_header_separator=True,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            parent=parent,
        )
        self.loop_in_thread = loop_in_thread
        self.signals_min = signals_min
        self.hide_steps_if_only_1 = hide_steps_if_only_1
        self.show_step_state_legend = show_step_state_legend
        self.show_header_separator = show_header_separator
        self.step_subtitles: list[str] = []
        self.step_bar = StepProgressBar(
            len(step_labels),
            current_index=current_index,
            clickable=clickable,
            use_checkmark_icon=use_checkmark_icon,
            circle_sizes=(
                None
                if sub_indices is None
                else [12 if i in sub_indices else 20 for i in range(len(step_labels))]
            ),
        )
        self.stacked_widget: AutoResizingStackedWidget | QStackedWidget = (
            AutoResizingStackedWidget() if use_resizing_stacked_widget else QStackedWidget()
        )
        self.collapsible_current_active = collapsible_current_active
        self.clickable = clickable

        self.legend_widget = QWidget(self)
        self.legend_layout = QHBoxLayout(self.legend_widget)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(36)
        self.legend_layout.addWidget(self._create_legend_label(self.tr("Completed"), "#10B814"))
        self.legend_layout.addWidget(self._create_legend_label(self.tr("Current"), "#2C7DD1"))
        self.legend_layout.addWidget(self._create_legend_label(self.tr("Future incomplete steps"), "#9A9A9A"))
        self.legend_layout.addStretch(1)

        self.active_step_label = QLabel(self)
        self.active_step_label.setWordWrap(True)

        self.active_step_subtitle = QLabel(self)
        self.active_step_subtitle.setWordWrap(True)
        subtitle_palette = self.active_step_subtitle.palette()
        subtitle_color = subtitle_palette.color(self.active_step_subtitle.foregroundRole())
        subtitle_color.setAlpha(170)
        subtitle_palette.setColor(self.active_step_subtitle.foregroundRole(), subtitle_color)
        self.active_step_subtitle.setPalette(subtitle_palette)

        self.header_separator = QFrame(self)
        self.header_separator.setFrameShape(QFrame.Shape.HLine)
        self.header_separator.setFrameShadow(QFrame.Shadow.Plain)
        self.header_separator.setStyleSheet("color: #C9C9C9;")

        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.legend_widget)
        self._layout.addWidget(self.step_bar)
        self._layout.addWidget(self.active_step_label)
        self._layout.addWidget(self.active_step_subtitle)
        self._layout.addWidget(self.header_separator)
        self._layout.setSpacing(6)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.stacked_widget)

        self.set_labels(step_labels)
        self.set_step_subtitles(step_subtitles)
        self.set_step_state_legend_visible(show_step_state_legend)
        self.set_current_index(current_index)

        self.step_bar.signal_index_clicked.connect(self.on_click)

    def set_labels(self, labels: list[str]) -> None:
        """Set labels."""
        if labels == self.step_bar.labels and self.stacked_widget.count() == len(labels):
            return

        self.step_bar.set_labels(labels=labels)

        # reset widgets
        while self.stacked_widget.count() > len(labels):
            widget = self.stacked_widget.widget(self.stacked_widget.count() - 1)
            if widget:
                self.stacked_widget.removeWidget(widget)
        for _i in range(len(labels) - self.stacked_widget.count()):
            custom_widget = QWidget()
            self.stacked_widget.addWidget(custom_widget)
        self._sync_step_subtitle_count()
        self._update_step_texts()

    def set_step_subtitles(self, subtitles: list[str | None] | None) -> None:
        """Set optional subtitles for each step."""
        self.step_subtitles = [subtitle or "" for subtitle in subtitles] if subtitles else []
        self._sync_step_subtitle_count()
        self._update_step_texts()

    def set_step_state_legend_visible(self, visible: bool) -> None:
        """Show or hide the color legend above the progress bar."""
        self.show_step_state_legend = visible
        self._update_header_visibility()

    def set_header_separator_visible(self, visible: bool) -> None:
        """Show or hide the separator between the header and the content."""
        self.show_header_separator = visible
        self._update_header_visibility()

    def set_sub_indices(self, sub_indices: list[int] | None = None) -> None:
        """Set sub indices."""
        self.step_bar.set_circle_sizes(
            None
            if sub_indices is None
            else [12 if i in sub_indices else 20 for i in range(len(self.step_bar.labels))]
        )

    def current_index(self) -> int:
        """Current index."""
        return self.step_bar.current_index

    def current_highlighted_index(self) -> int:
        """Current highlighted index."""
        return self.stacked_widget.currentIndex()

    def count(self) -> int:
        """Count."""
        return self.step_bar.number_of_steps

    def on_click(self, index: int) -> None:
        """On click."""
        if not self.clickable:
            return

        currently_visible_step = (
            self.stacked_widget.currentIndex() if self.stacked_widget.isVisible() else None
        )

        if currently_visible_step is None:
            if self.collapsible_current_active:
                self.set_stacked_widget_visible(True)
        else:
            if currently_visible_step == index:
                # hide the stacked widget
                if self.collapsible_current_active:
                    self.set_stacked_widget_visible(False)

        self.set_focus(index)

    def set_focus(self, index: int) -> None:
        """Set focus."""
        old_index = self.stacked_widget.currentIndex()

        if old_index == index:
            self._update_step_texts()
            return

        self.stacked_widget.setCurrentIndex(index)
        self._update_step_texts()

        if widget_unfocus := self.stacked_widget.widget(old_index):
            self.signal_widget_unfocus.emit(widget_unfocus)
        if widget_focus := self.stacked_widget.widget(index):
            self.signal_widget_focus.emit(widget_focus)

    def set_stacked_widget_visible(self, is_visible: bool) -> None:
        """Set stacked widget visible."""
        self.stacked_widget.setVisible(is_visible)

    def set_current_index(self, index: int) -> None:
        """Set current index."""
        old_index = self.current_index()

        if old_index == index and self.stacked_widget.currentIndex() == index:
            self._update_step_texts()
            return

        self.step_bar.set_current_index(index)
        self.stacked_widget.setCurrentIndex(index)
        self._update_step_texts()

        # this order is important:
        if old_widget := self.stacked_widget.widget(old_index):
            self.signal_widget_unfocus.emit(old_widget)
        if new_widget := self.stacked_widget.widget(index):
            self.signal_widget_focus.emit(new_widget)
            # in the set_current_widget the callback functions are executed that may change the
            # visiblities. So it is critical to do the set_current_widget at the end.
            self.signal_set_current_widget.emit(new_widget)

    def clear_widgets(self) -> None:
        """Clear widgets."""
        while self.stacked_widget.count():
            widget = self.stacked_widget.widget(0)
            if widget:
                widget.setParent(None)
                self.stacked_widget.removeWidget(widget)

    def set_custom_widget(self, index: int, widget: QWidget) -> None:
        """Sets the custom widget for the specified step.

        Parameters:
        step (int): The step number to set the custom widget for.
        widget (QWidget): The custom widget to be used for the step.
        """
        current_idx = self.stacked_widget.currentIndex()

        # Remove the old widget if there is one
        old_widget = self.stacked_widget.widget(index)
        if old_widget is not None:
            self.signal_widget_unfocus.emit(old_widget)
            self.stacked_widget.removeWidget(old_widget)

        # Add the new custom widget for the step
        self.stacked_widget.insertWidget(index, widget)

        self.stacked_widget.setCurrentIndex(current_idx)

        # if the current active widget is changed, emit the signals,
        # as if it was switched to
        if index == current_idx:
            self.signal_set_current_widget.emit(widget)
            self.signal_widget_focus.emit(widget)
        self._update_step_texts()

    def close(self) -> bool:
        """Close."""
        self.clear_widgets()
        return super().close()

    def _create_legend_label(self, text: str, color: str) -> QLabel:
        """Create a colored legend label."""
        label = QLabel(text, self)
        label.setStyleSheet(f"color: {color}; font-weight: 700;")
        return label

    def _sync_step_subtitle_count(self) -> None:
        """Pad the subtitle list to match the number of labels."""
        if len(self.step_subtitles) < self.count():
            self.step_subtitles.extend([""] * (self.count() - len(self.step_subtitles)))
        elif len(self.step_subtitles) > self.count():
            self.step_subtitles = self.step_subtitles[: self.count()]

    def _header_is_visible(self) -> bool:
        """Return whether the progress header should be shown."""
        return not (self.count() <= 1 and self.hide_steps_if_only_1)

    def _update_header_visibility(self) -> None:
        """Apply header visibility state to each header element."""
        header_is_visible = self._header_is_visible()
        self.legend_widget.setVisible(header_is_visible and self.show_step_state_legend)
        self.step_bar.setVisible(header_is_visible)
        self.active_step_label.setVisible(header_is_visible)
        self.active_step_subtitle.setVisible(header_is_visible and bool(self.active_step_subtitle.text()))
        self.header_separator.setVisible(header_is_visible and self.show_header_separator)

    def _step_text_index(self) -> int:
        """Return the index that drives the visible step text."""
        highlighted_index = self.stacked_widget.currentIndex()
        if 0 <= highlighted_index < self.count():
            return highlighted_index
        return self.current_index()

    def _update_step_texts(self) -> None:
        """Refresh the title and subtitle below the segmented bar."""
        if not self.count():
            self.active_step_label.clear()
            self.active_step_subtitle.clear()
            self._update_header_visibility()
            return

        index = self._step_text_index()
        if not 0 <= index < self.count():
            self.active_step_label.clear()
            self.active_step_subtitle.clear()
            self._update_header_visibility()
            return

        step_prefix = self.tr("Step {current} of {total}").format(current=index + 1, total=self.count())
        step_title = self.step_bar.labels[index]
        if step_title:
            self.active_step_label.setText(
                f"<span style='font-weight:700;'>{escape(step_prefix)}</span> - {escape(step_title)}"
            )
        else:
            self.active_step_label.setText(f"<span style='font-weight:700;'>{escape(step_prefix)}</span>")

        subtitle = self.step_subtitles[index] if index < len(self.step_subtitles) else ""
        self.active_step_subtitle.setText(subtitle)
        self._update_header_visibility()


@dataclass
class VisibilityOption:
    widget: QWidget
    on_focus_set_visible: bool
    on_unfocus_set_visible: bool | None = None


class TutorialWidget(QWidget):
    def __init__(
        self,
        container: StepProgressContainer,
        widget: QWidget,
        button_box: QDialogButtonBox,
        buttonbox_always_visible=False,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.widget = widget
        self.container = container
        self.button_box = button_box
        self.visibility_options: list[VisibilityOption] = []
        self.buttonbox_always_visible = buttonbox_always_visible
        self.callback_on_set_current_widget: Callable | None = None

        self._layout = QVBoxLayout(self)

        set_margins(
            self._layout,
            {
                Qt.Edge.RightEdge: 0,
                Qt.Edge.LeftEdge: 0,
                Qt.Edge.BottomEdge: 0,
            },
        )

        self._layout.addWidget(widget)
        self._layout.addWidget(button_box)

        self.container.signal_set_current_widget.connect(self.on_set_current_widget)
        self.container.signal_widget_unfocus.connect(self.on_widget_unfocus)
        self.container.signal_widget_focus.connect(self.on_widget_focus)

    def set_widget(self, widget: QWidget) -> None:
        # Check if there is at least one widget in the layout
        """Set widget."""
        if self._layout.count() > 0:
            # Take the first item (widget) from the layout
            item = self._layout.takeAt(0)
            if item is not None:
                # Remove the widget from the layout and delete it
                w = item.widget()
                if w is not None:  # Check if the item is a widget
                    w.setParent(None)  # type: ignore[call-overload]

        # Insert the new widget at position 0 in the layout
        self._layout.insertWidget(0, widget)

    def on_widget_unfocus(self, widget: QWidget) -> None:
        """On widget unfocus."""
        if self != widget:
            return
        logger.debug("on_widget_unfocus ")
        logger.debug(f"unset visibility of {self.visibility_options}")
        for visibility_option in self.visibility_options:
            if visibility_option.on_unfocus_set_visible is not None:
                visibility_option.widget.setVisible(visibility_option.on_unfocus_set_visible)
                logger.debug(
                    f"Setting {visibility_option.widget.__class__.__name__}."
                    "setVisible({visibility_option.on_unfocus_set_visible})"
                )

    def on_widget_focus(self, widget: QWidget) -> None:
        """On widget focus."""
        if self != widget:
            return
        logger.debug("on_widget_focus ")
        active_eq_visible = (
            self.container.step_bar.current_index == self.container.stacked_widget.currentIndex()
        )
        self.button_box.setVisible(active_eq_visible or self.buttonbox_always_visible)

        logger.debug(f"set visibility of {self.visibility_options}")
        for visibility_option in self.visibility_options:
            visibility_option.widget.setVisible(visibility_option.on_focus_set_visible)
            logger.debug(
                f"Setting {visibility_option.widget.__class__.__name__}."
                f"setVisible({visibility_option.on_focus_set_visible})"
            )

    def on_set_current_widget(self, widget: QWidget) -> None:
        """On set current widget."""
        if self != widget:
            return

        # the callbacks should only be in on_set_current_widget,
        # but not in on_widget_focus (when i click on it)
        if self.callback_on_set_current_widget:
            logger.debug(f"on_set_current_widget: doing callback: {self.callback_on_set_current_widget}")
            self.callback_on_set_current_widget()

    def synchronize_visiblity(self, visibility_option: VisibilityOption) -> None:
        """Synchronize visiblity."""
        existing_widgets = [t.widget for t in self.visibility_options]
        if visibility_option.widget in existing_widgets:
            # handle the case that I set the visibility before
            idx = existing_widgets.index(visibility_option.widget)
            self.visibility_options[idx] = visibility_option
        else:
            self.visibility_options.append(visibility_option)

    def set_callback(self, callback: Callable) -> None:
        """Set callback."""
        self.callback_on_set_current_widget = callback
