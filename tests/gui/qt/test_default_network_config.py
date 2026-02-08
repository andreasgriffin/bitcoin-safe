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

from bitcoin_safe.gui.qt.qt_wallet import QTWallet

from ...helpers import TestConfig
from .helpers import CheckedDeletionContext, Shutter, close_wallet, main_window_context

logger = logging.getLogger(__name__)


def test_default_network_config_works(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config_main_chain: TestConfig,
    caplog: pytest.LogCaptureFixture,
    wallet_file: str = "bacon.wallet",
) -> None:
    """Test default network config works."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config_main_chain)
    with main_window_context(test_config=test_config_main_chain) as main_window:
        # Wait until the main window is shown before interacting.
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe"

        shutter.save(main_window)

        # Copy the fixture wallet so the test can modify it safely.
        temp_dir = Path(tempfile.mkdtemp()) / wallet_file
        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        # Open the wallet and switch to the address tab.
        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert qt_wallet

        qt_wallet.tabs.setCurrentWidget(qt_wallet.address_tab)

        shutter.save(main_window)
        # Ensure the default wallet address matches the expected value.
        assert qt_wallet.wallet.get_addresses()[0] == "bc1qyngkwkslw5ng4v7m42s8t9j6zldmhyvrnnn9k5"

        def do_all(qt_wallet: QTWallet) -> None:
            # Avoid implicit references outside this scope that might keep qt_wallet alive.

            def sync() -> None:
                # Run a sync and wait for the signal to confirm completion.
                with qtbot.waitSignal(qt_wallet.signal_after_sync, timeout=50000):
                    qt_wallet.sync()

                shutter.save(main_window)

                # Sanity check that some transaction history is available.
                assert len(qt_wallet.wallet.sorted_delta_list_transactions()) >= 28

            sync()

        do_all(qt_wallet)

        with CheckedDeletionContext(
            qt_wallet=qt_wallet, qtbot=qtbot, caplog=caplog, graph_directory=shutter.used_directory()
        ):
            # Delete the reference and close the wallet UI to exercise cleanup.
            wallet_id = qt_wallet.wallet.id
            del qt_wallet

            close_wallet(
                shutter=shutter,
                test_config=test_config_main_chain,
                wallet_name=wallet_id,
                qtbot=qtbot,
                main_window=main_window,
            )
            shutter.save(main_window)

        def check_that_it_is_in_recent_wallets() -> None:
            # Ensure the wallet path shows up in recent wallets for this network.
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
