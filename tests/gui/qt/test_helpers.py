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
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Callable, Generator, Optional, Tuple, Type, TypeVar
from unittest.mock import patch

import bdkpython as bdk
import pytest
from PyQt6 import QtCore
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.main import MainWindow
from bitcoin_safe.pythonbdk_types import BlockchainType
from tests.test_setup_bitcoin_core import (
    BITCOIN_HOST,
    BITCOIN_PORT,
    RPC_PASSWORD,
    RPC_USER,
)

logger = logging.getLogger(__name__)


def get_current_test_name():
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
def test_start_time():
    """Fixture to capture the start time of the test session."""
    return datetime.now()


class TestConfig(UserConfig):
    config_dir = Path(tempfile.mkdtemp())
    config_file = Path(config_dir) / (UserConfig.app_name + ".conf")


@pytest.fixture(scope="session")
def test_config() -> TestConfig:
    config = TestConfig()
    logger.info(f"Setting config_dir = {config.config_dir} and config_file = {config.config_file}")
    config.network = bdk.Network.REGTEST
    config.network_config.server_type = BlockchainType.RPC
    config.network_config.rpc_ip = BITCOIN_HOST
    config.network_config.rpc_port = BITCOIN_PORT
    config.network_config.rpc_username = RPC_USER
    config.network_config.rpc_password = RPC_PASSWORD
    return config


@contextmanager
def application_context() -> Generator[QApplication, None, None]:
    """Context manager that manages the QApplication lifecycle."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    try:
        yield app
    finally:
        app.quit()


@contextmanager
def main_window_context(test_config: UserConfig) -> Generator[Tuple[QApplication, MainWindow], None, None]:
    """Context manager that manages the MainWindow lifecycle."""
    with application_context() as app:
        window = MainWindow(config=test_config)
        window.show()
        try:
            yield app, window
        finally:
            window.close()


# Define a Type Variable
T = TypeVar("T", bound=QWidget)  # This constrains T to be a subclass of QWidget


class Shutter:
    def __init__(self, qtbot: QtBot, test_start_time: datetime) -> None:
        self.qtbot = qtbot
        self.test_start_time = test_start_time

    def save(self, widget, delay=0.2):
        QApplication.processEvents()
        sleep(delay)
        self.save_screenshot(widget, self.qtbot, self.test_start_time)

    @staticmethod
    def directory(test_start_time: datetime) -> Path:
        """Saves a screenshot of the given main window using qtbot to the 'screenshots' directory with a timestamp."""
        # Ensure the 'screenshots' directory exists
        screenshots_dir = Path("tests") / "output" / f"screenshots_{test_start_time}"
        screenshots_dir.mkdir(exist_ok=True, parents=True)
        return screenshots_dir

    @staticmethod
    def save_screenshot(widget: QMainWindow, qtbot: QtBot, test_start_time: datetime) -> Path:
        """Saves a screenshot of the given main window using qtbot to the 'screenshots' directory with a timestamp."""
        # Ensure the 'screenshots' directory exists
        screenshots_dir = Shutter.directory(test_start_time)

        # Take a screenshot using qtbot, which returns the path to the temporary saved file
        temp_filepath: Path = qtbot.screenshot(widget)
        final_filepath = (
            screenshots_dir / f"{datetime.now().timestamp()}_{get_current_test_name()}_{temp_filepath.name}"
        )

        # Copy the screenshot from the temporary location to the desired directory
        shutil.move(str(temp_filepath), str(final_filepath))

        return final_filepath

    @staticmethod
    def create_symlink(test_start_time: datetime, test_config: UserConfig):
        screenshots_dir = Shutter.directory(test_start_time)
        (screenshots_dir / "config_dir").symlink_to(test_config.config_dir)


def _get_widget_top_level(cls: Type[T], title=None) -> Optional[T]:
    """
    Find the top-level widget of the specified class and title among the active widgets.

    Args:
    cls (QWidget): The class type to look for.
    title (str): The window title to match. Optional.

    Returns:
    QWidget or False: The widget if found, otherwise False.
    """
    QApplication.processEvents()
    for widget in QApplication.topLevelWidgets():
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


def get_widget_top_level(cls: Type[T], qtbot: QtBot, title=None, wait=True, timeout=10000) -> Optional[T]:
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
    click_pushbutton: QWidget,
    on_open: Callable[[T], None],
    qtbot: QtBot,
    button: QtCore.Qt.MouseButton = QtCore.Qt.MouseButton.LeftButton,
    cls: Type[T] = QMessageBox,
    timeout=5000,
):
    def click():
        print("\nwaiting for is_dialog_open")

        dialog = get_widget_top_level(cls=cls, qtbot=qtbot, timeout=timeout)
        assert dialog

        print("is_dialog_open = True")
        print("Do on_open")
        on_open(dialog)

    QtCore.QTimer.singleShot(10, click)
    qtbot.mouseClick(click_pushbutton, button)


def assert_message_box(click_pushbutton: QPushButton, tile: str, message_text: str):
    with patch("bitcoin_safe.gui.qt.util.QMessageBox") as mock_msgbox:
        click_pushbutton.click()
        while not mock_msgbox.called:
            QApplication.processEvents()
            sleep(0.2)

        called_args, called_kwargs = mock_msgbox.call_args
        assert called_args[1] == tile
        assert called_args[2] == message_text


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