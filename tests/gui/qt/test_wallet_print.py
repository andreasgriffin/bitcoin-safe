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
import shutil
from datetime import datetime
from pathlib import Path
from time import sleep

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from tests.setup_fulcrum import Faucet
from .test_wallet_send import SEND_TEST_WALLET_FUND_AMOUNT
from .helpers import (
    CheckedDeletionContext,
    Shutter,
    close_wallet,
    fund_wallet,
    main_window_context,
)


@pytest.mark.marker_qt_2
def test_print_existing_transaction(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: UserConfig,
    faucet: Faucet,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    wallet_file: str = "send_test.wallet",
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        temp_wallet_path = tmp_path / wallet_file
        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(wallet_path, temp_wallet_path)

        qt_wallet = main_window.open_wallet(str(temp_wallet_path))
        assert qt_wallet

        if not qt_wallet.wallet.sorted_delta_list_transactions():
            fund_wallet(qtbot=qtbot, faucet=faucet, qt_wallet=qt_wallet, amount=SEND_TEST_WALLET_FUND_AMOUNT)

        tx_history = qt_wallet.wallet.sorted_delta_list_transactions()

        assert tx_history, "Expected at least one transaction in the wallet history"
        tx_details = tx_history[0]

        main_window.open_tx_like_in_tab(tx_details)
        QApplication.processEvents()

        viewer = main_window.get_tx_viewer(tx_details.txid)
        assert viewer
        assert isinstance(viewer, UITx_Viewer)

        pdf_path = tmp_path / "printed_transaction.pdf"

        monkeypatch.setattr(
            "bitcoin_safe.gui.qt.export_data.DataExportPDF.open_pdf",
            lambda self, path: None,
        )
        viewer.export_data_simple.button_export_file.export_to_pdf(filepath=pdf_path)

        assert pdf_path.exists()
        assert pdf_path.is_file()
        assert pdf_path.stat().st_size > 0

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

        shutter.save(main_window)
