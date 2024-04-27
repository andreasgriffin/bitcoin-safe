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


import logging

logger = logging.getLogger(__name__)

import os
import sys
from math import ceil
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygon,
    QResizeEvent,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.util import create_button_box


def height_of_str(text, widget: QWidget, max_width: float):
    font_metrics = QFontMetrics(widget.font())
    rect = font_metrics.boundingRect(QRect(0, 0, int(max_width * 0.95), 1000), Qt.TextFlag.TextWordWrap, text)
    return rect.height() * 1.2


class StepProgressBar(QWidget):
    # Define a new signal that emits the number of the index clicked
    signal_index_clicked = pyqtSignal(int)

    def __init__(
        self,
        number_of_steps: int,
        current_index: int = 0,
        parent=None,
        mark_current_index_as_completed=False,
        clickable=True,
        use_checkmark_icon=True,
        circle_sizes: List[int] = None,
    ):
        super().__init__(parent)
        self.current_index = current_index
        self.clickable = clickable
        self.enumeration_alphabet: Optional[List[str]] = None
        self.cursor_set = False
        self.labels = [f"Step {i+1}" for i in range(number_of_steps)]  # Default labels
        self.set_circle_sizes(circle_sizes)
        self.tube_width = 4
        self.padding = 0
        self.label_distance = 5
        self.max_label_height = 0  # Initialize max label height
        self.use_checkmark_icon = use_checkmark_icon

        normalized_icon_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "../icons/checkmark.png")
        )
        self.checkmark_pixmap = QPixmap(normalized_icon_path).scaled(
            20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )  # Load and scale your checkmark image
        self.mark_current_index_as_completed = mark_current_index_as_completed
        self.tooltips = [""] * number_of_steps  # Initialize tooltips as empty strings
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_circle_sizes(self, circle_sizes: List[int] = None):
        self.radius = max(circle_sizes) if circle_sizes else 20
        self.circle_sizes = (
            circle_sizes if circle_sizes else [self.radius for i in range(self.number_of_steps)]
        )
        if len(self.circle_sizes) < self.number_of_steps:
            self.circle_sizes = self.circle_sizes * ceil(self.number_of_steps / len(self.circle_sizes))

    def set_enumeration_alphabet(self, enumeration_alphabet: Optional[List[str]]):
        self.enumeration_alphabet = enumeration_alphabet

    def set_current_index(self, index: int):
        self.current_index = index
        self.update()  # Redraw the widget

    def recalculate_max_height(self):
        max_width = self.width() / (self.number_of_steps + 1)
        self.max_label_height = 0
        for label in self.labels:
            self.max_label_height = max(self.max_label_height, height_of_str(label, self, max_width))
        self.updateGeometry()  # Notify the layout system that the widget's size hint has changed

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.recalculate_max_height()
        super().resizeEvent(event)

    @property
    def number_of_steps(self) -> int:
        return len(self.labels)

    def set_labels(self, labels: List[str]):
        self.labels = labels
        self.set_circle_sizes()
        self.tooltips = [""] * self.number_of_steps

        self.recalculate_max_height()
        self.update()

    def sizeHint(self) -> QSize:
        total_height = int(
            self.radius * 2 + max(self.max_label_height, 20) + self.label_distance + self.padding * 2
        )
        return QSize(self.width(), total_height)

    def mousePressEvent(self, event: QMouseEvent):
        # Calculate which step was clicked and emit the signal_step_clicked signal
        self.width() / (self.number_of_steps + 1)
        radius = self.radius  # Assuming you have a circle radius for each step
        circle_y = radius + self.tube_width  # Position circles near the top

        for i in range(self.number_of_steps):
            # Define the rectangle area for each step
            if self._ellipse_rect(i).contains(event.pos().toPointF()):
                self.signal_index_clicked.emit(i)  # Emit the clicked step number
                break

        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Define pens, brushes, and colors
        completed_color = QColor("#7FBA00")
        current_color = QColor("#0078D4")
        inactive_color = QColor("#BFBFBF")
        text_color = QColor("#505050")
        bubble_color = QColor("#FFFFFF")

        QPen(current_color, self.tube_width)
        completed_pen = QPen(completed_color, self.tube_width)
        inactive_pen = QPen(inactive_color, self.tube_width)
        QBrush(current_color)
        completed_brush = QBrush(completed_color)
        inactive_brush = QBrush(inactive_color)

        step_width = self._step_width()

        # Create a QTextOption for word wrapping
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.WordWrap)
        text_option.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        for i in range(self.number_of_steps):
            ellipse_rect = self._ellipse_rect(i)
            center_point = ellipse_rect.center()

            is_past_step = i < self.current_index or (
                i == self.current_index and self.mark_current_index_as_completed
            )

            # Draw connecting line
            if i < self.number_of_steps - 1:
                next_color = completed_color if i < self.current_index else inactive_color
                painter.setPen(QPen(next_color, self.tube_width))
                painter.drawLine(
                    int(center_point.x()),
                    int(center_point.y()),
                    int(center_point.x() + step_width),
                    int(center_point.y()),
                )

            # Set pen and brush for circle
            if is_past_step:
                painter.setPen(completed_pen)
                painter.setBrush(completed_brush)
            elif i == self.current_index:
                color = completed_color if self.mark_current_index_as_completed else current_color
                painter.setPen(QPen(color, self.tube_width))
                painter.setBrush(QBrush(color))
            else:
                painter.setPen(inactive_pen)
                painter.setBrush(inactive_brush)

            # Draw circle
            painter.drawEllipse(ellipse_rect)

            # Draw checkmark icon or step number
            if self.use_checkmark_icon and (
                is_past_step or (i == self.current_index and self.mark_current_index_as_completed)
            ):
                icon_size = self.checkmark_pixmap.size()
                painter.drawPixmap(
                    int(center_point.x() - icon_size.width() / 2),
                    int(center_point.y() - icon_size.height() / 2),
                    self.checkmark_pixmap,
                )
            else:
                painter.setPen(QPen(bubble_color))
                painter.drawText(
                    ellipse_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    self.format_step(i),
                )

            # Draw step text below circles
            painter.setPen(QPen(text_color))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(self._label_rect(i), self.labels[i], text_option)

        painter.end()

    def format_step(self, i: int) -> str:
        return (
            str(i + 1)
            if self.enumeration_alphabet is None
            else self.enumeration_alphabet[i % len(self.enumeration_alphabet)]
        )

    def _step_width(self):
        return self.width() / (self.number_of_steps + 1)

    def _label_rect(self, i: int):
        circle_y = self.radius + self.tube_width  # Position circles near the top
        step_width = self._step_width()
        return QRectF(
            step_width * (i + 1) - step_width / 2,
            circle_y + self.radius + self.padding + self.label_distance,
            step_width,
            self.max_label_height,
        )

    def _ellipse_rect(self, i: int):
        circle_y = self.radius + self.tube_width  # Position circles near the top
        step_width = self._step_width()
        return QRectF(
            step_width * (i + 1) - self.circle_sizes[i],
            circle_y - self.circle_sizes[i],
            2 * self.circle_sizes[i],
            2 * self.circle_sizes[i],
        )

    def set_mark_current_step_as_completed(self, value: bool):
        self.mark_current_index_as_completed = value
        self.update()

    def set_step_tooltips(self, tooltips: List[str]):
        self.tooltips = tooltips + ["" for i in range(len(tooltips), self.number_of_steps)]

    def enterEvent(self, event: QEvent) -> None:
        self.setMouseTracking(True)  # Enable mouse tracking to receive mouse move events

    def leaveEvent(self, event: QEvent) -> None:
        self.setMouseTracking(False)  # Disable mouse tracking when the mouse leaves the widget
        QToolTip.hideText()  # Hide tooltip when the cursor is not above a step
        self.restore_cursor()

    def mouseMoveEvent(self, event: QMouseEvent):
        in_circle = None
        for i in range(self.number_of_steps):
            if self._ellipse_rect(i).contains(event.pos().toPointF()):
                in_circle = i
                break

        if in_circle is None:
            QToolTip.hideText()  # Hide tooltip if the cursor is not above any step
            self.restore_cursor()
        else:
            self.set_cursor()
            QToolTip.showText(event.globalPosition().toPoint(), self.tooltips[in_circle], self)

        super().mouseMoveEvent(event)

    def restore_cursor(self):
        if self.clickable and self.cursor_set:
            self.cursor_set = False
            QApplication.restoreOverrideCursor()  # Restore to default cursor

    def set_cursor(self):
        if self.clickable and not self.cursor_set:
            self.cursor_set = True
            QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)


