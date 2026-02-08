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

from bitcoin_safe.gui.qt import address_dialog
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.util import svg_tools

from ...helpers import TestConfig
from .helpers import (
    CheckedDeletionContext,
    Shutter,
    close_wallet,
    get_widget_top_level,
    main_window_context,
)

logger = logging.getLogger(__name__)


@pytest.mark.marker_qt_2
def test_open_wallet_and_address_is_consistent_and_destruction_ok(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    caplog: pytest.LogCaptureFixture,
    wallet_file: str = "0.2.0.wallet",
) -> None:
    """Test open wallet and address is consistent and destruction ok."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        # Wait for the main window to render before interacting.
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        # Copy the fixture wallet into a temp directory to avoid modifying originals.
        temp_dir = Path(tempfile.mkdtemp()) / wallet_file

        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        # Open the wallet and check UI wiring.
        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert isinstance(qt_wallet, QTWallet)

        waiting_icon = svg_tools.get_QIcon("status_waiting.svg")
        connected_icon = svg_tools.get_QIcon("status_connected.svg")

        # QIcon.cacheKey() uniquely identifies the rendered icon, so matching cache keys
        # verifies that the expected asset is set on the tab.
        qtbot.waitUntil(
            lambda: (_node := main_window.tab_wallets.root.findNodeByWidget(qt_wallet.tabs))  # noqa: F821
            and _node.icon
            and _node.icon.cacheKey() == waiting_icon.cacheKey(),
            timeout=10000,
        )

        qtbot.waitUntil(
            lambda: (_node := main_window.tab_wallets.root.findNodeByWidget(qt_wallet.tabs))  # noqa: F821
            and _node.icon
            and _node.icon.cacheKey() == connected_icon.cacheKey(),
            timeout=10000,
        )

        # Switch to the address tab to validate wallet info.
        qt_wallet.tabs.setCurrentWidget(qt_wallet.address_tab)

        shutter.save(main_window)
        # Check wallet address matches fixture value.
        wallet_address = qt_wallet.wallet.get_addresses()[0]
        assert wallet_address == "bcrt1qklm7yyvyu2av4f35ve6tm8mpn6mkr8e3dpjd3jp9vn77vu670g7qu9cznl"

        def check_open_address_dialog(qt_wallet: QTWallet) -> None:
            """Check open address dialog."""
            # Opening the address dialog should attach a new widget.
            prev_count = len(main_window.attached_widgets)
            main_window.show_address(wallet_address, qt_wallet.wallet.id)
            d = get_widget_top_level(address_dialog.AddressDialog, qtbot)
            assert d
            QTest.qWaitForWindowExposed(d, timeout=10000)
            assert d.address == wallet_address
            assert len(main_window.attached_widgets) == prev_count + 1
            shutter.save(d)
            d.close()
            QApplication.processEvents()
            qtbot.waitUntil(lambda: d not in main_window.attached_widgets)

        check_open_address_dialog(qt_wallet)

        def check_empty(qt_wallet: QTWallet) -> None:
            """Check empty."""
            # New wallet should start with zero balance.
            assert qt_wallet.wallet.get_balance().total == 0

        check_empty(qt_wallet)

        def open_tx() -> UITx_Viewer:
            """Open tx."""
            tx = "0200000000010130e2288abc2259145cbd255a0cc94fe7226d26130b216100a9d631d7f31a5b090100000000fdffffff024894f31c01000000225120a450dee7d2d0f14d720b359f23660fed35c031de2d54e8fb0db8bd9f6b1ee35829ee250000000000220020b7f7e21184e2bacaa6346674bd9f619eb7619f316864d8c82564fde6735e7a3c0247304402203b76bd679a0f6ec4846a791247a5551771db6147a92f42e76ec4c079d3caf60502204f1bed609ee20c271faae2042c1d2727923650aea9439df78da45384e5979f1d01210370a2b7a566702a384ceb8e9f9f4c9ae8a4b4904b832c4de2cf19f3289285e20300000000"
            # Emit a raw tx string and find the viewer tab created by the signal.
            main_window.signals.open_tx_like.emit(tx)
            QApplication.processEvents()

            for child in main_window.tab_wallets.root.child_nodes:
                if isinstance(child.widget, UITx_Viewer):
                    return child.widget
            raise Exception("no UITx_Viewer found")

        def save_tx_to_local(tx_tab: UITx_Viewer, qt_wallet: QTWallet) -> None:
            """Save tx to local."""
            # Save the tx locally and verify it appears in history.
            assert tx_tab.button_save_local_tx.isVisible()
            tx_tab.save_local_tx()
            QApplication.processEvents()

            assert qt_wallet.tabs.currentWidget() == qt_wallet.history_tab
            QApplication.processEvents()

            assert qt_wallet.history_list.get_selected_keys() == [
                "6592209efae6c76e77626ffd62f2a59649a82aa3140f1d592f8e282293ececa3"
            ]

            # Close the viewer tab to keep UI clean.
            for child in main_window.tab_wallets.root.child_nodes:
                if isinstance(child.widget, UITx_Viewer):
                    child.removeNode()

        def open_and_save_tx(qt_wallet: QTWallet) -> None:
            """Open and save tx."""
            tx_tab = open_tx()
            save_tx_to_local(tx_tab, qt_wallet)

        open_and_save_tx(qt_wallet)

        # if True:
        with CheckedDeletionContext(
            qt_wallet=qt_wallet, qtbot=qtbot, caplog=caplog, graph_directory=shutter.used_directory()
        ):
            # Delete and close the wallet to ensure cleanup paths are exercised.
            wallet_id = qt_wallet.wallet.id
            del qt_wallet
            close_wallet(
                shutter=shutter,
                test_config=test_config,
                wallet_name=wallet_id,
                qtbot=qtbot,
                main_window=main_window,
            )
            shutter.save(main_window)

        def check_that_it_is_in_recent_wallets() -> None:
            """Check that it is in recent wallets."""
            # The wallet should appear in recent wallets after closing.
            assert any(
                [
                    (wallet_file in name)
                    for name in main_window.config.recently_open_wallets[main_window.config.network]
                ]
            )

            shutter.save(main_window)

        check_that_it_is_in_recent_wallets()

        # Final screenshot after assertions.
        shutter.save(main_window)


def test_open_same_wallet_twice(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure reopening the same wallet shows an info message."""

    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        # Wait for the main window to render before interacting.
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore

        # Copy the fixture wallet into a temp path for this test.
        temp_dir = Path(tempfile.mkdtemp()) / "0.2.0.wallet"
        wallet_path = Path("tests") / "data" / "0.2.0.wallet"
        shutil.copy(str(wallet_path), str(temp_dir))

        # Open the wallet once, then attempt to open it again.
        first_wallet = main_window.open_wallet(str(temp_dir))
        assert first_wallet

        messages: list[str] = []

        class MessageRecorder:
            def __init__(self, msg: str, *args, **kwargs) -> None:  # noqa: ANN001, D401
                """Record message invocations."""

                messages.append(msg)

            def show(self) -> None:  # noqa: D401
                """Do not display message boxes during tests."""

        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.main.Message",
            MessageRecorder,
        )

        # Reopening the same file should show an info message and return None.
        reopened_wallet = main_window.open_wallet(str(temp_dir))
        assert reopened_wallet is None
        assert messages == [f"The wallet {temp_dir} is already open."]
        messages.clear()

        # copy the wallet do a different dir and try again to open it

        # Same wallet ID in a different path should also be rejected.
        different_dir = Path(tempfile.mkdtemp()) / f"{first_wallet.wallet.id}.wallet"
        shutil.copy(str(wallet_path), str(different_dir))

        reopened_duplicate = main_window.open_wallet(str(different_dir))
        assert reopened_duplicate is None
        assert messages == [
            f"A wallet with id {first_wallet.wallet.id} is already open. Please close it first.",
        ]

        shutter.save(main_window)
