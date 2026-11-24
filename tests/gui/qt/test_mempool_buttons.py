#
# Bitcoin-Safe
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

import bdkpython as bdk
import pytest
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.ui_tx.mempool_buttons import MempoolButtons
from bitcoin_safe.mempool_manager import MempoolManager
from bitcoin_safe.network_config import NetworkConfig
from bitcoin_safe.signals import Signals, WalletFunctions
from bitcoin_safe.wallet import TxConfirmationStatus, TxStatus


@pytest.mark.parametrize(
    ("fee_rate", "expected_index"),
    [
        (35.0, 0),  # Above all ranges.
        (25.0, 0),  # Inside a range.
        (19.0, 1),  # Inside the second block's range.
        (24.0, 0),  # Overlapping ranges keep the first matching block.
        (12.0, 2),  # Gap between the second and third blocks.
        (7.0, 3),  # Gap closest to the fourth block's upper limit.
        (0.5, 4),  # Below all ranges, with a nonconsecutive displayed index.
        (1.5, 4),  # Inside a nonconsecutive displayed block.
    ],
)
def test_fee_column_highlights_a_displayed_block(qtbot: QtBot, fee_rate: float, expected_index: int) -> None:
    signals = Signals()
    manager = MempoolManager(NetworkConfig(network=bdk.Network.REGTEST), signals, None)
    manager.data.mempool_blocks = [
        {"feeRange": [20.0, 30.0], "medianFee": 25.0},
        {"feeRange": [15.0, 24.0], "medianFee": 19.0},
        {"feeRange": [8.0, 10.0], "medianFee": 9.0},
        {"feeRange": [4.0, 6.0], "medianFee": 5.0},
        {"feeRange": [1.0, 2.0], "medianFee": 1.5},
    ]
    manager.data.mempool_dict["vsize"] = 5_000_000
    buttons = MempoolButtons(
        mempool_manager=manager,
        decimal_precision=1,
        tx_status=TxStatus(None, None, lambda: 0, TxConfirmationStatus.DRAFT),
        wallet_functions=WalletFunctions(signals),
        fee_rate=fee_rate,
    )
    qtbot.addWidget(buttons)
    try:
        selected = [button for button in buttons.buttons if button.active]
        assert len(selected) == 1
        assert selected[0].index == expected_index
        assert not selected[0].isHidden()

        buttons.refresh(fee_rate=1.5)
        assert [button.index for button in buttons.buttons if button.active] == [4]
        buttons._on_button_click(4)
        assert [button.index for button in buttons.buttons if button.active] == [4]
    finally:
        manager.close()


@pytest.mark.parametrize("block_count", [0, 1, 2])
def test_fee_column_highlights_when_few_estimates_are_available(qtbot: QtBot, block_count: int) -> None:
    signals = Signals()
    manager = MempoolManager(NetworkConfig(network=bdk.Network.REGTEST), signals, None)
    manager.data.mempool_blocks = [
        {"feeRange": [10.0 - i * 3, 12.0 - i * 3], "medianFee": 11.0 - i * 3} for i in range(block_count)
    ]
    manager.data.mempool_dict["vsize"] = 5_000_000
    buttons = MempoolButtons(
        mempool_manager=manager,
        decimal_precision=1,
        tx_status=TxStatus(None, None, lambda: 0, TxConfirmationStatus.DRAFT),
        wallet_functions=WalletFunctions(signals),
        fee_rate=0.5,
    )
    qtbot.addWidget(buttons)
    try:
        selected = [button for button in buttons.buttons if button.active]
        assert len(selected) == 1
        assert selected[0].index == max(0, block_count - 1)
        assert not selected[0].isHidden()
    finally:
        manager.close()