class HorizontalIndicator(QWidget):
    def __init__(self, number_of_steps: int, current_index: int, parent=None):
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

    def set_number_of_steps(self, number_of_steps: int):
        self.number_of_steps = number_of_steps
        self.update()

    def set_current_index(self, index: int):
        self.current_index = index
        self.update()  # Repaint the widget with the new step indicator

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Set background color using a QPalette
        # palette = self.palette()
        # palette.setColor(self.backgroundRole(), QColor("#ff0000"))  # Replace with your desired color
        # self.setPalette(palette)
        # self.setAutoFillBackground(True)

        color = QColor("#BFBFBF")
        line_y = self.height() - self.pen_width / 2  # Adjust this as needed

        # Draw the gray horizontal line
        pen = QPen(color, self.pen_width)
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
        brush = QBrush(color)
        painter.setBrush(brush)

        pen = QPen(color, 1)
        painter.setPen(pen)
        painter.drawPolygon(triangle)


class AutoResizingStackedWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self.setLayout(self._layout)  # Explicitly setting the layout
        self.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.widgets = []
        self._currentIndex = -1

    def addWidget(self, widget: QWidget):
        self.insertWidget(len(self.widgets), widget)

    def insertWidget(self, index, widget: QWidget):
        if index < 0 or index > len(self.widgets):
            raise IndexError("Index out of bounds")
        widget.setVisible(False)
        self.widgets.insert(index, widget)
        self._layout.insertWidget(index, widget)
        if len(self.widgets) == 1:
            self.setCurrentIndex(0)

    def setCurrentIndex(self, index: int):
        if 0 <= index < len(self.widgets):
            if self._currentIndex != -1:
                self.widgets[self._currentIndex].setVisible(False)
            self.widgets[index].setVisible(True)

            self._currentIndex = index
            self.adjustSizeToCurrentWidget()

    def currentIndex(self):
        return self._currentIndex

    def adjustSizeToCurrentWidget(self):
        if self._currentIndex != -1:
            currentWidget = self.widgets[self._currentIndex]
            if currentWidget.sizeHint().height() != -1 and currentWidget.sizeHint().width() != -1:
                self.setMinimumHeight(currentWidget.sizeHint().height())
            self.setMaximumSize(currentWidget.maximumSize())

    def count(self):
        return len(self.widgets)

    def removeWidget(self, widget: QWidget):
        if widget in self.widgets:
            widget.setVisible(False)
            self.widgets.remove(widget)
            self._layout.removeWidget(widget)
            widget.setParent(None)  # This is important to fully remove the widget
            if self._currentIndex >= len(self.widgets):
                self.setCurrentIndex(len(self.widgets) - 1)

    def widget(self, index: int):
        if 0 <= index < len(self.widgets):
            return self.widgets[index]
        return None

    def currentWidget(self):
        if self._currentIndex != -1:
            return self.widgets[self._currentIndex]
        return None

    def indexOf(self, widget: QWidget):
        return self.widgets.index(widget) if widget in self.widgets else -1


