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
from collections.abc import Callable
from functools import partial
from typing import cast

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DecodingException
from bitcoin_qr_tools.gui.bitcoin_video_widget import BitcoinVideoWidget
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QResizeEvent, QTextCharFormat
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.custom_edits import (
    AnalyzerLineEdit,
    AnalyzerState,
    AnalyzerTextEdit,
)
from bitcoin_safe.gui.qt.util import (
    Message,
    MessageType,
    clear_layout,
    do_copy,
    get_icon_path,
    svg_tools,
)
from bitcoin_safe.i18n import translate

logger = logging.getLogger(__name__)


class SquareButton(QToolButton):
    def __init__(self, qicon: QIcon, parent) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setIcon(qicon)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)


class ButtonsField(QWidget):
    def __init__(self, vertical_align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignBottom, parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)
        self.vertical_align = vertical_align
        self.buttons: list[QPushButton | QToolButton] = []

    def minimumSizeHint(self) -> QSize:
        # Initialize minimum width and height
        """MinimumSizeHint."""
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

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        """ResizeEvent."""
        super().resizeEvent(a0)
        self.rearrange_buttons()

    def rearrange_buttons(self) -> None:
        # Get the current size of the widget
        """Rearrange buttons."""
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

    def append_button(self, button: QPushButton | QToolButton):
        """Append button."""
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
        """Clear buttons."""
        clear_layout(self.grid_layout)
        self.buttons = []
        # No need to call rearrange_buttons here since the layout is already cleared

    def remove_button(self, button: QPushButton) -> None:
        """Remove button."""
        if button in self.buttons:
            self.buttons.remove(button)
            self._remove_widget_from_layout(button)
            # No need to call rearrange_buttons here since we only removed one widget


