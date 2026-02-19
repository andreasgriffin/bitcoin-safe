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
from datetime import datetime

import pytest
from PyQt6.QtCore import QDateTime
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.main import MainWindow
from bitcoin_safe.gui.qt.nlocktime_group_box import NLocktimeMode
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.gui.qt.ui_tx.ui_tx_base import NLOCKTIME_FUTURE_YEARS
from bitcoin_safe.gui.qt.ui_tx.ui_tx_creator import UITx_Creator
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.tx import LOCKTIME_THRESHOLD

from ...faucet import Faucet
from ...helpers import TestConfig
from ...non_gui.test_signers import test_seeds
from .helpers import (
    Shutter,
    broadcast_tx,
    do_modal_click,
    fund_wallet,
    main_window_context,
    save_wallet,
    sign_tx,
)


def _setup_single_sig_wallet(
    main_window: MainWindow,
    qtbot: QtBot,
    shutter: Shutter,
    test_config: TestConfig,
    wallet_name: str,
) -> QTWallet:
    def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
        shutter.save(dialog)
        dialog.name_input.setText(wallet_name)
        dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()

    do_modal_click(
        main_window.welcome_screen.pushButton_custom_wallet,
        on_wallet_id_dialog,
        qtbot,
        cls=WalletIdDialog,
    )

    qt_protowallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
    assert isinstance(qt_protowallet, QTProtoWallet)

    qt_protowallet.wallet_descriptor_ui.spin_req.setValue(1)
    qt_protowallet.wallet_descriptor_ui.spin_signers.setValue(1)
    key = list(qt_protowallet.wallet_descriptor_ui.keystore_uis.getAllTabData().values())[0]
    key.tabs_import_type.setCurrentWidget(key.tab_manual)
    key.edit_seed.setText(test_seeds[0])
    shutter.save(main_window)

    save_wallet(
        test_config=test_config,
        wallet_name=wallet_name,
        save_button=qt_protowallet.wallet_descriptor_ui.button_box.button(
            QDialogButtonBox.StandardButton.Apply
        ),
    )

    qt_wallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
    assert isinstance(qt_wallet, QTWallet)
    return qt_wallet


