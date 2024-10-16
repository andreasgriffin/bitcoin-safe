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
from typing import Callable, List, Optional, Union

from bdkpython import bdk
from bitcoin_qr_tools.bitcoin_video_widget import BitcoinVideoWidget
from bitcoin_qr_tools.data import Data, DecodingException
from PyQt6.QtCore import QSize, Qt, pyqtBoundSignal, pyqtSignal
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
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.custom_edits import (
    AnalyzerLineEdit,
    AnalyzerState,
    AnalyzerTextEdit,
)
from bitcoin_safe.gui.qt.util import Message, clear_layout, do_copy, icon_path
from bitcoin_safe.i18n import translate

logger = logging.getLogger(__name__)


class SquareButton(QPushButton):
    def __init__(self, qicon: QIcon, parent) -> None:
        super().__init__(qicon, "", parent)
        self.setMaximumSize(24, 24)


class ButtonsField(QWidget):
    def __init__(self, vertical_align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignBottom, parent=None) -> None:
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)
        self.vertical_align = vertical_align
        self.buttons: List[QPushButton] = []

    def minimumSizeHint(self) -> QSize:
        # Initialize minimum width and height
        width = 0
        height = 0

        # Find all buttons and calculate their total minimum width and height
        for button in self.findChildren(QWidget):
            width = max(width, button.sizeHint().width())
            height = max(height, button.sizeHint().height())

        if self.grid_layout.count() > 0:
            return QSize(width, height)

        # If there are no buttons, fall back to the default minimum size hint
        return super().minimumSizeHint()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.rearrange_buttons()

    def rearrange_buttons(self) -> None:
        # Get the current size of the widget
        current_height = self.size().height()

        if not self.buttons:
            return

        # Get the size hint of the first button
        first_button = self.buttons[0]
        button_size = first_button.sizeHint().height()  # Assuming square buttons
        padding = 0  # Assume some padding between buttons

        # Calculate how many buttons can fit vertically
        buttons_per_column = max(1, current_height // (button_size + padding))

        # Calculate the required number of rows and columns
        num_buttons = len(self.buttons)
        num_columns = (num_buttons + buttons_per_column - 1) // buttons_per_column
        num_rows = (num_buttons + num_columns - 1) // num_columns

        # Determine if buttons are stacked vertically (more rows than 1)
        vertical_stack = num_columns > 1

        # Clear any existing stretch factors and alignments
        for i in range(self.grid_layout.rowCount()):
            self.grid_layout.setRowStretch(i, 0)

        # Add buttons back to the layout in the new arrangement
        for i, button in enumerate(self.buttons):
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

    def append_button(self, button: QPushButton):
        self.buttons.append(button)
        self.rearrange_buttons()

    def _remove_widget_from_layout(self, widget: QWidget) -> None:
        """Helper method to remove a specific widget from the grid layout."""
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if not item:
                continue
            if item.widget() == widget:
                self.grid_layout.takeAt(i)
                self.grid_layout.removeWidget(widget)
                widget.setParent(None)
                break

    def clear_buttons(self) -> None:
        clear_layout(self.grid_layout)
        self.buttons = []
        # No need to call rearrange_buttons here since the layout is already cleared

    def remove_button(self, button: QPushButton) -> None:
        if button in self.buttons:
            self.buttons.remove(button)
            self._remove_widget_from_layout(button)
            # No need to call rearrange_buttons here since we only removed one widget


class ButtonEdit(QWidget):
    signal_data = pyqtSignal(Data)

    def __init__(
        self,
        text="",
        button_vertical_align: Optional[Qt.AlignmentFlag] = None,
        parent=None,
        input_field: Union[AnalyzerTextEdit, AnalyzerLineEdit] | None = None,
        signal_update: pyqtBoundSignal | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent=parent)
        self.input_field: Union[AnalyzerTextEdit, AnalyzerLineEdit] = (
            input_field if input_field else AnalyzerLineEdit(parent=self)
        )
        if text:
            self.input_field.setText(text)
        self.button_container = ButtonsField(
            vertical_align=(
                button_vertical_align
                if button_vertical_align
                else (
                    Qt.AlignmentFlag.AlignVCenter
                    if isinstance(self.input_field, QLineEdit)
                    else Qt.AlignmentFlag.AlignBottom
                )
            )
        )  # Container for buttons to allow dynamic layout changes

        self.button_camera: Optional[SquareButton] = None
        self.copy_button: Optional[SquareButton] = None
        self.pdf_button: Optional[SquareButton] = None
        self.mnemonic_button: Optional[SquareButton] = None
        self.open_file_button: Optional[SquareButton] = None
        self._temp_bitcoin_video_widget: BitcoinVideoWidget | None = None

        self.main_layout = QHBoxLayout(
            self
        )  # Horizontal layout to place the input field and buttons side by side
        self.input_field.textChanged.connect(self.format_and_apply_validator)

        # Add the input field and buttons layout to the main layout
        self.main_layout.addWidget(self.input_field)
        self.main_layout.addWidget(self.button_container)

        # Ensure there's no spacing that could affect the alignment
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        if signal_update:
            signal_update.connect(self.updateUi)
        self.updateUi()

    def updateUi(self) -> None:
        if self.button_camera:
            self.button_camera.setToolTip(translate("d", "Import from camera"))
        if self.copy_button:
            self.copy_button.setToolTip(translate("d", "Copy to clipboard"))
        if self.pdf_button:
            self.pdf_button.setToolTip(translate("d", "Create PDF"))
        if self.mnemonic_button:
            self.mnemonic_button.setToolTip(translate("d", "Create random mnemonic"))
        if self.open_file_button:
            self.open_file_button.setToolTip(translate("d", "Open file"))

    def add_button(
        self, icon_path: Optional[str], button_callback: Callable, tooltip: str = ""
    ) -> SquareButton:
        button = SquareButton(QIcon(icon_path), parent=self)  # Create the button with the icon
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(button_callback)  # Connect the button's clicked signal to the callback
        button.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )  # Make button expand vertically
        self.button_container.append_button(button)
        return button

    def add_copy_button(
        self,
    ) -> SquareButton:
        def on_copy() -> None:
            do_copy(self.text())

        self.copy_button = self.add_button(
            icon_path("copy.png"), on_copy, tooltip=translate("d", "Copy to clipboard")
        )
        return self.copy_button

    def set_input_field(self, input_widget: Union[AnalyzerTextEdit, AnalyzerLineEdit]) -> None:
        # Remove the current input field from the layout and delete it
        self.input_field.setParent(None)  # type: ignore[call-overload]
        self.input_field.deleteLater()

        # Set the new input field and add it to the layout
        self.input_field = input_widget
        self.main_layout.insertWidget(0, self.input_field)  # Insert at the beginning

    def setText(self, value: str | None) -> None:
        self.input_field.setText(value)

    def setPlainText(self, value: str | None) -> None:
        self.input_field.setText(value)

    def setStyleSheet(self, value: str | None) -> None:
        self.input_field.setStyleSheet(value)

    def text(self) -> str:
        if hasattr(self.input_field, "toPlainText"):
            return getattr(self.input_field, "toPlainText")()
        return self.input_field.text()

    def setPlaceholderText(self, value: str | None) -> None:
        self.input_field.setPlaceholderText(value)

    def setReadOnly(self, value: bool) -> None:
        self.input_field.setReadOnly(value)

    def add_qr_input_from_camera_button(self, network: bdk.Network, set_data_as_string=False) -> SquareButton:

        def input_qr_from_camera() -> None:
            def exception_callback(e: Exception) -> None:
                if isinstance(e, DecodingException):
                    Message("Could not recognize the input.")
                else:
                    Message(str(e))

            def result_callback(data: Data) -> None:
                if set_data_as_string and hasattr(self, "setText"):
                    self.setText(str(data.data_as_string()))

            if self._temp_bitcoin_video_widget:
                self._temp_bitcoin_video_widget.close()
            self._temp_bitcoin_video_widget = BitcoinVideoWidget(
                network=network,
            )
            self._temp_bitcoin_video_widget.signal_data.connect(result_callback)
            self._temp_bitcoin_video_widget.signal_data.connect(self.signal_data)
            self._temp_bitcoin_video_widget.signal_recognize_exception.connect(exception_callback)
            self._temp_bitcoin_video_widget.show()

        self.button_camera = self.add_button(
            icon_path("camera.svg"), input_qr_from_camera, translate("d", "Read QR code from camera")
        )

        # side-effect: we export these methods:
        self.on_qr_from_camera_input_btn = input_qr_from_camera

        return self.button_camera

    def add_pdf_buttton(
        self,
        on_click: Callable,
    ) -> SquareButton:

        self.pdf_button = self.add_button(
            icon_path("pdf-file.svg"), on_click, tooltip=translate("d", "Create PDF")
        )
        return self.pdf_button

    def add_random_mnemonic_button(
        self,
        callback_seed=None,
    ) -> SquareButton:
        def on_click() -> None:
            seed = bdk.Mnemonic(bdk.WordCount.WORDS12).as_string()
            self.setText(seed)
            if callback_seed:
                callback_seed(seed)

        self.mnemonic_button = self.add_button(
            icon_path("dice.svg"), on_click, tooltip=translate("d", "Create random mnemonic")
        )
        return self.mnemonic_button

    def addResetButton(self, get_reset_text) -> SquareButton:
        def on_click() -> None:
            self.setText(get_reset_text())

        return self.add_button("reset-update.svg", on_click, "Reset")
        # button.setStyleSheet("background-color: white;")

    def add_open_file_button(
        self,
        callback_open_filepath,
        filter=translate("open_file", "All Files (*);;PSBT (*.psbt);;Transation (*.tx)"),
    ) -> QPushButton:
        def on_click() -> None:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                translate("open_file", "Open Transaction/PSBT"),
                "",
                filter,
            )
            if not file_path:
                logger.debug("No file selected")
                return

            logger.info(f"Selected file: {file_path}")
            callback_open_filepath(file_path)

        button = self.add_button(None, on_click, translate("d", "Open file"))
        icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        button.setIcon(icon)

        self.open_file_button = button
        return self.open_file_button

    def format_as_error(self, value: bool) -> None:
        if value:
            self.input_field.setStyleSheet(
                f"{self.input_field.__class__.__name__}" + " { background-color: #ff6c54; }"
            )
        else:
            self.input_field.setStyleSheet("")

    def format_and_apply_validator(self) -> None:
        analyzer = self.input_field.analyzer()
        if not analyzer:
            self.format_as_error(False)
            return

        analysis = analyzer.analyze(self.input_field.text(), self.input_field.cursorPosition())
        error = bool(self.input_field.text()) and (analysis.state != AnalyzerState.Valid)
        self.format_as_error(error)
        self.setToolTip(analysis.msg if error else "")


# Example usage
if __name__ == "__main__":
    import sys

    def example_callback() -> None:
        print("Button clicked!")

    app = QApplication(sys.argv)
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    for i in range(4):
        edit = ButtonEdit(button_vertical_align=Qt.AlignmentFlag.AlignVCenter)
        # window.add_button("../icons/copy.png", example_callback)  # Add buttons as needed
        edit.add_copy_button()
        # Replace QLineEdit with QTextEdit or any other widget if required
        # window.set_input_field(QTextEdit())
        layout.addWidget(edit)

    text_edit = ButtonEdit()
    text_edit.add_copy_button()
    text_edit.add_qr_input_from_camera_button(bdk.Network.TESTNET)
    text_edit.add_pdf_buttton(lambda: 0)
    text_edit.add_random_mnemonic_button(lambda: "some random")
    layout.addWidget(text_edit)

    widget.show()
    sys.exit(app.exec())
