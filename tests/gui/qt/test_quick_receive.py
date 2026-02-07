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

import inspect
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.qr_components.quick_receive import ReceiveGroup
from bitcoin_safe.gui.qt.qt_wallet import QTWallet

from ...helpers import TestConfig
from .helpers import Shutter, main_window_context

logger = logging.getLogger(__name__)


def _strip_invisible(text: str) -> str:
    return text.replace("\u200b", "").replace("\ufeff", "")


@pytest.mark.marker_qt_3
def test_quick_receive_copy_and_next_address(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    wallet_file: str = "0.2.0.wallet",
) -> None:
    """Test quick receive renders QR, copies address, and advances to next address."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        temp_dir = Path(tempfile.mkdtemp()) / wallet_file
        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert isinstance(qt_wallet, QTWallet)

        qt_wallet.tabs.setCurrentWidget(qt_wallet.history_tab)
        qtbot.waitUntil(lambda: qt_wallet.tabs.currentWidget() is qt_wallet.history_tab, timeout=5_000)

        quick_receive = qt_wallet.quick_receive
        qtbot.waitUntil(lambda: len(quick_receive.group_boxes) > 0, timeout=10_000)

        group_box = quick_receive.group_boxes[0]
        assert isinstance(group_box, ReceiveGroup)

        shutter.save(main_window)

        # Label should display the exact receive address (minus invisible chars).
        label_address = _strip_invisible(group_box.label.text())
        assert label_address == group_box.address

        quick_receive.scroll_area.ensureWidgetVisible(group_box)
        QTest.qWait(200)
        QApplication.processEvents()

        def qr_ready() -> bool:
            viewport = quick_receive.scroll_area.viewport()
            visible_in_viewport = bool(viewport) and group_box.qr_code.isVisibleTo(viewport)
            renderer_ready = (
                bool(group_box.qr_code.svg_renderers) and group_box.qr_code.svg_renderers[0].isValid()
            )
            return visible_in_viewport or renderer_ready

        qtbot.waitUntil(qr_ready, timeout=10_000)
        assert group_box.qr_code.svg_renderers
        assert group_box.qr_code.svg_renderers[0].isValid()

        # Copy button should place the address on the clipboard.
        clipboard = QApplication.clipboard()
        assert clipboard
        group_box.copy_button.click()
        qtbot.wait(200)
        assert clipboard.text() == group_box.address

        # "Force new" should advance to a different unused address.
        previous_address = group_box.address
        group_box.force_new_button.click()

        def address_updated() -> bool:
            if not quick_receive.group_boxes:
                return False
            return quick_receive.group_boxes[0].address != previous_address

        qtbot.waitUntil(address_updated, timeout=10_000)
        shutter.save(main_window)
