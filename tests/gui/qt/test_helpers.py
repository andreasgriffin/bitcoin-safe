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


import inspect
import logging
import os
import platform
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, Callable, Generator, List, Optional, Type, TypeVar, Union
from unittest.mock import patch

import pytest
from PyQt6 import QtCore
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QWidget,
)
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.dialogs import PasswordCreation
from bitcoin_safe.gui.qt.main import MainWindow

logger = logging.getLogger(__name__)


def get_current_test_name() -> Optional[str]:
    """
    Traverse the call stack and return the name of the current test function.
    """
    stack = inspect.stack()
    for frame_info in stack:
        function_name = frame_info.function
        if function_name.startswith("test_"):
            return function_name
    return None


@pytest.fixture(scope="session")
def test_start_time() -> datetime:
    """Fixture to capture the start time of the test session."""
    return datetime.now()


@contextmanager
def main_window_context(test_config: UserConfig) -> Generator[MainWindow, None, None]:
    """Context manager that manages the MainWindow lifecycle."""
    window = MainWindow(config=test_config)
    window.show()
    try:
        yield window
    finally:
        window.close()


# Define a Type Variable
T = TypeVar("T", bound=QWidget)  # This constrains T to be a subclass of QWidget


class Shutter:
    def __init__(self, qtbot: QtBot, name: str) -> None:
        self.qtbot = qtbot
        self.name = name

    def save(self, widget: QWidget, delay: float = 0.2) -> None:
        QApplication.processEvents()
        sleep(delay)
        self.save_screenshot(widget, self.qtbot, self.name)

    @staticmethod
    def directory(name: str) -> Path:
        """Saves a screenshot of the given main window using qtbot to the 'screenshots' directory with a timestamp."""
        # Ensure the 'screenshots' directory exists
        screenshots_dir = Path("tests") / "output" / f"screenshots_{name}"
        screenshots_dir.mkdir(exist_ok=True, parents=True)
        return screenshots_dir

    @staticmethod
    def save_screenshot(widget: QMainWindow, qtbot: QtBot, name: str) -> Path:
        """Saves a screenshot of the given main window using qtbot to the 'screenshots' directory with a timestamp."""
        # Ensure the 'screenshots' directory exists
        screenshots_dir = Shutter.directory(name)

        # Take a screenshot using qtbot, which returns the path to the temporary saved file
        temp_filepath: Path = qtbot.screenshot(widget)
        final_filepath = (
            screenshots_dir / f"{datetime.now().timestamp()}_{get_current_test_name()}_{temp_filepath.name}"
        )

        # Copy the screenshot from the temporary location to the desired directory
        shutil.move(str(temp_filepath), str(final_filepath))

        return final_filepath

    def create_symlink(self, test_config: UserConfig) -> None:
        screenshots_dir = Shutter.directory(self.name)
        link_name = screenshots_dir / "config_dir"

        if platform.system() == "Windows":
            # Use mklink to create a directory junction on Windows
            if os.system(f'mklink /J "{link_name}" "{test_config.config_dir}"') != 0:
                raise OSError(
                    f"Failed to create directory junction from {link_name} to {test_config.config_dir}"
                )
        else:
            link_name.symlink_to(test_config.config_dir)


def _get_widget_top_level(cls: Type[T], title: str | None = None) -> Optional[T]:
    """
    Find the top-level widget of the specified class and title among the active widgets.

    Args:
    cls (QWidget): The class type to look for.
    title (str): The window title to match. Optional.

    Returns:
    QWidget or False: The widget if found, otherwise False.
    """
    for widget in QApplication.topLevelWidgets():
        logger.debug(str(widget))
        # Check instance and, if a title is provided, whether the title matches
        if (
            isinstance(widget, cls)
            and (title is None or widget.windowTitle() == title)
            and widget.isVisible()
        ):
            print(f'Widget {widget} of class {cls} with title "{widget.windowTitle()}" is open.')
            return widget

    print(f'No open widget found of class {cls} with title "{title}".')
    return None