class ButtonEdit(QWidget):
    signal_data = cast(SignalProtocol[[Data]], pyqtSignal(Data))

    def __init__(
        self,
        close_all_video_widgets: SignalProtocol[[]],
        text="",
        button_vertical_align: Qt.AlignmentFlag | None = None,
        parent=None,
        input_field: AnalyzerTextEdit | AnalyzerLineEdit | None = None,
        signal_update: SignalProtocol[[]] | None = None,
        **kwargs,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.signal_tracker = SignalTracker()
        self.input_field: AnalyzerTextEdit | AnalyzerLineEdit = (
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

        self.button_camera: SquareButton | None = None
        self.copy_button: SquareButton | None = None
        self.pdf_button: SquareButton | None = None
        self.mnemonic_button: SquareButton | None = None
        self.open_file_button: SquareButton | None = None
        self._temp_bitcoin_video_widget: BitcoinVideoWidget | None = None
        self.close_all_video_widgets = close_all_video_widgets

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

        # signals
        if signal_update:
            signal_update.connect(self.updateUi)
        self.close_all_video_widgets.connect(self.close_video_widget)

        self.updateUi()

    def reset_formatting(self):
        """Reset formatting."""
        if isinstance(self.input_field, QTextEdit):
            self.input_field.setCurrentCharFormat(QTextCharFormat())

    def close_video_widget(self):
        """Close video widget."""
        if self._temp_bitcoin_video_widget:
            self._temp_bitcoin_video_widget.close()

    def updateUi(self) -> None:
        """UpdateUi."""
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

    def add_button(self, icon_path: str | None, button_callback: Callable, tooltip: str = "") -> SquareButton:
        """Add button."""
        button = SquareButton(svg_tools.get_QIcon(icon_path), parent=self)  # Create the button with the icon
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(button_callback)  # Connect the button's clicked signal to the callback
        button.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )  # Make button expand vertically
        self.button_container.append_button(button)
        return button

    def _on_copy(self) -> None:
        """On copy."""
        do_copy(self.text())

    def add_copy_button(
        self,
    ) -> SquareButton:
        """Add copy button."""
        self.copy_button = self.add_button(
            "bi--copy.svg", self._on_copy, tooltip=translate("d", "Copy to clipboard")
        )
        return self.copy_button

    def set_input_field(self, input_widget: AnalyzerTextEdit | AnalyzerLineEdit) -> None:
        # Remove the current input field from the layout and delete it
        """Set input field."""
        self.input_field.setParent(None)  # type: ignore[call-overload]

        # Set the new input field and add it to the layout
        self.input_field = input_widget
        self.main_layout.insertWidget(0, self.input_field)  # Insert at the beginning

    def setText(self, value: str | None) -> None:
        """SetText."""
        self.input_field.setText(value)

    def setPlainText(self, value: str | None) -> None:
        """SetPlainText."""
        self.input_field.setText(value)

    def setStyleSheet(self, styleSheet: str | None) -> None:
        """SetStyleSheet."""
        self.input_field.setStyleSheet(styleSheet)

    def text(self) -> str:
        """Text."""
        if isinstance(self.input_field, QTextEdit):
            return self.input_field.toPlainText()
        return self.input_field.text()

    def setPlaceholderText(self, value: str | None) -> None:
        """SetPlaceholderText."""
        self.input_field.setPlaceholderText(value)

    def setReadOnly(self, value: bool) -> None:
        """SetReadOnly."""
        self.input_field.setReadOnly(value)

    def _result_callback_input_qr_from_camera(self, data: Data) -> None:
        """Result callback input qr from camera."""
        if hasattr(self, "setText"):
            self.setText(str(data.data_as_string()))

    def input_qr_from_camera(
        self, network: bdk.Network, set_data_as_string=True, close_camera_on_result=True
    ) -> None:
        """Input qr from camera."""

        def _exception_callback(e: Exception) -> None:
            """Exception callback."""
            if isinstance(e, DecodingException):
                if question_dialog(
                    self.tr("Could not recognize the input. Do you want to scan again?"),
                    true_button=self.tr("Scan again"),
                ):
                    self.input_qr_from_camera(
                        network=network,
                        set_data_as_string=set_data_as_string,
                        close_camera_on_result=close_camera_on_result,
                    )
                else:
                    return
            else:
                Message(f"{type(e).__name__}\n{e}", type=MessageType.Error, parent=self)

        self.close_all_video_widgets.emit()
        self._temp_bitcoin_video_widget = BitcoinVideoWidget(
            network=network, close_on_result=close_camera_on_result
        )
        if set_data_as_string:
            self._temp_bitcoin_video_widget.signal_data.connect(self._result_callback_input_qr_from_camera)
        self._temp_bitcoin_video_widget.signal_data.connect(self.signal_data)
        self._temp_bitcoin_video_widget.signal_recognize_exception.connect(_exception_callback)
        self._temp_bitcoin_video_widget.show()

    def add_qr_input_from_camera_button(
        self, network: bdk.Network, set_data_as_string=False, close_camera_on_result=True
    ) -> SquareButton:
        """Add qr input from camera button."""
        self.button_camera = self.add_button(
            "bi--qr-code-scan.svg",
            partial(
                self.input_qr_from_camera,
                network=network,
                set_data_as_string=set_data_as_string,
                close_camera_on_result=close_camera_on_result,
            ),
            translate("d", "Read QR code from camera"),
        )

        return self.button_camera

    def add_pdf_buttton(
        self,
        on_click: Callable,
    ) -> SquareButton:
        """Add pdf buttton."""
        self.pdf_button = self.add_button(
            "bi--filetype-pdf.svg", on_click, tooltip=translate("d", "Create PDF")
        )
        return self.pdf_button

    def add_usb_buttton(
        self,
        on_click: Callable,
    ) -> SquareButton:
        """Add usb buttton."""
        self.pdf_button = self.add_button(
            "bi--usb-symbol.svg", on_click, tooltip=translate("d", "Connect to USB signer")
        )
        return self.pdf_button

    def _on_click_add_random_mnemonic_button(self, callback_seed: Callable | None = None) -> None:
        """On click add random mnemonic button."""
        seed = str(bdk.Mnemonic(bdk.WordCount.WORDS12))
        self.setText(seed)
        if callback_seed:
            callback_seed(seed)

    def add_random_mnemonic_button(
        self,
        callback_seed: Callable | None = None,
    ) -> SquareButton:
        """Add random mnemonic button."""
        self.mnemonic_button = self.add_button(
            get_icon_path("bi--dice-5.svg"),
            partial(self._on_click_add_random_mnemonic_button, callback_seed=callback_seed),
            tooltip=translate("d", "Create random mnemonic"),
        )
        return self.mnemonic_button

    def addResetButton(self, get_reset_text) -> SquareButton:
        """AddResetButton."""
        return self.add_button("bi--arrow-clockwise.svg", partial(self.setText, get_reset_text()), "Reset")

    def _on_click_add_open_file_button(
        self, callback_open_filepath: Callable | None = None, filter=None
    ) -> None:
        """On click add open file button."""
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
        if callback_open_filepath:
            callback_open_filepath(file_path)

    def add_open_file_button(
        self,
        callback_open_filepath: Callable | None = None,
        filter_str: str | None = None,
    ) -> QPushButton | QToolButton:
        """Add open file button."""
        filter_str = (
            filter_str
            if filter_str
            else translate("open_file", "All Files (*);;PSBT (*.psbt);;Transaction (*.tx)")
        )
        button = self.add_button(
            None,
            partial(
                self._on_click_add_open_file_button,
                callback_open_filepath=callback_open_filepath,
                filter=filter_str,
            ),
            translate("d", "Open file"),
        )
        icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        button.setIcon(icon)

        self.open_file_button = button
        return self.open_file_button

    def format_as_error(self, value: bool) -> None:
        """Format as error."""
        self.input_field.setObjectName(f"{id(self)}")

        if value:
            self.input_field.setStyleSheet(
                f"#{self.input_field.objectName()} {{ background-color: #ff6c54; }}"
            )
        else:
            self.input_field.setStyleSheet(f"#{self.input_field.objectName()} {{  }}")

    def format_and_apply_validator(self) -> None:
        """Format and apply validator."""
        analyzer = self.input_field.analyzer()
        if not analyzer:
            self.format_as_error(False)
            return

        self.input_field.normalize()
        analysis = analyzer.analyze(self.input_field.text(), self.input_field.cursorPosition())
        error = bool(self.input_field.text()) and (analysis.state != AnalyzerState.Valid)
        self.format_as_error(error)
        self.setToolTip(analysis.msg if error else "")

    def close(self) -> bool:
        """Close."""
        if self._temp_bitcoin_video_widget:
            self._temp_bitcoin_video_widget.close()
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setParent(None)
        return super().close()


# Example usage
if __name__ == "__main__":
    import sys

    class My(QObject):
        close_all_video_widgets = cast(SignalProtocol[[]], pyqtSignal())

    def example_callback() -> None:
        """Example callback."""
        print("Button clicked!")

    app = QApplication(sys.argv)
    my = My()
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    for _ in range(4):
        edit = ButtonEdit(
            button_vertical_align=Qt.AlignmentFlag.AlignVCenter,
            close_all_video_widgets=my.close_all_video_widgets,
        )
        # window.add_button("../icons/bi--copy.svg", example_callback)  # Add buttons as needed
        edit.add_copy_button()
        # Replace QLineEdit with QTextEdit or any other widget if required
        # window.set_input_field(QTextEdit())
        layout.addWidget(edit)

    text_edit = ButtonEdit(close_all_video_widgets=my.close_all_video_widgets)
    text_edit.add_copy_button()
    text_edit.add_qr_input_from_camera_button(bdk.Network.TESTNET4)
    text_edit.add_pdf_buttton(lambda: 0)
    text_edit.add_random_mnemonic_button(lambda: "some random")
    layout.addWidget(text_edit)

    widget.show()
    sys.exit(app.exec())
