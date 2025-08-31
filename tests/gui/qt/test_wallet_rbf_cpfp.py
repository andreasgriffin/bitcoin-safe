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
from datetime import datetime
from unittest.mock import patch

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.gui.qt.ui_tx.ui_tx_creator import UITx_Creator
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer

from ...non_gui.test_signers import test_seeds
from ...setup_fulcrum import Faucet
from .helpers import (
    CheckedDeletionContext,
    Shutter,
    broadcast_tx,
    close_wallet,
    do_modal_click,
    fund_wallet,
    main_window_context,
    save_wallet,
    sign_tx,
)

logger = logging.getLogger(__name__)


@pytest.mark.marker_qt_2
def test_rbf_cpfp_flow(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: UserConfig,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    wallet_name: str = "test_rbf_cpfp_flow",
    amount: int = int(1e6),
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window)
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"
        shutter.save(main_window)

        button = main_window.welcome_screen.pushButton_custom_wallet

        def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
            shutter.save(dialog)
            dialog.name_input.setText(wallet_name)
            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()
            shutter.save(main_window)

        do_modal_click(button, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        qt_protowallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert isinstance(qt_protowallet, QTProtoWallet)

        # switch to single sig and set seed
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

        def create_transaction_to_self(
            qt_wallet: QTWallet, addr: str, amount: int
        ) -> tuple[UITx_Viewer, str]:
            qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
            box = qt_wallet.uitx_creator.recipients.get_recipient_group_boxes()[0]
            box.address = addr
            box.amount = amount // 2
            qt_wallet.uitx_creator.column_fee.fee_group.spin_fee_rate.setValue(1.0)
            shutter.save(main_window)
            with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10000):
                qt_wallet.uitx_creator.button_ok.click()
            viewer = main_window.tab_wallets.currentNode().data
            assert isinstance(viewer, UITx_Viewer)
            return viewer, viewer.txid()

        def create_RBF_transaction(viewer: UITx_Viewer, qt_wallet: QTWallet) -> tuple[UITx_Viewer, str]:
            shutter.save(main_window)
            with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10000):
                viewer.button_rbf.click()
            shutter.save(main_window)
            creator_rbf = main_window.tab_wallets.currentNode().data
            assert isinstance(creator_rbf, UITx_Creator)
            assert creator_rbf.column_fee.fee_group.rbf_fee_label.isVisible()
            with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10000):
                creator_rbf.button_ok.click()
            shutter.save(main_window)
            viewer_rbf = main_window.tab_wallets.currentNode().data
            assert isinstance(viewer_rbf, UITx_Viewer)
            txid_rbf = viewer_rbf.txid()
            assert not viewer_rbf.column_fee.fee_group.rbf_fee_label.isVisible()
            assert not viewer_rbf.button_cpfp_tx.isVisible()
            assert not viewer_rbf.button_rbf.isVisible()

            sign_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer_rbf)
            with patch("bitcoin_safe.gui.qt.qt_wallet.question_dialog") as mock_message:
                mock_message.return_value = False

                broadcast_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer_rbf)
                mock_message.assert_called_once()

            assert not viewer_rbf.button_cpfp_tx.isVisible()
            assert not viewer_rbf.button_rbf.isVisible()
            return viewer_rbf, txid_rbf

        def create_CPFP_transaction(viewer_rbf: UITx_Viewer, qt_wallet: QTWallet) -> tuple[UITx_Viewer, str]:
            with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10000):
                viewer_rbf.button_cpfp_tx.click()
            shutter.save(main_window)
            creator_cpfp = main_window.tab_wallets.currentNode().data
            assert isinstance(creator_cpfp, UITx_Creator)
            creator_cpfp.column_fee.fee_group.spin_fee_rate.setValue(5.0)
            with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10000):
                creator_cpfp.button_ok.click()
            shutter.save(main_window)
            viewer_cpfp = main_window.tab_wallets.currentNode().data
            assert isinstance(viewer_cpfp, UITx_Viewer)
            assert viewer_cpfp.column_fee.fee_group.cpfp_fee_label.isVisible()
            txid_cpfp = viewer_cpfp.txid()

            sign_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer_cpfp)
            broadcast_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer_cpfp)

            return viewer_cpfp, txid_cpfp

        fund_wallet(qt_wallet=qt_wallet, amount=amount, qtbot=qtbot, faucet=faucet)
        address_info = qt_wallet.wallet.get_unused_category_address(category=None)
        viewer, txid_a = create_transaction_to_self(qt_wallet, str(address_info.address), amount)
        viewer.button_next.click()
        sign_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer)
        broadcast_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer)

        # focus viewer again
        qt_wallet.signals.open_tx_like.emit(txid_a)
        shutter.save(main_window)

        viewer_rbf, txid_rbf = create_RBF_transaction(viewer, qt_wallet)
        # focus viewer again
        qt_wallet.signals.open_tx_like.emit(txid_rbf)
        shutter.save(main_window)

        txids = [tx.txid for tx in qt_wallet.wallet.bdkwallet.list_transactions()]
        assert txid_a not in txids
        assert txid_rbf in txids
        viewer_cpfp, txid_cpfp = create_CPFP_transaction(viewer_rbf, qt_wallet)
        txids = [tx.txid for tx in qt_wallet.wallet.bdkwallet.list_transactions()]
        assert txid_cpfp in txids

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
