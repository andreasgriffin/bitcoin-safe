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
from tests.gui.qt.test_setup_wallet import close_wallet, get_tab_with_title, save_wallet

from ...test_helpers import test_config  # type: ignore
from ...test_helpers import test_config_main_chain  # type: ignore
from ...test_setup_bitcoin_core import Faucet, bitcoin_core, faucet  # type: ignore
from .test_helpers import (  # type: ignore
    CheckedDeletionContext,
    Shutter,
    close_wallet,
    do_modal_click,
    get_tab_with_title,
    get_widget_top_level,
    main_window_context,
    save_wallet,
    test_start_time,
)

logger = logging.getLogger(__name__)


@pytest.mark.marker_qt_2
def test_open_wallet_and_address_is_consistent_and_destruction_ok(
    qapp: QApplication,
    qtbot: QtBot,
    test_start_time: datetime,
    test_config: UserConfig,
    bitcoin_core: Path,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    wallet_file: str = "0.2.0.wallet",
    amount: int = int(1e6),
) -> None:  # bitcoin_core: Path,
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{test_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }")

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