@pytest.mark.marker_qt_2
def test_nlocktime_creator_viewer(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    wallet_name: str = "test_nlocktime_creator_viewer",
    amount: int = int(1e6),
) -> None:
    """Test nLocktime UI in creator and viewer."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)
        shutter.save(main_window)

        qt_wallet = _setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name=wallet_name,
        )

        fund_wallet(qt_wallet=qt_wallet, amount=amount, faucet=faucet, qtbot=qtbot)
        qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
        creator = qt_wallet.uitx_creator
        creator.clear_ui()
        qtbot.waitUntil(lambda: qt_wallet.wallet.get_height() > 0, timeout=10_000)

        # Enable the advanced nLocktime option so the UI becomes visible and initialized.
        creator.column_fee.action_set_nlocktime.setChecked(True)
        assert creator.column_fee.nlocktime_group.isVisible()
        # The default block height should match the wallet tip once the group is shown.
        current_height = qt_wallet.wallet.get_height()
        assert int(creator.column_fee.nlocktime_group.height_spin.value()) == current_height
        shutter.save(main_window)

        # Verify that a timestamp-based nLocktime (seconds) is read back correctly.
        custom_time = QDateTime.currentDateTime().addSecs(600)
        creator.column_fee.nlocktime_group.set_mode(NLocktimeMode.DATE_TIME)
        creator.column_fee.nlocktime_group.time_edit.setDateTime(custom_time)
        txinfos_time = creator.get_tx_ui_infos()
        assert txinfos_time.nlocktime == int(custom_time.toSecsSinceEpoch())
        shutter.save(main_window)

        # Verify that a future block-height nLocktime is captured correctly.
        creator.column_fee.nlocktime_group.set_mode(NLocktimeMode.BLOCK_HEIGHT)
        future_block_height = current_height + 1
        creator.column_fee.nlocktime_group.height_spin.setValue(future_block_height)
        txinfos_block = creator.get_tx_ui_infos()
        assert txinfos_block.nlocktime == future_block_height
        shutter.save(main_window)

        # Switch to a "valid now" height so the viewer may hide the nLocktime UI.
        block_height = current_height
        creator.column_fee.nlocktime_group.height_spin.setValue(block_height)
        shutter.save(main_window)

        # Prepare a simple self-send so the tx can be created.
        recipient_box = creator.recipients.get_recipient_group_boxes()[0]
        recipient_box.address = str(qt_wallet.wallet.get_address().address)
        recipient_box.amount = amount // 2
        creator.column_fee.fee_group.spin_fee_rate.setValue(1.0)
        shutter.save(main_window)

        # Create the transaction and open it in the viewer.
        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
            creator.button_ok.click()

        viewer = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer, UITx_Viewer)
        # The tx must carry the selected locktime; the UI may hide it if already valid.
        locktime = viewer.extract_tx().lock_time()
        assert locktime == block_height
        if locktime > current_height:
            assert viewer.column_fee.action_set_nlocktime.isChecked()
            assert viewer.column_fee.nlocktime_group.isVisible()
            assert int(viewer.column_fee.nlocktime_group.height_spin.value()) == block_height
            assert not viewer.column_fee.nlocktime_group.mode_combo.isEnabled()
        else:
            assert not viewer.column_fee.action_set_nlocktime.isChecked()
            assert not viewer.column_fee.nlocktime_group.isVisible()
        shutter.save(main_window)

        # Sign and save the tx locally so it appears in the wallet as a local tx.
        sign_tx(qtbot=qtbot, shutter=shutter, viewer=viewer, qt_wallet=qt_wallet)
        txid = str(viewer.extract_tx().compute_txid())
        viewer.save_local_tx()
        shutter.save(main_window)
        qtbot.waitUntil(lambda: qt_wallet.wallet.get_tx(txid) is not None, timeout=10_000)
        # Reopen the same tx to ensure we are acting on the local record.
        qt_wallet.signals.open_tx_like.emit(txid)
        qtbot.waitUntil(
            lambda: isinstance(main_window.tab_wallets.currentNode().data, UITx_Viewer),
            timeout=10_000,
        )
        viewer_local = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer_local, UITx_Viewer)
        shutter.save(main_window)
        # Broadcast the local tx so it becomes unconfirmed in the mempool.
        broadcast_tx(qtbot=qtbot, shutter=shutter, viewer=viewer_local, qt_wallet=qt_wallet)
        shutter.save(main_window)
        # Reopen after broadcast to get a mempool-backed viewer where RBF is available.
        qt_wallet.signals.open_tx_like.emit(txid)
        qtbot.waitUntil(
            lambda: isinstance(main_window.tab_wallets.currentNode().data, UITx_Viewer),
            timeout=10_000,
        )
        viewer_mempool = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer_mempool, UITx_Viewer)
        qtbot.waitUntil(lambda: viewer_mempool.button_rbf.isVisible(), timeout=10_000)
        shutter.save(main_window)

        # Enter the RBF flow from the mempool-backed viewer.
        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
            viewer_mempool.button_rbf.click()
        creator_rbf = main_window.tab_wallets.currentNode().data
        assert isinstance(creator_rbf, UITx_Creator)
        # The RBF creator should preserve the original nLocktime.
        assert int(creator_rbf.column_fee.nlocktime_group.height_spin.value()) == block_height
        shutter.save(main_window)

        # Create the RBF transaction and verify the locktime remains unchanged.
        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
            creator_rbf.button_ok.click()
        viewer_rbf = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer_rbf, UITx_Viewer)
        locktime_rbf = viewer_rbf.extract_tx().lock_time()
        assert locktime_rbf == block_height
        if locktime_rbf > current_height:
            assert int(viewer_rbf.column_fee.nlocktime_group.height_spin.value()) == block_height
        shutter.save(main_window)
        shutter.save(main_window)


@pytest.mark.marker_qt_2
def test_nlocktime_menu_toggle_clears_locktime(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    wallet_name: str = "test_nlocktime_options_menu_clears_locktime",
    amount: int = int(1e6),
) -> None:
    """Ensure toggling the nLocktime menu clears the configured locktime."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)
        shutter.save(main_window)
        qt_wallet = _setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name=wallet_name,
        )

        fund_wallet(qt_wallet=qt_wallet, amount=amount, faucet=faucet, qtbot=qtbot)
        qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
        creator = qt_wallet.uitx_creator
        creator.clear_ui()
        shutter.save(main_window)

        # Start from a clean UI: the advanced nLocktime option is disabled and no value is set.
        assert not creator.column_fee.action_set_nlocktime.isChecked()
        assert not creator.column_fee.nlocktime_group.isVisible()
        assert creator.column_fee.nlocktime() is None
        shutter.save(main_window)

        # Enable the option and set a timestamp-based locktime.
        creator.column_fee.action_set_nlocktime.setChecked(True)
        assert creator.column_fee.nlocktime_group.isVisible()
        custom_time = QDateTime.currentDateTime().addSecs(1200)
        creator.column_fee.nlocktime_group.set_mode(NLocktimeMode.DATE_TIME)
        creator.column_fee.nlocktime_group.time_edit.setDateTime(custom_time)
        assert creator.column_fee.nlocktime() == int(custom_time.toSecsSinceEpoch())
        shutter.save(main_window)

        # Move the date far into the future and confirm the warning bar is shown.
        far_future_time = QDateTime.currentDateTime().addYears(NLOCKTIME_FUTURE_YEARS + 1)
        creator.column_fee.nlocktime_group.time_edit.setDateTime(far_future_time)
        qtbot.waitUntil(lambda: creator.nlocktime_warning_label.isVisible(), timeout=10_000)
        shutter.save(main_window)

        # Switch to a far-future block height and confirm the warning remains visible.
        current_height = qt_wallet.wallet.get_height()
        blocks_per_year = 6 * 24 * 365
        far_future_height = min(
            LOCKTIME_THRESHOLD - 1, current_height + (blocks_per_year * (NLOCKTIME_FUTURE_YEARS + 1))
        )
        creator.column_fee.nlocktime_group.set_mode(NLocktimeMode.BLOCK_HEIGHT)
        creator.column_fee.nlocktime_group.height_spin.setValue(far_future_height)
        qtbot.waitUntil(lambda: creator.nlocktime_warning_label.isVisible(), timeout=10_000)
        shutter.save(main_window)

        # Restore the original custom time before toggling the option off.
        creator.column_fee.nlocktime_group.set_mode(NLocktimeMode.DATE_TIME)
        creator.column_fee.nlocktime_group.time_edit.setDateTime(custom_time)

        # Disable the option again; this should clear the locktime before creating the tx.
        custom_time_value = int(custom_time.toSecsSinceEpoch())
        creator.column_fee.action_set_nlocktime.setChecked(False)
        assert not creator.column_fee.nlocktime_group.isVisible()
        assert creator.column_fee.nlocktime() is None
        shutter.save(main_window)

        # Build a simple self-send so the created tx can be inspected in the viewer.
        recipient_box = creator.recipients.get_recipient_group_boxes()[0]
        recipient_box.address = str(qt_wallet.wallet.get_address().address)
        recipient_box.amount = amount // 2
        creator.column_fee.fee_group.spin_fee_rate.setValue(1.0)
        shutter.save(main_window)

        # Open the viewer and confirm the custom time locktime was not preserved.
        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
            creator.button_ok.click()

        viewer = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer, UITx_Viewer)
        locktime = viewer.extract_tx().lock_time()
        assert locktime != custom_time_value
        current_height = qt_wallet.wallet.get_height()
        assert viewer.column_fee.action_set_nlocktime.isChecked() == (locktime > current_height)
        if locktime > current_height:
            assert viewer.column_fee.nlocktime_group.isVisible()
        else:
            assert not viewer.column_fee.nlocktime_group.isVisible()
        shutter.save(main_window)


