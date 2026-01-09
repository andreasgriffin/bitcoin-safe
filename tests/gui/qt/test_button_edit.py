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
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QResizeEvent
from PyQt6.QtWidgets import QApplication, QPushButton, QToolButton, QWidget
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.buttonedit import (
    AnalyzerLineEdit,
    AnalyzerState,
    AnalyzerTextEdit,
    ButtonEdit,
    ButtonsField,
    SquareButton,
    get_icon_path,
)
from bitcoin_safe.gui.qt.custom_edits import AnalyzerMessage, BaseAnalyzer

logger = logging.getLogger(__name__)


class My(QObject):
    close_all_video_widgets = cast(SignalProtocol[[]], pyqtSignal())


@pytest.fixture()
def dummy_instance_with_close_all_video_widgets(qapp: QApplication) -> My:
    """Dummy instance with close all video widgets."""
    return My()


@pytest.fixture()
def button_edit(dummy_instance_with_close_all_video_widgets: My, qapp: QApplication) -> ButtonEdit:
    """Button edit."""
    return ButtonEdit(
        close_all_video_widgets=dummy_instance_with_close_all_video_widgets.close_all_video_widgets
    )


def test_square_button(qapp: QApplication):
    """Test square button."""
    icon = QIcon()
    parent = QWidget()
    button = SquareButton(icon, parent)
    assert isinstance(button, QToolButton)
    assert button.parent() == parent
    assert button.icon().cacheKey() == icon.cacheKey()


def test_buttons_field_initialization(qapp: QApplication):
    """Test buttons field initialization."""
    parent = QWidget()
    buttons_field = ButtonsField(Qt.AlignmentFlag.AlignBottom, parent)
    assert buttons_field.parent() == parent
    assert buttons_field.vertical_align == Qt.AlignmentFlag.AlignBottom
    assert buttons_field.buttons == []
    assert buttons_field.grid_layout is not None


def test_buttons_field_add_button(qapp: QApplication):
    """Test buttons field add button."""
    buttons_field = ButtonsField()
    button = QPushButton()
    buttons_field.append_button(button)
    assert button in buttons_field.buttons
    assert buttons_field.grid_layout.count() == 1


def test_buttons_field_remove_button(qapp: QApplication):
    """Test buttons field remove button."""
    buttons_field = ButtonsField()
    button = QPushButton()
    buttons_field.append_button(button)
    assert buttons_field.grid_layout.count() == 1
    buttons_field.remove_button(button)
    assert button not in buttons_field.buttons
    assert buttons_field.grid_layout.count() == 0  # Now this should be 0


def test_buttons_field_clear_buttons(qapp: QApplication):
    """Test buttons field clear buttons."""
    buttons_field = ButtonsField()
    button1 = QPushButton()
    button2 = QPushButton()
    buttons_field.append_button(button1)
    buttons_field.append_button(button2)
    buttons_field.clear_buttons()
    assert buttons_field.buttons == []
    assert buttons_field.grid_layout.count() == 0


def test_buttons_field_resize_event(qapp: QApplication):
    """Test buttons field resize event."""
    buttons_field = ButtonsField()
    for _ in range(10):
        button = QPushButton()
        buttons_field.append_button(button)
    # Simulate resize event
    event = QResizeEvent(QSize(200, 200), QSize(100, 100))
    buttons_field.resizeEvent(event)
    # Check that rearrange_buttons was called (we can mock rearrange_buttons)
    with patch.object(buttons_field, "rearrange_buttons") as mock_rearrange:
        buttons_field.resizeEvent(event)
        mock_rearrange.assert_called_once()


def test_button_edit_initialization(button_edit: ButtonEdit):
    """Test button edit initialization."""
    assert isinstance(button_edit.input_field, AnalyzerLineEdit)
    assert button_edit.button_container is not None
    assert button_edit.main_layout is not None


def test_button_edit_set_text(button_edit: ButtonEdit):
    """Test button edit set text."""
    button_edit.setText("Test Text")
    assert button_edit.input_field.text() == "Test Text"


def test_button_edit_get_text(button_edit: ButtonEdit):
    """Test button edit get text."""
    button_edit.setText("Test Text")
    assert button_edit.text() == "Test Text"
    assert button_edit.input_field.text() == "Test Text"


def test_button_edit_set_input_field(button_edit: ButtonEdit):
    """Test button edit set input field."""
    new_input_field = AnalyzerTextEdit()
    button_edit.set_input_field(new_input_field)
    assert button_edit.input_field == new_input_field
    assert button_edit.main_layout.itemAt(0).widget() == new_input_field


def test_button_edit_format_as_error(button_edit: ButtonEdit):
    """Test button edit format as error."""
    button_edit.format_as_error(True)
    assert "background-color" in button_edit.input_field.styleSheet()
    button_edit.format_as_error(False)
    assert "background-color" not in button_edit.input_field.styleSheet()


def test_button_edit_format_and_apply_validator_valid(button_edit: ButtonEdit):
    """Test button edit format and apply validator valid."""
    button_edit.input_field.setText("Valid Input")
    analyzer = BaseAnalyzer()
    with patch.object(BaseAnalyzer, "analyze", return_value=AnalyzerMessage("", AnalyzerState.Valid)):
        button_edit.input_field.setAnalyzer(analyzer)
        button_edit.format_and_apply_validator()
        assert "background-color" not in button_edit.input_field.styleSheet()


