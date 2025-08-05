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

import gc
import inspect
import json
import logging
import os
import platform
import re
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, Callable, Generator, List, Optional, Type, TypeVar, Union
from unittest.mock import patch

import objgraph
import pytest
from PyQt6 import QtCore
from PyQt6.QtGui import QAction
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QWidget,
)
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.dialogs import PasswordCreation
from bitcoin_safe.gui.qt.main import MainWindow
from bitcoin_safe.gui.qt.qt_wallet import QTWallet

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
def mytest_start_time() -> datetime:
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
        QApplication.processEvents()
        self.save_screenshot(widget, self.qtbot, self.name)

    @staticmethod
    def directory(name: str) -> Path:
        """Saves a screenshot of the given main window using qtbot to the 'screenshots' directory with a timestamp."""
        # Ensure the 'screenshots' directory exists
        screenshots_dir = Path("tests") / "output" / f"screenshots_{name}"
        screenshots_dir.mkdir(exist_ok=True, parents=True)
        return screenshots_dir

    def used_directory(self) -> Path:
        return Shutter.directory(self.name)

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
    click_pushbutton: Union[Callable, QWidget, QAction],
    on_open: Callable[[T], None],
    qtbot: QtBot,
    button: QtCore.Qt.MouseButton = QtCore.Qt.MouseButton.LeftButton,
    cls: Type[T] = Union[QMessageBox, QWidget],
    timeout=5000,
    timer_delay=500,
) -> None:
    dialog_was_opened = False

    def click() -> None:
        QApplication.processEvents()
        print("\nwaiting for is_dialog_open")

        try:
            dialog = get_widget_top_level(cls=cls, qtbot=qtbot, timeout=timeout)
            nonlocal dialog_was_opened
            dialog_was_opened = True
        except Exception as e:
            logger.error(f"Failed to get {cls.__name__}")
            raise e
        assert dialog, f"Failed to get {cls.__name__}"

        print("is_dialog_open = True")
        print("Do on_open")
        on_open(dialog)

    QtCore.QTimer.singleShot(timer_delay, click)
    if callable(click_pushbutton):
        click_pushbutton()
    elif isinstance(click_pushbutton, QAction):
        click_pushbutton.trigger()
    else:
        qtbot.mouseClick(click_pushbutton, button)

    QApplication.processEvents()
    qtbot.waitUntil(lambda: dialog_was_opened, timeout=10000)


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


def save_wallet(
    test_config: UserConfig,
    wallet_name: str,
    save_button: QPushButton,
) -> Path:

    wallet_file = Path(test_config.config_dir) / f"{wallet_name}.wallet"
    with patch.object(
        QFileDialog, "getSaveFileName", return_value=(str(wallet_file), "All Files (*)")
    ) as mock_open:

        with patch.object(PasswordCreation, "get_password", return_value="") as mock_password:

            save_button.click()

            QApplication.processEvents()
            mock_password.assert_called_once()

        mock_open.assert_called_once()
    return wallet_file


def close_wallet(
    shutter: Shutter, test_config: UserConfig, wallet_name: str, qtbot: QtBot, main_window: MainWindow
) -> None:

    # check that you cannot go further without import xpub
    def password_creation(dialog: QMessageBox) -> None:
        shutter.save(dialog)
        for button in dialog.buttons():
            if button.text() == "Close":
                button.click()
                break

    node = main_window.tab_wallets.root.findNodeByTitle(wallet_name)

    do_modal_click(lambda: main_window.close_tab(node), password_creation, qtbot, cls=QMessageBox)
    gc.collect()


def clean_and_shorten(input_string, max_filename_len=50):
    # Remove characters problematic for filenames
    cleaned_string = re.sub(r'[\/:*?"<>|]', "", input_string)

    # Truncate the string to a maximum of 30 characters
    shortened_string = cleaned_string[:max_filename_len]

    return shortened_string


class CheckedDeletionContext:
    def __init__(
        self,
        qt_wallet: QTWallet,
        qtbot: QtBot,
        caplog: pytest.LogCaptureFixture,
        graph_directory: Path | None = None,
        list_references=None,
    ):
        self.graph_directory = graph_directory
        self.caplog = caplog
        self.qtbot = qtbot
        self.d = list_references
        self.check_for_destruction: List[QtCore.QObject] = [
            qt_wallet,
            # qt_wallet.address_list,
            # qt_wallet.address_list_with_toolbar,
            # qt_wallet.history_list,
            # qt_wallet.uitx_creator,
            # qt_wallet.uitx_creator.category_list,
            # qt_wallet.address_tab_category_editor,
        ]

    @classmethod
    def serialize_referrers(cls, obj: Any):
        referrers = gc.get_referrers(obj)

        # Simplify referrers to a list of strings or simple dicts
        simple_referrers = []
        for ref in referrers:
            if isinstance(ref, dict):
                # Provide a simple representation for dictionaries
                simple_referrers.append({str(k): str(v) for k, v in ref.items()})
            elif isinstance(ref, list):
                # Simplify lists by providing the type of elements or simple str representation
                simple_referrers.append([str(item) for item in ref])
            else:
                # Use a string representation for other types
                simple_referrers.append(str(ref))

        return simple_referrers

    @classmethod
    def save_single_referrers_to_json(cls, obj: Any, path: Path):
        filename = str(path / f"{cls.__name__}_{clean_and_shorten(str(obj))}.json")
        simplified_data = cls.serialize_referrers(obj)
        with open(filename, "w") as f:
            json.dump(simplified_data, f, indent=4)

    @classmethod
    def save_referrers_to_json(cls, objects: List[Any], path: Path):
        for o in objects:
            cls.save_single_referrers_to_json(o, path=path)

    @classmethod
    def show_backrefs(cls, objects: List[Any], path: Path):
        for o in objects:
            objgraph.show_backrefs(
                [o],
                shortnames=False,
                refcounts=True,
                max_depth=2,
                too_many=30,
                filename=str(path / f"{cls.__name__}_{clean_and_shorten(str(o))}.png"),
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):

        with self.qtbot.waitSignals([q.destroyed for q in self.check_for_destruction], timeout=1000):
            if self.graph_directory:
                self.show_backrefs(self.check_for_destruction, self.graph_directory)
                self.save_referrers_to_json(self.check_for_destruction, self.graph_directory)

            self.check_for_destruction.clear()
            gc.collect()

        ##### for_debug_only
        if self.d:
            # with qtbot.waitSignal(d, timeout=1000):
            gc.collect()
            logger.warning(str(gc.get_referrers(self.d)))
            del self.d
            gc.collect()
            # import gc
            # import types
            # # the function gets cell (lambda function) references
            # gx.collect()
            # def get_cell_referrers(obj):
            #     # Get all objects that refer to 'obj'
            #     referrers = gc.get_referrers(obj)
            #     # Filter to retain only cell objects
            #     cell_referrers = [ref for ref in referrers if isinstance(ref, types.CellType)]
            #     return cell_referrers
            # runt eh line below separately
            # len(get_cell_referrers(self))
        ##### for_debug_only