@pytest.mark.marker_qt_2
def test_nlocktime_creator_viewer_starting_height_stays_visible(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    wallet_name: str = "test_nlocktime_creator_viewer_starting_height",
    amount: int = int(1e6),
) -> None:
    """Ensure a starting-height nLocktime remains visible in creator and survives RBF."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)
        shutter.save(main_window)

        qt_wallet = _setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name=wallet_name,
        )

        fund_wallet(qt_wallet=qt_wallet, amount=amount, faucet=faucet, qtbot=qtbot)
        qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
        creator = qt_wallet.uitx_creator
        creator.clear_ui()
        shutter.save(main_window)

        # Enable nLocktime and set the starting block height from the start.
        creator.column_fee.action_set_nlocktime.setChecked(True)
        assert creator.column_fee.nlocktime_group.isVisible()
        qtbot.waitUntil(lambda: qt_wallet.wallet.get_height() > 0, timeout=10_000)
        current_height = qt_wallet.wallet.get_height()
        target_height = current_height
        creator.column_fee.nlocktime_group.set_mode(NLocktimeMode.BLOCK_HEIGHT)
        creator.column_fee.nlocktime_group.height_spin.setValue(target_height)
        assert int(creator.column_fee.nlocktime_group.height_spin.value()) == target_height
        shutter.save(main_window)

        # Create a simple self-send.
        recipient_box = creator.recipients.get_recipient_group_boxes()[0]
        recipient_box.address = str(qt_wallet.wallet.get_address().address)
        recipient_box.amount = amount // 2
        creator.column_fee.fee_group.spin_fee_rate.setValue(1.0)
        shutter.save(main_window)

        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
            creator.button_ok.click()

        viewer = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer, UITx_Viewer)
        locktime = viewer.extract_tx().lock_time()
        assert locktime == target_height
        if locktime > current_height:
            assert viewer.column_fee.action_set_nlocktime.isChecked()
            assert viewer.column_fee.nlocktime_group.isVisible()
            assert int(viewer.column_fee.nlocktime_group.height_spin.value()) == target_height
        else:
            assert not viewer.column_fee.action_set_nlocktime.isChecked()
            assert not viewer.column_fee.nlocktime_group.isVisible()
        shutter.save(main_window)

        # Sign and save locally so the tx is in the wallet, then broadcast to enable RBF.
        sign_tx(qtbot=qtbot, shutter=shutter, viewer=viewer, qt_wallet=qt_wallet)
        txid = str(viewer.extract_tx().compute_txid())
        viewer.save_local_tx()
        shutter.save(main_window)
        qtbot.waitUntil(lambda: qt_wallet.wallet.get_tx(txid) is not None, timeout=10_000)

        qt_wallet.signals.open_tx_like.emit(txid)
        qtbot.waitUntil(
            lambda: isinstance(main_window.tab_wallets.currentNode().data, UITx_Viewer),
            timeout=10_000,
        )
        viewer_local = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer_local, UITx_Viewer)
        shutter.save(main_window)

        broadcast_tx(qtbot=qtbot, shutter=shutter, viewer=viewer_local, qt_wallet=qt_wallet)
        shutter.save(main_window)

        qt_wallet.signals.open_tx_like.emit(txid)
        qtbot.waitUntil(
            lambda: isinstance(main_window.tab_wallets.currentNode().data, UITx_Viewer),
            timeout=10_000,
        )
        viewer_mempool = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer_mempool, UITx_Viewer)
        qtbot.waitUntil(lambda: viewer_mempool.button_rbf.isVisible(), timeout=10_000)
        shutter.save(main_window)

        # Enter RBF flow and ensure nLocktime stays visible with the same height.
        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
            viewer_mempool.button_rbf.click()
        creator_rbf = main_window.tab_wallets.currentNode().data
        assert isinstance(creator_rbf, UITx_Creator)
        assert int(creator_rbf.column_fee.nlocktime_group.height_spin.value()) == target_height
        shutter.save(main_window)

        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
            creator_rbf.button_ok.click()
        viewer_rbf = main_window.tab_wallets.currentNode().data
        assert isinstance(viewer_rbf, UITx_Viewer)
        assert viewer_rbf.extract_tx().lock_time() == target_height
        if target_height > current_height:
            assert int(viewer_rbf.column_fee.nlocktime_group.height_spin.value()) == target_height
        shutter.save(main_window)