def get_widget_top_level(
    cls: Type[T], qtbot: QtBot, title: str | None = None, wait: bool = True, timeout: int = 10000
) -> Optional[T]:
    """
    Find the top-level widget of the specified class and title among the active widgets.

    Args:
    cls (QWidget): The class type to look for.
    title (str): The window title to match. Optional.

    Returns:
    QWidget or False: The widget if found, otherwise False.
    """
    QApplication.processEvents()
    qtbot.waitUntil(lambda: bool(_get_widget_top_level(cls=cls)), timeout=timeout)
    return _get_widget_top_level(cls=cls)


def do_modal_click(
    click_pushbutton: Union[Callable, QWidget],
    on_open: Callable[[T], None],
    qtbot: QtBot,
    button: QtCore.Qt.MouseButton = QtCore.Qt.MouseButton.LeftButton,
    cls: Type[T] = QMessageBox,
    timeout=5000,
    timer_delay=200,
) -> None:
    def click() -> None:
        print("\nwaiting for is_dialog_open")

        dialog = get_widget_top_level(cls=cls, qtbot=qtbot, timeout=timeout)
        assert dialog

        print("is_dialog_open = True")
        print("Do on_open")
        on_open(dialog)

    QtCore.QTimer.singleShot(timer_delay, click)
    if callable(click_pushbutton):
        click_pushbutton()
    else:
        qtbot.mouseClick(click_pushbutton, button)


def get_called_args_message_box(
    patch_str: str,
    click_pushbutton: QPushButton,
    repeat_clicking_until_message_box_called=False,
) -> List[Any]:
    with patch(patch_str) as mock_message:
        while not mock_message.called:
            click_pushbutton.click()
            QApplication.processEvents()
            sleep(0.2)
            if not repeat_clicking_until_message_box_called:
                break

        called_args, called_kwargs = mock_message.call_args
        return called_args


def simulate_user_response(
    main_window: QMainWindow, qtbot: QtBot, button_type: QMessageBox.StandardButton
) -> Optional[bool]:
    # You have to find the dialog window among the active widgets
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QMessageBox):
            # Simulate clicking 'Yes'
            print("do click")
            qtbot.mouseClick(widget.button(button_type), QtCore.Qt.MouseButton.LeftButton)
            return True
    return None


def type_text_in_edit(text: str, edit: Union[QLineEdit, QTextEdit]) -> None:
    """
    Simulate typing text into a QLineEdit or QTextEdit widget.

    :param text: The text to type into the edit widget.
    :param edit: The QLineEdit or QTextEdit widget where the text will be typed.
    """
    edit.setFocus()
    QApplication.processEvents()

    # Ensure the widget has focus
    if not edit.hasFocus():
        edit.setFocus()
        QApplication.processEvents()

    # Simulate typing each character
    for char in text:
        QTest.keyClick(edit, char)
        QApplication.processEvents()


def get_tab_with_title(tabs: QTabWidget, title: str) -> Optional[QWidget]:
    """
    Returns the tab with the specified title from a QTabWidget.

    :param tabs: The QTabWidget instance containing the tabs.
    :param title: The title of the tab to find.
    :return: The QWidget of the tab with the specified title, or None if not found.
    """
    for index in range(tabs.count()):
        if tabs.tabText(index).lower() == title.lower():
            return tabs.widget(index)
    return None


def save_wallet(
    shutter: Shutter, test_config: UserConfig, wallet_name: str, qtbot: QtBot, save_button: QPushButton
) -> None:

    # check that you cannot go further without import xpub
    def password_creation(dialog: PasswordCreation) -> None:
        shutter.save(dialog)
        dialog.submit_button.click()

    wallet_file = Path(test_config.config_dir) / f"{wallet_name}.wallet"
    with patch.object(
        QFileDialog, "getSaveFileName", return_value=(str(wallet_file), "All Files (*)")
    ) as mock_open:
        do_modal_click(save_button, password_creation, qtbot, cls=PasswordCreation)
        mock_open.assert_called_once()


def close_wallet(
    shutter: Shutter, test_config: UserConfig, wallet_name: str, qtbot: QtBot, main_window: MainWindow
) -> None:

    # check that you cannot go further without import xpub
    def password_creation(dialog: QMessageBox) -> None:
        shutter.save(dialog)
        dialog.button(QMessageBox.StandardButton.Yes).click()

    index = main_window.tab_wallets.indexOf(main_window.qt_wallets[wallet_name].tab)

    do_modal_click(lambda: main_window.close_tab(index), password_creation, qtbot, cls=QMessageBox)