class StepProgressContainer(QWidget):
    signal_set_current_widget = pyqtSignal(QWidget)
    signal_widget_focus = pyqtSignal(QWidget)

    def __init__(
        self,
        step_labels: List[str],
        current_index: int = 0,
        collapsible_current_active=False,
        clickable=True,
        use_checkmark_icon=True,
        parent=None,
        sub_indices: List[int] = None,
        use_resizing_stacked_widget=True,
    ):
        super().__init__(parent)
        self.step_bar = StepProgressBar(
            len(step_labels),
            current_index=current_index,
            clickable=clickable,
            use_checkmark_icon=use_checkmark_icon,
            circle_sizes=None
            if sub_indices is None
            else [12 if i in sub_indices else 20 for i in range(len(step_labels))],
        )

        self.horizontal_indicator = HorizontalIndicator(len(step_labels), current_index)
        self.stacked_widget = AutoResizingStackedWidget() if use_resizing_stacked_widget else QStackedWidget()
        self.collapsible_current_active = collapsible_current_active
        self.clickable = clickable

        self.set_labels(step_labels)

        self.setLayout(QVBoxLayout())
        self.layout().addWidget(self.step_bar)
        self.layout().addWidget(self.horizontal_indicator)
        self.layout().setSpacing(0)  # This sets the spacing between items in the layout to zero
        self.layout().addSpacing(5)
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.layout().addWidget(self.stacked_widget)

        self.set_current_index(current_index)

        self.step_bar.signal_index_clicked.connect(self.on_click)

    def set_labels(self, labels: List[str]):
        self.step_bar.set_labels(labels=labels)
        self.horizontal_indicator.set_number_of_steps(len(labels))

        # reset widgets
        while self.stacked_widget.count() > len(labels):
            self.stacked_widget.removeWidget(self.stacked_widget.widget(0))
        for i in range(len(labels) - self.stacked_widget.count()):
            custom_widget = QWidget()
            self.stacked_widget.addWidget(custom_widget)

    def set_sub_indices(self, sub_indices: List[int] = None):
        self.step_bar.set_circle_sizes(
            None
            if sub_indices is None
            else [12 if i in sub_indices else 20 for i in range(len(self.step_bar.labels))]
        )

    def current_index(self) -> int:
        return self.step_bar.current_index

    def current_highlighted_index(self) -> int:
        return self.stacked_widget.currentIndex()

    def count(self):
        return self.step_bar.number_of_steps

    def on_click(self, index: int):
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

    def set_focus(self, index: int):
        if self.stacked_widget.currentIndex() == index:
            return
        self.stacked_widget.setCurrentIndex(index)
        self.horizontal_indicator.set_current_index(index)

        self.signal_widget_focus.emit(self.stacked_widget.widget(index))

    def set_stacked_widget_visible(self, is_visible: bool):
        self.horizontal_indicator.setVisible(is_visible)
        self.stacked_widget.setVisible(is_visible)

    def set_current_index(self, index: int):
        if self.current_index() == index:
            return

        self.step_bar.set_current_index(index)
        self.horizontal_indicator.set_current_index(index)
        self.stacked_widget.setCurrentIndex(index)

        # this order is important:
        self.signal_widget_focus.emit(self.stacked_widget.widget(index))
        # in the set_current_widget the callback functions are executed that may change the
        # visiblities. So it is critical to do the set_current_widget at the end.
        self.signal_set_current_widget.emit(self.stacked_widget.widget(index))

    def set_custom_widget(self, index: int, widget: QWidget):
        """Sets the custom widget for the specified step.

        Parameters:
        step (int): The step number to set the custom widget for.
        widget (QWidget): The custom widget to be used for the step.
        """
        current_idx = self.stacked_widget.currentIndex()

        # Remove the old widget if there is one
        old_widget = self.stacked_widget.widget(index)
        if old_widget is not None:
            self.stacked_widget.removeWidget(old_widget)

        # Add the new custom widget for the step
        self.stacked_widget.insertWidget(index, widget)

        self.stacked_widget.setCurrentIndex(current_idx)

        # if the current active widget is changed, emit the signals,
        # as if it was switched to
        if index == current_idx:
            self.signal_set_current_widget.emit(widget)
            self.signal_widget_focus.emit(widget)


