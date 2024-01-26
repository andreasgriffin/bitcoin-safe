import os
import sys

from PySide2.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide2.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
    QTextOption,
)
from PySide2.QtWidgets import (
    QApplication,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


def height_of_str(text, widget, max_width):
    font_metrics = QFontMetrics(widget.font())
    rect = font_metrics.boundingRect(QRect(0, 0, max_width * 0.95, 1000), Qt.TextWordWrap, text)
    return rect.height() * 1.2


class StepProgressBar(QWidget):
    # Define a new signal that emits the number of the step clicked
    signal_step_clicked = Signal(int)

    def __init__(
        self,
        steps,
        current_step=0,
        parent=None,
        mark_current_step_as_completed=False,
        clickable=True,
        use_checkmark_icon=True,
    ):
        super().__init__(parent)
        self.steps = steps
        self.current_step = current_step
        self.clickable = clickable
        self.cursor_set = False
        self.radius = 20
        self.tube_width = 4
        self.padding = 0
        self.label_distance = 5
        self.max_label_height = 0  # Initialize max label height
        self.use_checkmark_icon = use_checkmark_icon

        self.step_labels = [f"Step {i+1}" for i in range(steps)]  # Default labels
        normalized_icon_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "../icons/checkmark.png")
        )
        self.checkmark_pixmap = QPixmap(normalized_icon_path).scaled(
            20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )  # Load and scale your checkmark image
        self.mark_current_step_as_completed = mark_current_step_as_completed
        self.step_tooltips = [""] * steps  # Initialize tooltips as empty strings
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_current_step(self, step):
        self.current_step = step
        self.update()  # Redraw the widget

    def recalculate_max_height(self):
        max_width = self.width() / (self.steps + 1)
        self.max_label_height = 0
        for label in self.step_labels:
            self.max_label_height = max(self.max_label_height, height_of_str(label, self, max_width))
        self.updateGeometry()  # Notify the layout system that the widget's size hint has changed

    def resizeEvent(self, event):
        self.recalculate_max_height()
        super().resizeEvent(event)

    def set_labels(self, labels):

        self.step_labels = labels + [f"Step {i+1}" for i in range(len(labels), self.steps)]

        self.recalculate_max_height()
        self.update()

    def sizeHint(self):
        total_height = (
            self.radius * 2 + max(self.max_label_height, 20) + self.label_distance + self.padding * 2
        )
        return QSize(self.width(), total_height)

    def mousePressEvent(self, event):
        # Calculate which step was clicked and emit the signal_step_clicked signal
        self.width() / (self.steps + 1)
        radius = self.radius  # Assuming you have a circle radius for each step
        circle_y = radius + self.tube_width  # Position circles near the top

        for i in range(self.steps):
            # Define the rectangle area for each step
            if self._ellipse_rect(i).contains(event.pos()):
                self.signal_step_clicked.emit(i)  # Emit the clicked step number
                break

        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

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
        text_option.setWrapMode(QTextOption.WordWrap)
        text_option.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        for i in range(self.steps):
            rect = self._ellipse_rect(i)
            center_point = rect.center()

            is_past_step = i < self.current_step or (
                i == self.current_step and self.mark_current_step_as_completed
            )

            # Draw connecting line
            if i < self.steps - 1:
                next_color = completed_color if i < self.current_step else inactive_color
                painter.setPen(QPen(next_color, self.tube_width))
                painter.drawLine(
                    center_point.x() + self.radius,
                    center_point.y(),
                    center_point.x() + step_width - self.radius,
                    center_point.y(),
                )

            # Set pen and brush for circle
            if is_past_step:
                painter.setPen(completed_pen)
                painter.setBrush(completed_brush)
            elif i == self.current_step:
                color = completed_color if self.mark_current_step_as_completed else current_color
                painter.setPen(QPen(color, self.tube_width))
                painter.setBrush(QBrush(color))
            else:
                painter.setPen(inactive_pen)
                painter.setBrush(inactive_brush)

            # Draw circle
            painter.drawEllipse(rect)

            # Draw checkmark icon or step number
            if self.use_checkmark_icon and (
                is_past_step or (i == self.current_step and self.mark_current_step_as_completed)
            ):
                icon_size = self.checkmark_pixmap.size()
                painter.drawPixmap(
                    center_point.x() - icon_size.width() / 2,
                    center_point.y() - icon_size.height() / 2,
                    self.checkmark_pixmap,
                )
            else:
                painter.setPen(QPen(bubble_color))
                painter.drawText(
                    rect,
                    Qt.AlignCenter,
                    str(i + 1),
                )

            # Draw step text below circles
            painter.setPen(QPen(text_color))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(self._label_rect(i), self.step_labels[i], text_option)

        painter.end()

    def _step_width(self):
        return self.width() / (self.steps + 1)

    def _label_rect(self, i):
        circle_y = self.radius + self.tube_width  # Position circles near the top
        step_width = self._step_width()
        return QRectF(
            step_width * (i + 1) - step_width / 2,
            circle_y + self.radius + self.padding + self.label_distance,
            step_width,
            self.max_label_height,
        )

    def _ellipse_rect(self, i):
        circle_y = self.radius + self.tube_width  # Position circles near the top
        step_width = self._step_width()
        return QRectF(
            step_width * (i + 1) - self.radius,
            circle_y - self.radius,
            2 * self.radius,
            2 * self.radius,
        )

    def set_mark_current_step_as_completed(self, value: bool):
        self.mark_current_step_as_completed = value
        self.update()

    def set_step_tooltips(self, tooltips):
        self.step_tooltips = tooltips + ["" for i in range(len(tooltips), self.steps)]

    def enterEvent(self, event):
        self.setMouseTracking(True)  # Enable mouse tracking to receive mouse move events

    def leaveEvent(self, event):
        self.setMouseTracking(False)  # Disable mouse tracking when the mouse leaves the widget
        QToolTip.hideText()  # Hide tooltip when the cursor is not above a step
        self.restore_cursor()

    def mouseMoveEvent(self, event):
        in_circle = None
        for i in range(self.steps):
            if self._ellipse_rect(i).contains(event.pos()):
                in_circle = i
                break

        if in_circle is None:
            QToolTip.hideText()  # Hide tooltip if the cursor is not above any step
            self.restore_cursor()
        else:
            self.set_cursor()
            QToolTip.showText(event.globalPos(), self.step_tooltips[in_circle], self)

        super().mouseMoveEvent(event)

    def restore_cursor(self):
        if self.clickable and self.cursor_set:
            self.cursor_set = False
            QApplication.restoreOverrideCursor()  # Restore to default cursor

    def set_cursor(self):
        if self.clickable and not self.cursor_set:
            self.cursor_set = True
            QApplication.setOverrideCursor(Qt.PointingHandCursor)


