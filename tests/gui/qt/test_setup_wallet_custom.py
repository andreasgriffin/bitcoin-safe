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

import gc
import inspect
import logging
from datetime import datetime
from unittest.mock import patch

import bdkpython as bdk
import pytest
from bitcoin_usb.address_types import AddressTypes
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.block_change_signals import BlockChangesSignals
from bitcoin_safe.gui.qt.descriptor_edit import DescriptorExport
from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from tests.gui.qt.test_setup_wallet import close_wallet, save_wallet

from ...setup_fulcrum import Faucet
from .helpers import (
    CheckedDeletionContext,
    Shutter,
    close_wallet,
    do_modal_click,
    main_window_context,
    save_wallet,
)

logger = logging.getLogger(__name__)


def update_counter():
    """This method runs every 100ms."""
    gc.collect()


@pytest.mark.marker_qt_1
def test_custom_wallet_setup_custom_single_sig(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: UserConfig,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    wallet_name: str = "test_custom_wallet_setup_custom_single_sig",
    amount: int = int(1e6),
) -> None:
    """Test custom wallet setup custom single sig."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        QApplication.processEvents()
        shutter.save(main_window)

        button = main_window.welcome_screen.pushButton_custom_wallet

        def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
            """On wallet id dialog."""
            shutter.save(dialog)
            dialog.name_input.setText(wallet_name)
            shutter.save(dialog)

            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()
            shutter.save(main_window)

        do_modal_click(button, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        qt_protowallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert isinstance(qt_protowallet, QTProtoWallet)

        def test_block_change_signals() -> None:
            """Test block change signals."""
            with BlockChangesSignals([qt_protowallet.wallet_descriptor_ui]):
                assert qt_protowallet.wallet_descriptor_ui.spin_req.signalsBlocked()
            with BlockChangesSignals([qt_protowallet.wallet_descriptor_ui]):
                with BlockChangesSignals([qt_protowallet.wallet_descriptor_ui]):
                    assert qt_protowallet.wallet_descriptor_ui.spin_req.signalsBlocked()
                assert qt_protowallet.wallet_descriptor_ui.spin_req.signalsBlocked()

        def check_consistent() -> None:
            """Check consistent."""
            signers = qt_protowallet.wallet_descriptor_ui.spin_signers.value()
            qt_protowallet.wallet_descriptor_ui.spin_req.value()

            assert signers == qt_protowallet.wallet_descriptor_ui.keystore_uis.count()
            for i in range(signers):
                assert qt_protowallet.wallet_descriptor_ui.keystore_uis.tabText(
                    i
                ) == qt_protowallet.protowallet.signer_name(i)

            if qt_protowallet.protowallet.is_multisig():
                assert AddressTypes.p2wsh in [
                    qt_protowallet.wallet_descriptor_ui.comboBox_address_type.itemData(i)
                    for i in range(qt_protowallet.wallet_descriptor_ui.comboBox_address_type.count())
                ]
            else:
                assert AddressTypes.p2pkh in [
                    qt_protowallet.wallet_descriptor_ui.comboBox_address_type.itemData(i)
                    for i in range(qt_protowallet.wallet_descriptor_ui.comboBox_address_type.count())
                ]

        def page1() -> None:
            """Page1."""
            shutter.save(main_window)

            assert qt_protowallet.wallet_descriptor_ui.spin_req.value() == 3
            assert qt_protowallet.wallet_descriptor_ui.spin_signers.value() == 5
            assert (
                qt_protowallet.wallet_descriptor_ui.comboBox_address_type.currentData() == AddressTypes.p2wsh
            )
            assert qt_protowallet.wallet_descriptor_ui.spin_gap.value() == 20
            assert qt_protowallet.wallet_descriptor_ui.keystore_uis.count() == 5

            shutter.save(main_window)
            check_consistent()
            test_block_change_signals()

        page1()

        def change_to_single_sig() -> None:
            """Change to single sig."""
            assert qt_protowallet.protowallet.is_multisig()
            qt_protowallet.wallet_descriptor_ui.spin_req.setValue(1)
            assert qt_protowallet.wallet_descriptor_ui.spin_req.value() == 1

            # change to single sig
            qt_protowallet.wallet_descriptor_ui.spin_signers.setValue(1)
            assert qt_protowallet.wallet_descriptor_ui.spin_signers.value() == 1

            assert not qt_protowallet.protowallet.is_multisig()

            shutter.save(main_window)
            check_consistent()

        change_to_single_sig()

        def do_save_wallet() -> None:
            """Do save wallet."""
            key = list(qt_protowallet.wallet_descriptor_ui.keystore_uis.getAllTabData().values())[0]
            key.tabs_import_type.setCurrentWidget(key.tab_manual)

            shutter.save(main_window)

            if key.edit_seed.mnemonic_button:
                key.edit_seed.mnemonic_button.click()

            assert key.edit_seed.text()
            assert key.edit_xpub.text()
            assert key.edit_fingerprint.text()
            assert (
                key.edit_key_origin.text()
                == f"m/84h/{0 if bdk.Network.REGTEST == bdk.Network.BITCOIN else 1}h/0h"
            )

            shutter.save(main_window)

            save_wallet(
                test_config=test_config,
                wallet_name=wallet_name,
                save_button=qt_protowallet.wallet_descriptor_ui.button_box.button(
                    QDialogButtonBox.StandardButton.Apply
                ),
            )

            assert len(main_window.tab_wallets.root.child_nodes) == 1, "there should be only 1 wallet open"

        do_save_wallet()

        # get the new qt wallet
        qt_wallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert isinstance(qt_wallet, QTWallet)

        def do_all(qt_wallet: QTWallet):
            "any implicit reference to qt_wallet (including the function page_send) will create a cell refrence"

            def export_wallet_descriptor() -> None:
                """Export wallet descriptor."""

                def on_dialog(dialog: DescriptorExport):
                    """On dialog."""
                    shutter.save(dialog)
                    assert dialog.isVisible()
                    dialog.close()

                do_modal_click(
                    main_window.show_descriptor_export_window, on_dialog, qtbot, cls=DescriptorExport
                )

                shutter.save(main_window)

            export_wallet_descriptor()

            def check_that_it_is_in_recent_wallets() -> None:
                """Check that it is in recent wallets."""
                assert any(
                    [
                        (wallet_name in name)
                        for name in main_window.config.recently_open_wallets[main_window.config.network]
                    ]
                )

                shutter.save(main_window)

            check_that_it_is_in_recent_wallets()

            def switch_language() -> None:
                """Switch language."""
                main_window.language_chooser.switchLanguage("zh_CN")
                shutter.save(main_window)
                main_window.language_chooser.switchLanguage("en_US")
                shutter.save(main_window)

            switch_language()

        do_all(qt_wallet)
        QApplication.processEvents()
        wallet_name = qt_wallet.wallet.id

        def replace_descriptor() -> QTWallet:
            """Replace descriptor."""
            descriptor = "wpkh([e53c8089/84'/1'/0']tpubDDg6DvnYDvUcRW3a5HeHoFCpKZYDm4qhKP7ccArDsSBSvBjc4d7AMdijAbekZ4c7NaP1zKWZ4qgHYzbQ6gv2Sge4MWWp96zhhAkjvge22FW/<0;1>/*)#uduv7uyw"

            def on_fill_question(dialog: QMessageBox) -> None:
                # question 2
                """On fill question."""
                shutter.save(dialog)
                assert "Fill" in dialog.text()

                shutter.save(main_window)

                dialog.button(QMessageBox.StandardButton.Ok).click()

            do_modal_click(
                lambda: qt_wallet.wallet_descriptor_ui.edit_descriptor.edit.input_field.setText(descriptor),
                on_fill_question,
                qtbot,
                cls=QMessageBox,
            )

            def on_proceed_question(dialog: QMessageBox) -> None:
                # question 2
                """On proceed question."""
                shutter.save(dialog)
                assert "Proceeding will potentially change all wallet addresses" in dialog.text()

                shutter.save(main_window)

                button = dialog.buttons()[0]
                assert button.text() == "Proceed"
                button.click()

            with patch("bitcoin_safe.gui.qt.qt_wallet.Message") as mock_message:
                do_modal_click(
                    qt_wallet.wallet_descriptor_ui.button_box.button(
                        QDialogButtonBox.StandardButton.Apply
                    ).click,
                    on_proceed_question,
                    qtbot,
                    cls=QMessageBox,
                )

                QApplication.processEvents()

                assert mock_message.call_count == 1
                called_args, called_kwargs = mock_message.call_args
                assert "Backup saved to" in called_args[0]

            QApplication.processEvents()

            new_wallet: QTWallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
            assert new_wallet.wallet.get_addresses()[0] == "bcrt1qpmhcdhv2nyajtajpmwt74rqw7g38r6tyvtkctp"

            return new_wallet

        with CheckedDeletionContext(
            qt_wallet=qt_wallet, qtbot=qtbot, caplog=caplog, graph_directory=shutter.used_directory()
        ):
            new_wallet = replace_descriptor()
            del qt_wallet

        with CheckedDeletionContext(
            qt_wallet=new_wallet, qtbot=qtbot, caplog=caplog, graph_directory=shutter.used_directory()
        ):
            # if True:
            wallet_id = new_wallet.wallet.id
            del new_wallet

            close_wallet(
                shutter=shutter,
                test_config=test_config,
                wallet_name=wallet_id,
                qtbot=qtbot,
                main_window=main_window,
            )
            main_window.on_close_all_tx_tabs()

            shutter.save(main_window)

        # end
        shutter.save(main_window)