class TutorialWidget(QWidget):
    def __init__(
        self,
        container: StepProgressContainer,
        widget: QWidget,
        button_box: QDialogButtonBox,
        buttonbox_always_visible=False,
    ) -> None:
        super().__init__()
        self.container = container
        self.button_box = button_box
        self.external_widgets: List[Tuple[QWidget, bool]] = []
        self.buttonbox_always_visible = buttonbox_always_visible
        self.callback_on_set_current_widget: Optional[Callable] = None

        self.setLayout(QVBoxLayout())
        current_margins = self.layout().contentsMargins()
        self.layout().setContentsMargins(5, current_margins.top(), 5, 5)  # Left, Top, Right, Bottom margins

        self.layout().addWidget(widget)
        self.layout().addWidget(button_box)

        self.container.signal_set_current_widget.connect(self.on_set_current_widget)
        self.container.signal_widget_focus.connect(self.on_widget_focus)

    def set_widget(self, widget: QWidget):
        # Check if there is at least one widget in the layout
        if self.layout().count() > 0:
            # Take the first item (widget) from the layout
            item = self.layout().takeAt(0)
            if item is not None:
                # Remove the widget from the layout and delete it
                w = item.widget()
                if w is not None:  # Check if the item is a widget
                    w.setParent(None)
                    w.deleteLater()  # Ensure the widget is deleted

        # Insert the new widget at position 0 in the layout
        self.layout().insertWidget(0, widget)

    def on_widget_focus(self, widget: QWidget):
        if self != widget:
            return
        logger.debug(f"on_widget_focus ")
        active_eq_visible = (
            self.container.step_bar.current_index == self.container.stacked_widget.currentIndex()
        )
        self.button_box.setVisible(active_eq_visible or self.buttonbox_always_visible)

        logger.debug(f"set visibility of self.external_widgets  {self.external_widgets}")
        for external_widget, set_also_visible in self.external_widgets:
            external_widget.setVisible(set_also_visible)
            logger.debug(f"Setting {external_widget.__class__.__name__}.setVisible({set_also_visible})")

    def on_set_current_widget(self, widget: QWidget):
        if self != widget:
            return

        # the callbacks should only be in on_set_current_widget, but not in on_widget_focus (when i click on it)
        if self.callback_on_set_current_widget:
            logger.debug(f"on_set_current_widget: doing callback: {self.callback_on_set_current_widget}")
            self.callback_on_set_current_widget()

    def synchronize_visiblity(self, external_widget: QWidget, set_also_visible: bool):
        existing_widgets = [t[0] for t in self.external_widgets]
        if external_widget in existing_widgets:
            # handle the case that I set the visibility before
            idx = existing_widgets.index(external_widget)
            self.external_widgets[idx] = (external_widget, set_also_visible)

        else:
            self.external_widgets.append((external_widget, set_also_visible))

    def set_callback(self, callback: Callable):
        self.callback_on_set_current_widget = callback