def test_button_edit_format_and_apply_validator_invalid(button_edit: ButtonEdit):
    """Test button edit format and apply validator invalid."""
    button_edit.input_field.setText("Invalid Input")
    invalid_result = AnalyzerMessage("Error message", AnalyzerState.Invalid)
    analyzer = BaseAnalyzer()
    with patch.object(BaseAnalyzer, "analyze", return_value=invalid_result):
        button_edit.input_field.setAnalyzer(analyzer)
        button_edit.format_and_apply_validator()
        assert "background-color" in button_edit.input_field.styleSheet()
        assert button_edit.toolTip() == "Error message"


def test_button_edit_add_pdf_button(button_edit: ButtonEdit, qtbot: QtBot):
    """Test button edit add pdf button."""
    qtbot.addWidget(button_edit)  # Register the widget with qtbot
    callback = MagicMock()
    button_edit.add_pdf_buttton(callback)
    assert button_edit.pdf_button is not None
    # Simulate button click
    qtbot.mouseClick(button_edit.pdf_button, Qt.MouseButton.LeftButton)
    callback.assert_called_once()


def test_button_edit_add_open_file_button(button_edit: ButtonEdit, qtbot: QtBot):
    """Test button edit add open file button."""
    callback = MagicMock()
    with patch("PyQt6.QtWidgets.QFileDialog.getOpenFileName", return_value=("file_path", "")):
        button_edit.add_open_file_button(callback)
        assert button_edit.open_file_button is not None
        # Simulate button click
        qtbot.mouseClick(button_edit.open_file_button, Qt.MouseButton.LeftButton)
        callback.assert_called_once_with("file_path")


def test_button_edit_set_placeholder_text(button_edit: ButtonEdit):
    """Test button edit set placeholder text."""
    button_edit.setPlaceholderText("Enter text...")
    assert button_edit.input_field.placeholderText() == "Enter text..."


def test_button_edit_set_read_only(button_edit: ButtonEdit):
    """Test button edit set read only."""
    button_edit.setReadOnly(True)
    assert button_edit.input_field.isReadOnly()
    button_edit.setReadOnly(False)
    assert not button_edit.input_field.isReadOnly()


def test_button_edit_update_ui(button_edit: ButtonEdit):
    """Test button edit update ui."""
    button_edit.add_copy_button()
    button_edit.add_pdf_buttton(lambda: None)
    button_edit.updateUi()
    assert button_edit.copy_button.toolTip() == "Copy to clipboard"
    assert button_edit.pdf_button.toolTip() == "Create PDF"


def test_button_edit_add_button(button_edit: ButtonEdit):
    """Test button edit add button."""
    callback = MagicMock()
    button = button_edit.add_button(get_icon_path("icon.png"), callback, "Tooltip text")
    assert button in button_edit.button_container.buttons
    assert button.toolTip() == "Tooltip text"
    # Simulate button click
    button.click()
    callback.assert_called_once()


def test_button_edit_set_plain_text(button_edit: ButtonEdit):
    """Test button edit set plain text."""
    button_edit.setPlainText("Plain Text")
    assert button_edit.input_field.text() == "Plain Text"


def test_button_edit_set_style_sheet(button_edit: ButtonEdit):
    """Test button edit set style sheet."""
    button_edit.setStyleSheet("background-color: red;")
    assert button_edit.input_field.styleSheet() == "background-color: red;"


def test_buttons_field_rearrange_buttons(button_edit: ButtonEdit):
    """Test buttons field rearrange buttons."""
    buttons_field = ButtonsField()
    for i in range(5):
        button = QPushButton(f"Button {i}")
        buttons_field.append_button(button)
    # Simulate resize event
    event = QResizeEvent(QSize(100, 500), QSize(100, 100))
    buttons_field.resizeEvent(event)
    # Check that buttons are arranged correctly
    # Since the rearrangement logic can be complex, we can check the number of items in the grid layout
    assert buttons_field.grid_layout.count() == 5


def test_square_button_click(button_edit: ButtonEdit, qtbot: QtBot):
    """Test square button click."""
    icon = QIcon()
    parent = QWidget()
    button = SquareButton(icon, parent)
    callback = MagicMock()
    button.clicked.connect(callback)
    # Simulate button click
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    callback.assert_called_once()


def test_button_edit_set_input_field_text_edit(button_edit: ButtonEdit):
    """Test button edit set input field text edit."""
    text_edit = AnalyzerTextEdit()
    button_edit.set_input_field(text_edit)
    assert isinstance(button_edit.input_field, AnalyzerTextEdit)
    button_edit.setText("Sample Text")
    assert button_edit.input_field.toPlainText() == "Sample Text"
    assert button_edit.text() == "Sample Text"


def test_button_edit_method_delegation(button_edit: ButtonEdit):
    # Set placeholder text
    """Test button edit method delegation."""
    button_edit.setPlaceholderText("Placeholder")
    assert button_edit.input_field.placeholderText() == "Placeholder"
    # Set read-only
    button_edit.setReadOnly(True)
    assert button_edit.input_field.isReadOnly()


def test_button_edit_format_and_apply_validator_no_analyzer(button_edit: ButtonEdit):
    """Test button edit format and apply validator no analyzer."""
    with patch.object(button_edit.input_field, "analyzer", return_value=None):
        button_edit.format_and_apply_validator()
        assert "background-color" not in button_edit.input_field.styleSheet()


def test_button_edit_add_reset_button(button_edit: ButtonEdit, qtbot: QtBot):
    """Test button edit add reset button."""
    get_reset_text = MagicMock(return_value="Reset Text")
    reset_button = button_edit.addResetButton(get_reset_text)
    assert reset_button in button_edit.button_container.buttons
    # Simulate button click
    qtbot.mouseClick(reset_button, Qt.MouseButton.LeftButton)
    get_reset_text.assert_called_once()
    assert button_edit.text() == "Reset Text"
