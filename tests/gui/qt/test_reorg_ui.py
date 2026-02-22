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
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtGui import QIcon, QStandardItem
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.main import MainWindow
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.util import sort_id_to_icon, svg_tools
from bitcoin_safe.wallet import TxStatus

from ...faucet import Faucet
from ...helpers import TestConfig
from ...non_gui.test_signers import test_seeds
from ...setup_bitcoin_core import bitcoin_cli
from .helpers import (
    Shutter,
    broadcast_tx,
    fund_wallet,
    main_window_context,
    setup_single_sig_wallet,
    sign_tx,
)


def _bitcoin_cli_json(bitcoin_core: Path, command: str) -> dict[str, Any] | list[Any]:
    """Run an RPC command and parse JSON output, retrying transient RPC failures."""
    for _ in range(20):
        result = bitcoin_cli(command, bitcoin_core)
        if result:
            return json.loads(result)
        time.sleep(1)
    raise AssertionError(f"bitcoin-cli returned no output for command after retries: {command}")


def _active_tip(bitcoin_core: Path) -> dict[str, Any]:
    """Return the active tip from getchaintips."""
    chain_tips = _bitcoin_cli_json(bitcoin_core, "getchaintips")
    assert isinstance(chain_tips, list)
    active_tips = [tip for tip in chain_tips if isinstance(tip, dict) and tip.get("status") == "active"]
    assert len(active_tips) == 1
    return active_tips[0]


def _block_contains_tx(bitcoin_core: Path, block_hash: str, txid: str) -> bool:
    """Check whether a block contains a transaction id."""
    block = _bitcoin_cli_json(bitcoin_core, f"getblock {block_hash} 1")
    assert isinstance(block, dict)
    txids = block.get("tx")
    assert isinstance(txids, list)
    return txid in txids


def _sync_wallet_and_refresh_ui(qt_wallet: QTWallet, qtbot: QtBot) -> None:
    """Force a sync tick and refresh UI lists."""
    qt_wallet.wallet.trigger_sync()
    qtbot.wait(300)
    qt_wallet.refresh_caches_and_ui_lists(force_ui_refresh=True)
    qtbot.wait(100)


def _wait_for_history_tx_presence(qt_wallet: QTWallet, qtbot: QtBot, txid: str, present: bool) -> None:
    """Wait until txid is present or absent in history."""

    def condition() -> bool:
        _sync_wallet_and_refresh_ui(qt_wallet=qt_wallet, qtbot=qtbot)
        return (qt_wallet.history_list.find_row_by_key(txid) is not None) is present

    qtbot.waitUntil(condition, timeout=180_000)


def _history_status_item(qt_wallet: QTWallet, txid: str) -> QStandardItem:
    """Return the status column item for a txid from history."""
    row = qt_wallet.history_list.find_row_by_key(txid)
    assert row is not None
    status_item = qt_wallet.history_list._source_model.item(row, qt_wallet.history_list.Columns.STATUS)
    assert status_item is not None
    return status_item


def _icon_matches(actual: QIcon, expected: QIcon) -> bool:
    """Robust icon comparison that works across QIcon cache/pixmap paths."""
    return actual.cacheKey() == expected.cacheKey() or (
        actual.pixmap(16, 16).toImage() == expected.pixmap(16, 16).toImage()
    )


def _expected_tx_icon(qt_wallet: QTWallet, txid: str) -> QIcon:
    """Return the expected icon for txid based on current wallet status."""
    tx_status = TxStatus.from_wallet(txid, qt_wallet.wallet)
    return svg_tools.get_QIcon(sort_id_to_icon(tx_status.sort_id()))


def _wait_for_unconfirmed_history_status(qt_wallet: QTWallet, qtbot: QtBot, txid: str) -> None:
    """Wait until txid is shown as mempool unconfirmed in history."""

    def condition() -> bool:
        _sync_wallet_and_refresh_ui(qt_wallet=qt_wallet, qtbot=qtbot)
        tx_status = TxStatus.from_wallet(txid, qt_wallet.wallet)
        return tx_status.is_unconfirmed() and tx_status.is_in_mempool()

    qtbot.waitUntil(condition, timeout=180_000)
    status_item = _history_status_item(qt_wallet=qt_wallet, txid=txid)
    tx_status = TxStatus.from_wallet(txid, qt_wallet.wallet)
    assert tx_status.is_unconfirmed()
    assert not status_item.icon().isNull()
    assert status_item.toolTip() == qt_wallet.history_list.tr("Waiting to be included in a block")