class MultiProgressContainer(QWidget):
    def __init__(self, step_label_dict: Dict[str, List[str]], parent: QWidget = None) -> None:
        super().__init__(parent)

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.container = StepProgressContainer(step_labels=list(step_label_dict.keys()), current_index=0)
        self.layout().addWidget(self.container)

        if len(step_label_dict) == 1:
            # no need to show a progress bar with 1 step
            self.container.step_bar.setHidden(True)
            self.container.horizontal_indicator.setHidden(True)

        # create tabs
        for i, step_labels in enumerate(step_label_dict.values()):

            export_import = StepProgressContainer(step_labels=step_labels, current_index=0)
            export_import.step_bar.set_enumeration_alphabet(
                enumeration_alphabet=[f"{i+1}.{j+1}" for j in range(len(step_labels))]
            )
            self.container.set_custom_widget(i, export_import)

            export_import.set_custom_widget(0, self.create_export_widget(export_import))
            export_import.set_custom_widget(1, self.create_import_widget(export_import))

    def go_to_next_index(self):
        current_export_import: StepProgressContainer = self.container.stacked_widget.widget(
            self.container.current_index()
        )

        if current_export_import.current_index() + 1 < current_export_import.count():
            current_export_import.set_current_index(current_export_import.current_index() + 1)
        else:
            # switch main step
            current_export_import.step_bar.set_mark_current_step_as_completed(True)

            if self.container.current_index() + 1 < self.container.count():

                self.container.set_current_index(self.container.current_index() + 1)
            else:
                self.container.step_bar.set_mark_current_step_as_completed(True)

    def go_to_previous_index(self):
        current_export_import: StepProgressContainer = self.container.stacked_widget.widget(
            self.container.current_index()
        )
        current_export_import.step_bar.set_mark_current_step_as_completed(False)
        self.container.step_bar.set_mark_current_step_as_completed(False)

        if current_export_import.current_index() - 1 >= 0:
            current_export_import.set_current_index(current_export_import.current_index() - 1)

        else:
            # switch main step
            if self.container.current_index() - 1 >= 0:
                # i can actually switch the main step back

                self.container.set_current_index(self.container.current_index() - 1)

                current_export_import = self.container.stacked_widget.widget(self.container.current_index())
                current_export_import.step_bar.set_mark_current_step_as_completed(False)

    def create_export_widget(self, container: StepProgressContainer) -> QWidget:
        widget = QWidget()
        widget.setLayout(QVBoxLayout())

        buttonbox, buttons = create_button_box(
            self.go_to_next_index,
            self.go_to_previous_index,
            ok_text="Next step",
            cancel_text="Previous step",
        )
        return TutorialWidget(container, widget, buttonbox, buttonbox_always_visible=False)

    def create_import_widget(self, container: StepProgressContainer) -> QWidget:
        widget = QWidget()
        widget.setLayout(QVBoxLayout())

        buttonbox, buttons = create_button_box(
            self.go_to_next_index,
            self.go_to_previous_index,
            ok_text="Next step",
            cancel_text="Previous step",
        )
        return TutorialWidget(container, widget, buttonbox, buttonbox_always_visible=False)