class HorizontalIndicator(QWidget):
    def __init__(self, steps, current_step, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.current_step = current_step
        self.pen_width = 2
        self.triangle_size = 13 + self.pen_width  # Half-width of the triangle
        self.triangle_height = 1 * self.triangle_size
        self.setMinimumHeight(
            self.triangle_height + self.pen_width
        )  # Set minimum height to ensure there's enough space for the line and triangle

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def set_current_step(self, step: int):
        self.current_step = step
        self.update()  # Repaint the widget with the new step indicator

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

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
        painter.drawLine(0, line_y, self.width(), line_y)

        # Draw the triangle indicator pointing up
        step_width = self.width() / (self.steps + 1)
        triangle_center = QPoint(int(step_width * (self.current_step + 1)), line_y)
        triangle = QPolygon(
            [
                triangle_center - QPoint(self.triangle_size, 0),
                triangle_center + QPoint(self.triangle_size, 0),
                triangle_center - QPoint(0, self.triangle_height),  # Pointing up
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

    def addWidget(self, widget):
        self.insertWidget(len(self.widgets), widget)

    def insertWidget(self, index, widget):
        if index < 0 or index > len(self.widgets):
            raise IndexError("Index out of bounds")
        widget.setVisible(False)
        self.widgets.insert(index, widget)
        self._layout.insertWidget(index, widget)
        if len(self.widgets) == 1:
            self.setCurrentIndex(0)

    def setCurrentIndex(self, index):
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
                self.setMinimumSize(currentWidget.sizeHint())
            self.setMaximumSize(currentWidget.maximumSize())

    def count(self):
        return len(self.widgets)

    def removeWidget(self, widget):
        if widget in self.widgets:
            widget.setVisible(False)
            self.widgets.remove(widget)
            self._layout.removeWidget(widget)
            widget.setParent(None)  # This is important to fully remove the widget
            if self._currentIndex >= len(self.widgets):
                self.setCurrentIndex(len(self.widgets) - 1)

    def widget(self, index):
        if 0 <= index < len(self.widgets):
            return self.widgets[index]
        return None

    def currentWidget(self):
        if self._currentIndex != -1:
            return self.widgets[self._currentIndex]
        return None

    def indexOf(self, widget):
        return self.widgets.index(widget) if widget in self.widgets else -1


class StepProgressContainer(QWidget):
    def __init__(
        self,
        steps,
        current_step=0,
        hide_on_click=True,
        clickable=True,
        use_checkmark_icon=True,
        parent=None,
    ):
        super().__init__(parent)
        self.step_bar = StepProgressBar(
            steps,
            current_step=current_step,
            clickable=clickable,
            use_checkmark_icon=use_checkmark_icon,
        )
        self.horizontal_indicator = HorizontalIndicator(steps, current_step)
        self.stacked_widget = AutoResizingStackedWidget()
        self.hide_on_click = hide_on_click
        self.clickable = clickable

        # Create a custom widget for each step
        for i in range(steps):
            custom_widget = QWidget()
            self.stacked_widget.addWidget(custom_widget)

        self.setLayout(QVBoxLayout())
        self.layout().addWidget(self.step_bar)
        self.layout().addWidget(self.horizontal_indicator)
        self.layout().setSpacing(0)  # This sets the spacing between items in the layout to zero
        self.layout().addSpacing(5)
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.layout().addWidget(self.stacked_widget)

        self.set_current_step(current_step)

        self.step_bar.signal_step_clicked.connect(self.on_click)

    def on_click(self, step: int):
        if not self.clickable:
            return

        currently_visible_step = (
            self.stacked_widget.currentIndex() if self.stacked_widget.isVisible() else None
        )

        if currently_visible_step is None:
            if self.hide_on_click:
                self.set_stacked_widget_visible(True)
        else:
            if currently_visible_step == step:
                # hide the stacked widget
                if self.hide_on_click:
                    self.set_stacked_widget_visible(False)

        self.set_clicked_step(step)

    def set_clicked_step(self, step):
        self.stacked_widget.setCurrentIndex(step)
        self.horizontal_indicator.set_current_step(step)

    def set_stacked_widget_visible(self, is_visible):
        self.horizontal_indicator.setVisible(is_visible)
        self.stacked_widget.setVisible(is_visible)

    def set_current_step(self, step):
        self.step_bar.set_current_step(step)
        self.horizontal_indicator.set_current_step(step)
        self.stacked_widget.setCurrentIndex(step)

    def set_custom_widget(self, step, widget):
        """Sets the custom widget for the specified step.

        Parameters:
        step (int): The step number to set the custom widget for.
        widget (QWidget): The custom widget to be used for the step.
        """
        curreent_idx = self.stacked_widget.currentIndex()

        # Remove the old widget if there is one
        old_widget = self.stacked_widget.widget(step)
        if old_widget is not None:
            self.stacked_widget.removeWidget(old_widget)

        # Add the new custom widget for the step
        self.stacked_widget.insertWidget(step, widget)

        self.stacked_widget.setCurrentIndex(curreent_idx)


class DemoApp(QWidget):
    def __init__(self):
        super().__init__()

        # Create the StepProgressContainer with the desired steps
        self.step_progress_container = StepProgressContainer(steps=8, current_step=1)
        self.step_progress_container.step_bar.set_labels(
            ["Create Account\n from hardware signers", "Login", "Payment", "Confirm"]
        )
        self.step_progress_container.step_bar.set_step_tooltips(
            [
                "<font color='red'>This is an important step.</font><br><br><u>Payment information is required.</u><br><br><b>Confirm your submission.</b>",
                "<i>Remember to check your details.</i>",
                "<u>Payment information is required.</u>",
                "<b>Confirm your submission.</b>",
            ]
        )
        for i in range(5):
            self.step_progress_container.set_custom_widget(i, QTextEdit(f"{i}"))

        self.init_ui()

    def init_ui(self):
        self.setLayout(QVBoxLayout())

        # Buttons to navigate through steps
        next_button = QPushButton("Next Step")
        next_button.clicked.connect(self.next_step)

        prev_button = QPushButton("Previous Step")
        prev_button.clicked.connect(self.prev_step)

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
        current_value = self.step_progress_container.step_bar.mark_current_step_as_completed
        self.step_progress_container.step_bar.set_mark_current_step_as_completed(not current_value)

    def next_step(self):
        if self.step_progress_container.step_bar.current_step < self.step_progress_container.step_bar.steps:
            self.step_progress_container.set_current_step(
                self.step_progress_container.step_bar.current_step + 1
            )

    def prev_step(self):
        if self.step_progress_container.step_bar.current_step > 0:
            self.step_progress_container.set_current_step(
                self.step_progress_container.step_bar.current_step - 1
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DemoApp()
    window.show()
    sys.exit(app.exec_())
