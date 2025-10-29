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
from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from tests.gui.qt.test_setup_wallet import close_wallet

from .helpers import CheckedDeletionContext, Shutter, close_wallet, main_window_context

logger = logging.getLogger(__name__)


def test_default_network_config_works(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config_main_chain: UserConfig,
    caplog: pytest.LogCaptureFixture,
    wallet_file: str = "bacon.wallet",
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(
        qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }"
    )

    shutter.create_symlink(test_config=test_config_main_chain)
    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe"

        shutter.save(main_window)

        temp_dir = Path(tempfile.mkdtemp()) / wallet_file

        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert qt_wallet

        qt_wallet.tabs.setCurrentWidget(qt_wallet.address_tab)

        shutter.save(main_window)
        # check wallet address
        assert qt_wallet.wallet.get_addresses()[0] == "bc1qyngkwkslw5ng4v7m42s8t9j6zldmhyvrnnn9k5"

        def do_all(qt_wallet: QTWallet):
            "any implicit reference to qt_wallet (including the function page_send) will create a cell refrence"

            def sync():
                with qtbot.waitSignal(qt_wallet.signal_after_sync, timeout=50000):
                    qt_wallet.sync()

                shutter.save(main_window)

                assert len(qt_wallet.wallet.sorted_delta_list_transactions()) >= 28

            sync()

        do_all(qt_wallet)

        with CheckedDeletionContext(
            qt_wallet=qt_wallet, qtbot=qtbot, caplog=caplog, graph_directory=shutter.used_directory()
        ):
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
            assert any(
                [
                    (wallet_file in name)
                    for name in main_window.config.recently_open_wallets[main_window.config.network]
                ]
            )

            shutter.save(main_window)

        check_that_it_is_in_recent_wallets()

        # end
        shutter.save(main_window)