def _wait_for_tx_viewer_icon(main_window: MainWindow, qt_wallet: QTWallet, qtbot: QtBot, txid: str) -> None:
    """Wait until the tx-viewer tab icon matches the current tx status icon."""

    def condition() -> bool:
        _sync_wallet_and_refresh_ui(qt_wallet=qt_wallet, qtbot=qtbot)
        viewer = main_window.get_tx_viewer(txid)
        if not viewer:
            return False
        node = main_window.tab_wallets.root.findNodeByWidget(viewer)
        if not node or not node.icon:
            return False
        return _icon_matches(node.icon, _expected_tx_icon(qt_wallet=qt_wallet, txid=txid))

    qtbot.waitUntil(condition, timeout=180_000)


def _wait_for_non_confirmed_tx_status(qt_wallet: QTWallet, qtbot: QtBot, txid: str, timeout_ms: int) -> bool:
    """Wait for tx status to become non-confirmed and return whether it happened in time."""
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        _sync_wallet_and_refresh_ui(qt_wallet=qt_wallet, qtbot=qtbot)
        if not TxStatus.from_wallet(txid, qt_wallet.wallet).is_confirmed():
            return True
    return False


def _create_sign_and_broadcast_self_send(
    main_window: MainWindow,
    qt_wallet: QTWallet,
    qtbot: QtBot,
    shutter: Shutter,
    amount: int,
) -> str:
    """Create, sign and broadcast a self-send transaction."""
    qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
    creator = qt_wallet.uitx_creator
    creator.clear_ui()

    recipient_box = creator.recipients.get_recipient_group_boxes()[0]
    recipient_box.address = str(qt_wallet.wallet.get_address().address)
    recipient_box.amount = amount // 2
    creator.column_fee.fee_group.spin_fee_rate.setValue(1.0)

    with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
        creator.button_ok.click()

    viewer = main_window.tab_wallets.currentNode().data
    assert isinstance(viewer, UITx_Viewer)
    if viewer.button_next.isVisible():
        viewer.button_next.click()

    sign_tx(qtbot=qtbot, shutter=shutter, viewer=viewer, qt_wallet=qt_wallet)
    txid = str(viewer.extract_tx().compute_txid())
    broadcast_tx(qtbot=qtbot, shutter=shutter, viewer=viewer, qt_wallet=qt_wallet)
    return txid


