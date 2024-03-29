import logging
from typing import Callable, List, Optional, Union

from bdkpython import bdk
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTextEdit,
    QWidget,
)

from .util import do_copy, icon_path

logger = logging.getLogger(__name__)


class SquareButton(QPushButton):
    def __init__(self, qicon: QIcon, parent) -> None:
        super().__init__(qicon, "", parent)
        self.setMaximumSize(24, 24)


class ButtonsField(QWidget):
    def __init__(self, vertical_align: Qt = Qt.AlignmentFlag.AlignBottom, parent=None):
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)
        self.vertical_align = vertical_align

    def minimumSizeHint(self):
        # Initialize minimum width and height
        width = 0
        height = 0

        # Iterate over all buttons to calculate the total minimum width
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            button = item.widget()
            if button:
                width = max(width, button.sizeHint().width())
                height = max(height, button.sizeHint().height())

        # If we have buttons, return the total width as minimum width, and the height of the first button as minimum height
        if self.grid_layout.count() > 0:
            return QSize(width, height)

        # If there are no buttons, fall back to the default minimum size hint
        return super().minimumSizeHint()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.rearrange_buttons()

    def rearrange_buttons(self):
        # Get the current size of the widget
        current_height = self.size().height()

        # Get the size hint of the first button
        first_button = self.grid_layout.itemAt(0).widget()
        button_size = first_button.sizeHint().height()  # Assuming square buttons
        padding = 0  # Assume some padding between buttons

        # Calculate how many buttons can fit vertically
        buttons_per_column = max(1, current_height // (button_size + padding))

        # Remove all buttons from the layout and store them in a list
        buttons = []
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.takeAt(i).widget()
            buttons.append(widget)

        # Calculate the required number of rows and columns
        num_buttons = len(buttons)
        num_columns = (num_buttons + buttons_per_column - 1) // buttons_per_column
        num_rows = (num_buttons + num_columns - 1) // num_columns

        # Determine if buttons are stacked vertically (more rows than 1)
        vertical_stack = num_columns > 1

        # Clear any existing stretch factors and alignments
        for i in range(self.grid_layout.rowCount()):
            self.grid_layout.setRowStretch(i, 0)

        # Add buttons back to the layout in the new arrangement
        for i, button in enumerate(buttons):
            row = i // num_columns
            col = i % num_columns
            self.grid_layout.addWidget(button, row + 1, col)

            # # If buttons are vertically stacked, align them to the bottom, otherwise center them
            if vertical_stack:
                self.grid_layout.setAlignment(button, Qt.AlignmentFlag.AlignBottom)
            else:
                self.grid_layout.setAlignment(button, Qt.AlignmentFlag.AlignVCenter)

        if self.vertical_align in [Qt.AlignmentFlag.AlignVCenter, Qt.AlignmentFlag.AlignCenter]:
            self.grid_layout.setRowStretch(0, 1)
            self.grid_layout.setRowStretch(num_rows + 1, 1)
        if self.vertical_align == Qt.AlignmentFlag.AlignBottom:
            self.grid_layout.setRowStretch(0, 1)
        if self.vertical_align == Qt.AlignmentFlag.AlignTop:
            self.grid_layout.setRowStretch(num_rows + 1, 1)


class ButtonEdit(QWidget):
    def __init__(self, text="", button_vertical_align: Optional[Qt] = None, parent=None, input_field=None):
        super().__init__(parent=parent)
        self.callback_is_valid: Optional[Callable[[], bool]] = None
        self.buttons: List[QPushButton] = []  # Store button references
        self.input_field: Union[QTextEdit, QLineEdit] = input_field if input_field else QLineEdit(self)
        if text:
            self.input_field.setText(text)
        self.button_container = ButtonsField(
            vertical_align=button_vertical_align
            if button_vertical_align
            else (
                Qt.AlignmentFlag.AlignVCenter
                if isinstance(self.input_field, QLineEdit)
                else Qt.AlignmentFlag.AlignBottom
            )
        )  # Container for buttons to allow dynamic layout changes

        self.main_layout = QHBoxLayout(
            self
        )  # Horizontal layout to place the input field and buttons side by side
        self.input_field.textChanged.connect(self.format)

        # Add the input field and buttons layout to the main layout
        self.main_layout.addWidget(self.input_field)
        self.main_layout.addWidget(self.button_container)

        # Ensure there's no spacing that could affect the alignment
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

    def add_button(self, button_path: Optional[str], button_callback: Callable, tooltip: str = ""):
        button = SquareButton(QIcon(button_path), parent=self)  # Create the button with the icon
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(button_callback)  # Connect the button's clicked signal to the callback
        button.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )  # Make button expand vertically
        self.buttons.append(button)
        self.button_container.layout().addWidget(button)
        return button

    def add_copy_button(self):
        def on_copy():
            do_copy(self.text())

        self.add_button(icon_path("copy.png"), on_copy, tooltip="Copy to clipboard")

    def set_input_field(self, input_widget: QWidget):
        # Remove the current input field from the layout and delete it
        self.main_layout.removeWidget(self.input_field)
        self.input_field.deleteLater()

        # Set the new input field and add it to the layout
        self.input_field = input_widget
        self.main_layout.insertWidget(0, self.input_field)  # Insert at the beginning

    def setText(self, value: str):
        self.input_field.setText(value)

    def setPlainText(self, value: str):
        self.input_field.setText(value)

    def setStyleSheet(self, value: str):
        self.input_field.setStyleSheet(value)

    def text(self):
        if hasattr(self.input_field, "toPlainText"):
            return getattr(self.input_field, "toPlainText")()
        return self.input_field.text()

    def setPlaceholderText(self, value: str):
        self.input_field.setPlaceholderText(value)

    def setReadOnly(self, value: bool):
        self.input_field.setReadOnly(value)

    def add_qr_input_from_camera_button(
        self,
        *,
        custom_handle_input=None,
    ):
        def input_qr_from_camera():
            from bitcoin_qrreader import bitcoin_qr, bitcoin_qr_gui

            def result_callback(data: bitcoin_qr.Data):
                if custom_handle_input:
                    custom_handle_input(data, self)
                else:
                    if hasattr(self, "setText"):
                        self.setText(str(data.data_as_string()))

            window = bitcoin_qr_gui.BitcoinVideoWidget(result_callback=result_callback)
            window.show()

        button = self.add_button(icon_path("camera.svg"), input_qr_from_camera, "Read QR code from camera")
        # side-effect: we export these methods:
        self.on_qr_from_camera_input_btn = input_qr_from_camera

        return button

    def add_pdf_buttton(self, on_click: Callable):
        button = self.add_button(icon_path("pdf-file.svg"), on_click, tooltip="Create PDF")

    def add_random_mnemonic_button(self, callback_seed=None):
        def on_click():
            seed = bdk.Mnemonic(bdk.WordCount.WORDS12).as_string()
            self.setText(seed)
            if callback_seed:
                callback_seed(seed)

        self.add_button(icon_path("dice.svg"), on_click, tooltip="Create random mnemonic")

    def addResetButton(self, get_reset_text):
        def on_click():
            self.setText(get_reset_text())

        self.add_button("reset-update.svg", on_click, "Reset")
        # button.setStyleSheet("background-color: white;")

    def add_open_file_button(
        self, callback_open_filepath, filter="All Files (*);;PSBT (*.psbt);;Transation (*.tx)"
    ) -> QPushButton:
        def on_click():
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Transaction/PSBT",
                "",
                filter,
            )
            if not file_path:
                logger.debug("No file selected")
                return

            logger.debug(f"Selected file: {file_path}")
            callback_open_filepath(file_path)

        button = self.add_button(None, on_click, "Open file")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        button.setIcon(icon)
        return button

    def format_as_error(self, value: bool):
        if value:
            self.input_field.setStyleSheet(
                f"{self.input_field.__class__.__name__}" + " { background-color: #ff6c54; }"
            )
        else:
            self.input_field.setStyleSheet("")

    def format(self):
        if not self.callback_is_valid:
            return self.format_as_error(False)
        self.format_as_error(not self.callback_is_valid())

    def set_validator(self, callback_is_valid: Callable[[], bool]):
        self.callback_is_valid = callback_is_valid


# Example usage
if __name__ == "__main__":
    import sys

    def example_callback():
        print("Button clicked!")

    app = QApplication(sys.argv)
    window = ButtonEdit(button_vertical_align=Qt.AlignmentFlag.AlignVCenter)
    # window.add_button("../icons/copy.png", example_callback)  # Add buttons as needed
    window.add_copy_button()
    # Replace QLineEdit with QTextEdit or any other widget if required
    # window.set_input_field(QTextEdit())
    window.show()
    sys.exit(app.exec())
