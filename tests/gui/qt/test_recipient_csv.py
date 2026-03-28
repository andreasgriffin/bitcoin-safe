#
# Bitcoin Safe
# Copyright (C) 2026 Andreas Griffin
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
#

from __future__ import annotations

import csv
import inspect
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import bdkpython as bdk
import pytest
from bitcoin_qr_tools.data import Data, DataType
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.export_data import FileToolButton
from bitcoin_safe.gui.qt.recipient_csv import (
    export_recipients_csv,
    get_recipient_csv_header,
    get_recipients_from_data,
)
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.pythonbdk_types import Recipient
from tests.faucet import Faucet
from tests.non_gui.test_psbt_util import p2wsh_psbt_0_1of1
from tests.non_gui.test_signers import test_seeds

from ...helpers import TestConfig
from ...util import wait_for_sync
from .helpers import Shutter, fund_wallet, main_window_context, setup_single_sig_wallet


def _action_texts(button: FileToolButton) -> list[str]:
    return [action.text() for action in button._menu.actions() if not action.isSeparator()]


def test_export_recipients_csv_writes_expected_rows(tmp_path: Path) -> None:
    recipients = [
        Recipient(address="bcrt1qa", amount=125_000, label="Alice"),
        Recipient(address="bcrt1qb", amount=250_000, label=None),
    ]

    path = export_recipients_csv(
        recipients=recipients,
        network=bdk.Network.REGTEST,
        file_path=tmp_path / "recipients.csv",
    )

    assert path == tmp_path / "recipients.csv"

    with path.open() as file:
        rows = list(csv.reader(file))

    assert rows == [
        get_recipient_csv_header(bdk.Network.REGTEST),
        ["bcrt1qa", "125000", "Alice"],
        ["bcrt1qb", "250000", ""],
    ]


def test_file_toolbutton_adds_recipients_action_only_for_transaction_data(
    qapp: QApplication, qtbot: QtBot
) -> None:
    non_tx_button = FileToolButton(
        data=Data("bitcoin:bcrt1qexample", DataType.Bip21, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )
    qtbot.addWidget(non_tx_button)
    assert "Export Recipients CSV" not in _action_texts(non_tx_button)

    tx_button = FileToolButton(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )
    qtbot.addWidget(tx_button)
    assert "Export Recipients CSV" in _action_texts(tx_button)


def test_get_recipients_from_data_uses_address_label_metadata() -> None:
    unlabeled_recipients = get_recipients_from_data(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )
    assert unlabeled_recipients

    recipients = get_recipients_from_data(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
        address_labels_dict={unlabeled_recipients[0].address: "Alice"},
    )

    assert recipients[0].label == "Alice"


def test_file_toolbutton_add_meta_data_passes_labels_to_recipient_export(
    qapp: QApplication, qtbot: QtBot
) -> None:
    button = FileToolButton(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )
    qtbot.addWidget(button)

    recipients = get_recipients_from_data(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )
    assert recipients
    button.add_meta_data({recipients[0].address: "Alice"})

    with patch("bitcoin_safe.gui.qt.export_data.export_recipients_csv") as mock_export:
        mock_export.return_value = Path("recipients.csv")
        button.export_recipients_csv()

    exported_recipients = mock_export.call_args.kwargs["recipients"]
    assert exported_recipients[0].label == "Alice"


@pytest.mark.marker_qt_2
def test_viewer_hides_recipients_csv_toolbutton_and_moves_export_into_file_menu(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    wallet_name: str = "test_recipient_csv_viewer",
    amount: int = int(1e6),
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name=wallet_name,
            seed=test_seeds[51],
        )

        fund_wallet(faucet=faucet, qt_wallet=qt_wallet, amount=amount, qtbot=qtbot)

        wait_for_sync(wallet=qt_wallet.wallet, minimum_funds=1, qtbot=qtbot)

        tx_history = qt_wallet.wallet.sorted_delta_list_transactions()
        assert tx_history

        main_window.open_tx_like_in_tab(tx_history[0])
        QApplication.processEvents()

        viewer = main_window.get_tx_viewer(tx_history[0].txid)
        assert viewer
        assert isinstance(viewer, UITx_Viewer)

        assert viewer.recipients.toolbutton_csv.isHidden()
        assert "Export Recipients CSV" in _action_texts(viewer.export_data_simple.button_export_file)