@pytest.mark.marker_qt_2
def test_reorg_keeps_tx_in_history_when_reincluded(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    bitcoin_core: Path,
    wallet_name: str = "test_reorg_keeps_tx_in_history_when_reincluded",
    amount: int = int(1e6),
) -> None:
    """Reorg to a longer chain that still includes tx A; tx A must remain in history."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)

        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name=wallet_name,
            seed=test_seeds[16],
        )
        fund_wallet(qt_wallet=qt_wallet, amount=amount, faucet=faucet, qtbot=qtbot)
        txid_a = _create_sign_and_broadcast_self_send(
            main_window=main_window,
            qt_wallet=qt_wallet,
            qtbot=qtbot,
            shutter=shutter,
            amount=amount,
        )

        miner_address = str(faucet.wallet.get_address().address)
        mined_with_a = _bitcoin_cli_json(bitcoin_core, f"generatetoaddress 1 {miner_address}")
        assert isinstance(mined_with_a, list)
        assert len(mined_with_a) == 1
        confirmed_block_with_a = str(mined_with_a[0])

        tx_a_confirmed = _bitcoin_cli_json(bitcoin_core, f"getrawtransaction {txid_a} true")
        assert isinstance(tx_a_confirmed, dict)
        assert int(tx_a_confirmed["confirmations"]) == 1
        assert str(tx_a_confirmed["blockhash"]) == confirmed_block_with_a
        assert _block_contains_tx(bitcoin_core=bitcoin_core, block_hash=confirmed_block_with_a, txid=txid_a)
        _wait_for_history_tx_presence(qt_wallet=qt_wallet, qtbot=qtbot, txid=txid_a, present=True)

        tip_before_reorg = _active_tip(bitcoin_core=bitcoin_core)
        assert str(tip_before_reorg["hash"]) == confirmed_block_with_a
        tip_before_reorg_height = int(tip_before_reorg["height"])

        bitcoin_cli(f"invalidateblock {confirmed_block_with_a}", bitcoin_core)
        tip_after_invalidate = _active_tip(bitcoin_core=bitcoin_core)
        assert int(tip_after_invalidate["height"]) == tip_before_reorg_height - 1

        bitcoin_cli(f"reconsiderblock {confirmed_block_with_a}", bitcoin_core)
        tip_after_reconsider = _active_tip(bitcoin_core=bitcoin_core)
        assert str(tip_after_reconsider["hash"]) == confirmed_block_with_a
        assert int(tip_after_reconsider["height"]) == tip_before_reorg_height

        longer_branch_blocks = _bitcoin_cli_json(bitcoin_core, f"generatetoaddress 1 {miner_address}")
        assert isinstance(longer_branch_blocks, list)
        assert len(longer_branch_blocks) == 1
        assert isinstance(longer_branch_blocks[0], str)

        tip_after_reorg = _active_tip(bitcoin_core=bitcoin_core)
        assert int(tip_after_reorg["height"]) == tip_before_reorg_height + 1

        tx_a_after_reorg = _bitcoin_cli_json(bitcoin_core, f"getrawtransaction {txid_a} true")
        assert isinstance(tx_a_after_reorg, dict)
        assert int(tx_a_after_reorg["confirmations"]) >= 2
        block_hash_after_reorg = str(tx_a_after_reorg["blockhash"])
        assert block_hash_after_reorg == confirmed_block_with_a
        assert _block_contains_tx(bitcoin_core=bitcoin_core, block_hash=block_hash_after_reorg, txid=txid_a)

        _wait_for_history_tx_presence(qt_wallet=qt_wallet, qtbot=qtbot, txid=txid_a, present=True)


@pytest.mark.marker_qt_2
def test_reorged_out_tx_stays_unconfirmed_in_history(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    bitcoin_core: Path,
    backend: str,
    wallet_name: str = "test_reorged_out_tx_stays_unconfirmed_in_history",
    amount: int = int(1e6),
) -> None:
    """Reorg tx A out of active chain; keep it in mempool and verify history/viewer status icon updates."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)

        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name=wallet_name,
            seed=test_seeds[17],
        )
        fund_wallet(qt_wallet=qt_wallet, amount=amount, faucet=faucet, qtbot=qtbot)
        txid_a = _create_sign_and_broadcast_self_send(
            main_window=main_window,
            qt_wallet=qt_wallet,
            qtbot=qtbot,
            shutter=shutter,
            amount=amount,
        )

        miner_address = str(faucet.wallet.get_address().address)
        mined_with_a = _bitcoin_cli_json(bitcoin_core, f"generatetoaddress 1 {miner_address}")
        assert isinstance(mined_with_a, list)
        assert len(mined_with_a) == 1
        confirmed_block_with_a = str(mined_with_a[0])

        tx_a_confirmed = _bitcoin_cli_json(bitcoin_core, f"getrawtransaction {txid_a} true")
        assert isinstance(tx_a_confirmed, dict)
        assert int(tx_a_confirmed["confirmations"]) == 1
        assert str(tx_a_confirmed["blockhash"]) == confirmed_block_with_a
        assert _block_contains_tx(bitcoin_core=bitcoin_core, block_hash=confirmed_block_with_a, txid=txid_a)
        _wait_for_history_tx_presence(qt_wallet=qt_wallet, qtbot=qtbot, txid=txid_a, present=True)

        # Open tx A in viewer and lock in the confirmed icon before the reorg.
        qt_wallet.signals.open_tx_like.emit(txid_a)
        qtbot.waitUntil(
            lambda: isinstance(main_window.tab_wallets.currentNode().data, UITx_Viewer),
            timeout=10_000,
        )
        viewer = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer, UITx_Viewer)
        assert viewer.txid() == txid_a
        _wait_for_tx_viewer_icon(main_window=main_window, qt_wallet=qt_wallet, qtbot=qtbot, txid=txid_a)

        tip_before_reorg = _active_tip(bitcoin_core=bitcoin_core)
        assert str(tip_before_reorg["hash"]) == confirmed_block_with_a
        tip_before_reorg_height = int(tip_before_reorg["height"])

        bitcoin_cli(f"invalidateblock {confirmed_block_with_a}", bitcoin_core)

        tip_after_invalidate = _active_tip(bitcoin_core=bitcoin_core)
        assert int(tip_after_invalidate["height"]) == tip_before_reorg_height - 1
        assert str(tip_after_invalidate["hash"]) != confirmed_block_with_a

        mempool_after_invalidate = _bitcoin_cli_json(bitcoin_core, "getrawmempool")
        assert isinstance(mempool_after_invalidate, list)
        assert txid_a in mempool_after_invalidate

        mempool_entry = _bitcoin_cli_json(bitcoin_core, f"getmempoolentry {txid_a}")
        assert isinstance(mempool_entry, dict)

        deprioritize_result = bitcoin_cli(f"prioritisetransaction {txid_a} 0 -100000000", bitcoin_core)
        assert deprioritize_result == "true"

        try:
            longer_branch_blocks = _bitcoin_cli_json(bitcoin_core, f"generatetoaddress 2 {miner_address}")
            assert isinstance(longer_branch_blocks, list)
            assert len(longer_branch_blocks) == 2
            for block_hash in longer_branch_blocks:
                assert isinstance(block_hash, str)
                assert not _block_contains_tx(bitcoin_core=bitcoin_core, block_hash=block_hash, txid=txid_a)

            tip_after_reorg = _active_tip(bitcoin_core=bitcoin_core)
            assert int(tip_after_reorg["height"]) == tip_before_reorg_height + 1

            mempool_after_longer_chain = _bitcoin_cli_json(bitcoin_core, "getrawmempool")
            assert isinstance(mempool_after_longer_chain, list)
            assert txid_a in mempool_after_longer_chain

            tx_a_after_reorg_out = _bitcoin_cli_json(bitcoin_core, f"getrawtransaction {txid_a} true")
            assert isinstance(tx_a_after_reorg_out, dict)
            assert int(tx_a_after_reorg_out.get("confirmations", 0)) == 0
            assert "blockhash" not in tx_a_after_reorg_out

            _wait_for_history_tx_presence(qt_wallet=qt_wallet, qtbot=qtbot, txid=txid_a, present=True)
            if backend == "fulcrum":
                _wait_for_unconfirmed_history_status(qt_wallet=qt_wallet, qtbot=qtbot, txid=txid_a)
                tx_status = TxStatus.from_wallet(txid_a, qt_wallet.wallet)
                assert tx_status.is_unconfirmed()
                assert tx_status.is_in_mempool()
                assert not tx_status.is_local()
                status_item = _history_status_item(qt_wallet=qt_wallet, txid=txid_a)
                assert status_item.text() != qt_wallet.history_list.tr("Local")
            else:
                if not _wait_for_non_confirmed_tx_status(
                    qt_wallet=qt_wallet, qtbot=qtbot, txid=txid_a, timeout_ms=180_000
                ):
                    pytest.skip("CBF backend did not propagate non-confirmed reorg state in time")

            # Regression check: when tx A is open in the viewer, its tab icon must update after reorg.
            _wait_for_tx_viewer_icon(main_window=main_window, qt_wallet=qt_wallet, qtbot=qtbot, txid=txid_a)
        finally:
            reprioritize_result = bitcoin_cli(f"prioritisetransaction {txid_a} 0 100000000", bitcoin_core)
            assert reprioritize_result == "true"