class StepProgressContainerWithButtons(StepProgressContainer):
    def __init__(
        self,
        step_labels: List[str],
        current_index: int = 0,
        collapsible_current_active=False,
        clickable=True,
        use_checkmark_icon=True,
        parent=None,
        sub_indices: List[int] = None,
        use_resizing_stacked_widget=True,
    ) -> None:
        super().__init__(
            step_labels=step_labels,
            current_index=current_index,
            collapsible_current_active=collapsible_current_active,
            clickable=clickable,
            use_checkmark_icon=use_checkmark_icon,
            parent=parent,
            sub_indices=sub_indices,
            use_resizing_stacked_widget=use_resizing_stacked_widget,
        )

        for i in range(len(step_labels)):
            super().set_custom_widget(i, self.create_tutorial_widget())

    def set_custom_widget(self, index: int, widget: QWidget):
        tutorial_widget: TutorialWidget = self.stacked_widget.widget(index)
        tutorial_widget.set_widget(widget)

        # if the current active widget is changed, emit the signals,
        # as if it was switched to
        if index == self.current_index():
            self.signal_set_current_widget.emit(tutorial_widget)
            self.signal_widget_focus.emit(tutorial_widget)

    def go_to_next_index(self):
        if self.current_index() + 1 < self.count():
            self.set_current_index(self.current_index() + 1)
        else:
            self.step_bar.set_mark_current_step_as_completed(True)

    def go_to_previous_index(self):
        self.step_bar.set_mark_current_step_as_completed(False)

        if self.current_index() - 1 >= 0:
            self.set_current_index(self.current_index() - 1)

    def create_tutorial_widget(self) -> TutorialWidget:
        widget = QWidget()
        widget.setLayout(QVBoxLayout())

        buttonbox, buttons = create_button_box(
            self.go_to_next_index,
            self.go_to_previous_index,
            ok_text="Next step",
            cancel_text="Previous step",
        )
        return TutorialWidget(self, widget, buttonbox, buttonbox_always_visible=False)


if __name__ == "__main__":

    class DemoApp(QWidget):
        def __init__(self):
            super().__init__()

            # Create the StepProgressContainer with the desired steps
            self.step_progress_container = StepProgressContainerWithButtons(
                step_labels=["Create Account\n from hardware signers", "Login", "Payment", "Confirm"],
                current_index=1,
                sub_indices=[0, 2],
            )
            self.step_progress_container.step_bar.set_enumeration_alphabet(["1.1", "1", "2.1", "2"])

            self.step_progress_container.step_bar.set_step_tooltips(
                [
                    "<font color='red'>This is an important step.</font><br><br><u>Payment information is required.</u><br><br><b>Confirm your submission.</b>",
                    "<i>Remember to check your details.</i>",
                    "<u>Payment information is required.</u>",
                    "<b>Confirm your submission.</b>",
                ]
            )

            def factory(i):
                def f(i=i):
                    print(f"callback action for {i}")

                return f

            for i in range(self.step_progress_container.count()):
                widget: TutorialWidget = self.step_progress_container.stacked_widget.widget(i)
                widget.set_callback(factory(i))
                self.step_progress_container.set_custom_widget(i, QTextEdit(f"{i}"))

            self.init_ui()

        def init_ui(self):
            self.setLayout(QVBoxLayout())

            # Buttons to navigate through steps
            next_button = QPushButton("Next Step")
            next_button.clicked.connect(self.next_index)

            prev_button = QPushButton("Previous Step")
            prev_button.clicked.connect(self.prev_index)

            self.layout().addWidget(
                self.step_progress_container
            )  # Add the step progress container instead of step_bar
            self.layout().addWidget(prev_button)
            self.layout().addWidget(next_button)
            self.layout().setContentsMargins(0, 0, 0, 0)

            self.toggle_completion_button = QPushButton("Toggle Step Completion")
            self.toggle_completion_button.clicked.connect(self.toggle_step_completion)
            self.layout().addWidget(self.toggle_completion_button)

        def toggle_step_completion(self):
            current_value = self.step_progress_container.step_bar.mark_current_index_as_completed
            self.step_progress_container.step_bar.set_mark_current_step_as_completed(not current_value)

        def next_index(self):
            if (
                self.step_progress_container.step_bar.current_index
                < self.step_progress_container.step_bar.number_of_steps
            ):
                self.step_progress_container.set_current_index(
                    self.step_progress_container.step_bar.current_index + 1
                )

        def prev_index(self):
            if self.step_progress_container.step_bar.current_index > 0:
                self.step_progress_container.set_current_index(
                    self.step_progress_container.step_bar.current_index - 1
                )

    app = QApplication(sys.argv)
    window = DemoApp()
    window.show()
    sys.exit(app.exec())
