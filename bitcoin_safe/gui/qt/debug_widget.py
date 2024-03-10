import random

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PyQt6.QtWidgets import (
    QApplication,
    QPushButton,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)


class DebugWidget(QWidget):
    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        self.drawDebugInfo(self)

    def _cleaned_size_policy(self, policy):
        return str(policy).split(".")[-1]

    def _collect_debug_info(self, widget: QWidget, level=0):
        indent = "    " * level
        sizePolicy = widget.sizePolicy()
        sizePolicyText = f"{indent}SP: H-{self._cleaned_size_policy(sizePolicy.horizontalPolicy())}, V-{self._cleaned_size_policy(sizePolicy.verticalPolicy())}"
        # sizeText = f"{indent}Size: Min {widget.minimumWidth()}x{widget.minimumHeight()}, Max {widget.maximumWidth()}x{widget.maximumHeight()}"
        sizeText = f"{indent}sizeHint: {widget.sizeHint()}"
        classNameText = f"{indent}Class: {widget.__class__.__name__}"

        # Margins (for QLayout if exists)
        if widget.layout():
            margins = widget.layout().getContentsMargins()
            marginText = f"{indent}Margins: {margins}"
        else:
            marginText = f"{indent}No layout/margins"

        # Padding (generalized)
        option = QStyleOption()
        option.initFrom(widget)
        padding = option.rect
        paddingText = f"{indent}Padding: {padding}"

        tooltipText = f"{classNameText}\n{sizePolicyText}\n{sizeText}\n{marginText}\n{paddingText}"

        # Recursively collect info from children
        for child in widget.children():
            if isinstance(child, QWidget) and level < 2:
                tooltipText += "\n\n" + self._collect_debug_info(child, level + 1)

        return tooltipText

    def drawDebugInfo(self, widget: QWidget):
        widget_hash = hash(widget)
        random.seed(widget_hash)
        color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

        painter = QPainter(widget)
        painter.setPen(color)
        painter.drawRect(widget.rect().adjusted(0, 0, -1, -1))

        # Set tooltip with recursive information
        widget.setToolTip(self._collect_debug_info(widget))

        # Display size policy and size information on widget
        font = QFont("Arial", 8)
        painter.setFont(font)
        painter.drawText(
            widget.rect().adjusted(5, 5, -5, -5),
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignLeft,
            widget.__class__.__name__,
        )


def generate_debug_class(BaseClass) -> QWidget:
    class DebugClass(BaseClass):
        def paintEvent(self, event: QPaintEvent):
            super().paintEvent(event)
            DebugWidget().drawDebugInfo(self)

    DebugClass.__name__ = f"{BaseClass.__name__}"
    return DebugClass


if __name__ == "__main__":
    app = QApplication([])

    DebugButton = generate_debug_class(QPushButton)
    main_widget = DebugWidget()
    layout = QVBoxLayout(main_widget)
    layout.addWidget(DebugButton("Button 1"))
    layout.addWidget(DebugButton("Button 2"))

    main_widget.show()
    app.exec()
