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
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from tests.gui.qt.test_setup_wallet import close_wallet

from ...setup_fulcrum import Faucet
from .helpers import CheckedDeletionContext, Shutter, close_wallet, main_window_context

logger = logging.getLogger(__name__)


@pytest.mark.marker_qt_2
def test_open_wallet_and_address_is_consistent_and_destruction_ok(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: UserConfig,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    wallet_file: str = "0.2.0.wallet",
    amount: int = int(1e6),
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(
        qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }"
    )

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        temp_dir = Path(tempfile.mkdtemp()) / wallet_file

        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert qt_wallet

        qt_wallet.tabs.setCurrentWidget(qt_wallet.address_tab)

        shutter.save(main_window)
        # check wallet address
        assert (
            qt_wallet.wallet.get_addresses()[0]
            == "bcrt1qklm7yyvyu2av4f35ve6tm8mpn6mkr8e3dpjd3jp9vn77vu670g7qu9cznl"
        )

        def check_empty():
            assert qt_wallet.wallet.get_balance().total == 0

        check_empty()

        def open_tx() -> UITx_Viewer:
            tx = "0200000000010130e2288abc2259145cbd255a0cc94fe7226d26130b216100a9d631d7f31a5b090100000000fdffffff024894f31c01000000225120a450dee7d2d0f14d720b359f23660fed35c031de2d54e8fb0db8bd9f6b1ee35829ee250000000000220020b7f7e21184e2bacaa6346674bd9f619eb7619f316864d8c82564fde6735e7a3c0247304402203b76bd679a0f6ec4846a791247a5551771db6147a92f42e76ec4c079d3caf60502204f1bed609ee20c271faae2042c1d2727923650aea9439df78da45384e5979f1d01210370a2b7a566702a384ceb8e9f9f4c9ae8a4b4904b832c4de2cf19f3289285e20300000000"
            main_window.signals.open_tx_like.emit(tx)
            QApplication.processEvents()

            for child in main_window.tab_wallets.root.child_nodes:
                if isinstance(child.widget, UITx_Viewer):
                    return child.widget
            raise Exception("no UITx_Viewer found")

        def save_tx_to_local(tx_tab: UITx_Viewer):
            assert tx_tab.button_save_local_tx.isVisible()
            tx_tab.save_local_tx()
            QApplication.processEvents()

            assert qt_wallet.tabs.currentWidget() == qt_wallet.history_tab
            QApplication.processEvents()

            assert qt_wallet.history_list.get_selected_keys() == [
                "6592209efae6c76e77626ffd62f2a59649a82aa3140f1d592f8e282293ececa3"
            ]

            for child in main_window.tab_wallets.root.child_nodes:
                if isinstance(child.widget, UITx_Viewer):
                    child.removeNode()

        def open_and_save_tx():
            tx_tab = open_tx()
            save_tx_to_local(tx_tab)

        open_and_save_tx()

        # if True:
        with CheckedDeletionContext(
            qt_wallet=qt_wallet, qtbot=qtbot, caplog=caplog, graph_directory=shutter.used_directory()
        ):
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
