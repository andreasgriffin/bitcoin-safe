from typing import List

from PyQt6.QtCore import QMargins, Qt
from PyQt6.QtGui import QFont, QResizeEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit

from .image_widget import QRCodeWidgetSVG


class ReceiveGroup(QGroupBox):
    def __init__(
        self,
        category: str,
        hex_color: str,
        address: str,
        qr_uri: str,
        width=170,
    ):
        super().__init__(category)

        # Set the stylesheet for the QGroupBox
        self.setStyleSheet(
            f"""
            QGroupBox {{
                background-color: {hex_color};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top center; /* Center align the title */
                margin-top: 3px; /* Margin at the top for the title */
                margin-left: 0px; /* Align the title text to the center */
                margin-right: 0px;
                }}
            """
        )
        font = QFont()
        font.setBold(True)
        self.setFont(font)

        self.setFixedWidth(width)

        v_layout = QVBoxLayout(self)
        v_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        v_layout.setSpacing(3)

        # QR Code
        self.qr_code = QRCodeWidgetSVG()
        self.qr_code.setMinimumHeight(30)
        self.qr_code.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.qr_code.set_data_list([qr_uri])
        v_layout.addWidget(self.qr_code)

        self.text_edit = ButtonEdit(input_field=QTextEdit(address))
        self.text_edit.setReadOnly(True)
        self.text_edit.add_copy_button()
        self.text_edit.input_field.setStyleSheet(
            f"""
            background-color: {hex_color};
            """
        )
        self.text_edit.setFixedHeight(55)
        v_layout.addWidget(self.text_edit)


class NoVerticalScrollArea(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.horizontalScrollBar().valueChanged.connect(self.recenterVerticalScroll)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Override to do nothing, preventing vertical scrolling
        pass

    def recenterVerticalScroll(self):
        # Recenter the vertical scroll position when horizontal scrollbar state changes
        if self.widget():
            max_scroll = self.verticalScrollBar().maximum()
            self.verticalScrollBar().setValue(max_scroll // 2)

    # Override resizeEvent to handle window resizing
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.recenterVerticalScroll()


class QuickReceive(QWidget):
    def __init__(self, title="Quick Receive"):
        super().__init__()

        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,  # Horizontal size policy
            QSizePolicy.Policy.Fixed,  # Vertical size policy
        )

        # Horizontal Layout for Scroll Area content
        self.h_layout = QHBoxLayout()

        # Content Widget for the Scroll Area
        self.content_widget = QWidget()
        self.content_widget.setLayout(self.h_layout)

        # Scroll Area
        self.scroll_area = NoVerticalScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setWidget(self.content_widget)

        # Main Layout
        main_layout = QVBoxLayout(self)
        self.label = QLabel(title)
        font = QFont()
        font.setBold(True)
        self.label.setFont(font)
        main_layout.addWidget(self.label)
        main_layout.addWidget(self.scroll_area)

        # Group Box Management
        self.group_boxes: List[ReceiveGroup] = []

    def _qmargins_to_tuple(self, margins: QMargins) -> tuple[int, int, int, int]:
        return margins.left(), margins.top(), margins.right(), margins.bottom()

    def resizeEvent(self, event: QResizeEvent) -> None:
        for group_box in self.group_boxes:
            group_box.setFixedHeight(
                self.height()
                - sum(self.h_layout.getContentsMargins())
                - sum(self._qmargins_to_tuple(self.scroll_area.contentsMargins()))
                - self.scroll_area.horizontalScrollBar().height()
            )

    def add_box(self, receive_group: ReceiveGroup):
        self.group_boxes.append(receive_group)
        self.h_layout.addWidget(receive_group)
        self.content_widget.adjustSize()

    def remove_box(self):
        if self.group_boxes:
            group_box = self.group_boxes.pop()
            self.h_layout.removeWidget(group_box)
            group_box.deleteLater()
            self.content_widget.adjustSize()

    def clear_boxes(self):
        while self.group_boxes:
            self.remove_box()
