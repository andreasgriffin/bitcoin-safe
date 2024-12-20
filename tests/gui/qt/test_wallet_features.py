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
import os
import tempfile
from datetime import datetime
from pathlib import Path
from time import sleep
from unittest.mock import patch

import bdkpython as bdk
from bitcoin_qr_tools.gui.bitcoin_video_widget import BitcoinVideoWidget
from bitcoin_usb.address_types import AddressTypes
from bitcoin_usb.tool_gui import ToolGui
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.about_dialog import LicenseDialog
from bitcoin_safe.gui.qt.block_change_signals import BlockChangesSignals
from bitcoin_safe.gui.qt.descriptor_edit import DescriptorExport
from bitcoin_safe.gui.qt.dialog_import import ImportDialog
from bitcoin_safe.gui.qt.dialogs import PasswordCreation, WalletIdDialog
from bitcoin_safe.gui.qt.network_settings.main import NetworkSettingsUI
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.gui.qt.register_multisig import RegisterMultisigInteractionWidget
from bitcoin_safe.hardware_signers import DescriptorQrExportTypes
from bitcoin_safe.logging_setup import setup_logging  # type: ignore
from tests.gui.qt.test_setup_wallet import close_wallet, get_tab_with_title, save_wallet

from ...non_gui.test_signers import test_seeds
from ...test_helpers import test_config  # type: ignore
from ...test_setup_bitcoin_core import Faucet, bitcoin_core, faucet  # type: ignore
from .test_helpers import (  # type: ignore
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


def test_wallet_features_multisig(
    qapp: QApplication,
    qtbot: QtBot,
    test_start_time: datetime,
    test_config: UserConfig,
    bitcoin_core: Path,
    faucet: Faucet,
    wallet_name: str = "test_custom_wallet_setup_custom_single_sig2",
    amount: int = int(1e6),
) -> None:  # bitcoin_core: Path,
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{test_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"
        assert main_window.notification_bar_testnet.isVisible()

        shutter.save(main_window)

        button = main_window.welcome_screen.pushButton_custom_wallet

        def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
            shutter.save(dialog)
            dialog.name_input.setText(wallet_name)
            shutter.save(dialog)

            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()
            shutter.save(main_window)

        do_modal_click(button, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        w = get_tab_with_title(main_window.tab_wallets, title=wallet_name)
        qt_proto_wallet = main_window.tab_wallets.get_data_for_tab(w)
        assert isinstance(qt_proto_wallet, QTProtoWallet)

        def test_block_change_signals() -> None:
            with BlockChangesSignals([qt_proto_wallet.wallet_descriptor_ui.tab]):
                assert qt_proto_wallet.wallet_descriptor_ui.spin_req.signalsBlocked()
            with BlockChangesSignals([qt_proto_wallet.wallet_descriptor_ui.tab]):
                with BlockChangesSignals([qt_proto_wallet.wallet_descriptor_ui.tab]):
                    assert qt_proto_wallet.wallet_descriptor_ui.spin_req.signalsBlocked()
                assert qt_proto_wallet.wallet_descriptor_ui.spin_req.signalsBlocked()

        def check_consistent() -> None:
            signers = qt_proto_wallet.wallet_descriptor_ui.spin_signers.value()
            qt_proto_wallet.wallet_descriptor_ui.spin_req.value()

            assert signers == qt_proto_wallet.wallet_descriptor_ui.keystore_uis.count()
            for i in range(signers):
                assert qt_proto_wallet.wallet_descriptor_ui.keystore_uis.tabText(
                    i
                ) == qt_proto_wallet.protowallet.signer_name(i)

            if qt_proto_wallet.protowallet.is_multisig():
                assert AddressTypes.p2wsh in [
                    qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.itemData(i)
                    for i in range(qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.count())
                ]
            else:
                assert AddressTypes.p2pkh in [
                    qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.itemData(i)
                    for i in range(qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.count())
                ]

        def page1() -> None:
            shutter.save(main_window)

            assert qt_proto_wallet.wallet_descriptor_ui.spin_req.value() == 3
            assert qt_proto_wallet.wallet_descriptor_ui.spin_signers.value() == 5
            assert (
                qt_proto_wallet.wallet_descriptor_ui.comboBox_address_type.currentData() == AddressTypes.p2wsh
            )
            assert qt_proto_wallet.wallet_descriptor_ui.spin_gap.value() == 20
            assert qt_proto_wallet.wallet_descriptor_ui.keystore_uis.count() == 5

            shutter.save(main_window)
            check_consistent()
            test_block_change_signals()

        page1()

        def set_simple_multisig() -> None:
            assert qt_proto_wallet.protowallet.is_multisig()
            qt_proto_wallet.wallet_descriptor_ui.spin_req.setValue(1)
            assert qt_proto_wallet.wallet_descriptor_ui.spin_req.value() == 1

            # change to single sig
            qt_proto_wallet.wallet_descriptor_ui.spin_signers.setValue(2)
            assert qt_proto_wallet.wallet_descriptor_ui.spin_signers.value() == 2

            assert qt_proto_wallet.protowallet.is_multisig()

            shutter.save(main_window)
            check_consistent()

        set_simple_multisig()

        def set_mnemonic(index: int) -> None:
            key = list(qt_proto_wallet.wallet_descriptor_ui.keystore_uis.getAllTabData().values())[index]
            key.tabs_import_type.setCurrentWidget(key.tab_manual)

            shutter.save(main_window)

            key.edit_seed.setText(test_seeds[index])

            assert key.edit_seed.text()
            assert key.edit_xpub.text()
            assert key.edit_fingerprint.text()
            assert (
                key.edit_key_origin.text()
                == f"m/48h/{0 if bdk.Network.REGTEST==bdk.Network.BITCOIN else 1}h/0h/2h"
            )

            shutter.save(main_window)

        def do_save_wallet() -> None:
            set_mnemonic(0)
            set_mnemonic(1)

            wallet_file = save_wallet(
                test_config=test_config,
                wallet_name=wallet_name,
                save_button=qt_proto_wallet.wallet_descriptor_ui.button_box.button(
                    QDialogButtonBox.StandardButton.Apply
                ),
            )

            assert wallet_file.exists()
            assert main_window.tab_wallets.count() == 1, "there should be only 1 wallet open"

        do_save_wallet()

        # get the new qt wallet
        qt_wallet = main_window.tab_wallets.get_data_for_tab(
            get_tab_with_title(main_window.tab_wallets, title=wallet_name)
        )
        assert isinstance(qt_wallet, QTWallet)

        shutter.save(main_window)
        # check wallet address
        assert (
            qt_wallet.wallet.get_addresses()[0]
            == "bcrt1qklm7yyvyu2av4f35ve6tm8mpn6mkr8e3dpjd3jp9vn77vu670g7qu9cznl"
        )

        ##  from here starts testing features

        wallet_name = wallet_name + " new"

        def menu_action_rename_wallet() -> None:
            def callback(dialog: WalletIdDialog) -> None:
                shutter.save(dialog)
                dialog.name_input.setText(wallet_name)
                shutter.save(dialog)

                dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()
                shutter.save(main_window)

            do_modal_click(main_window.menu_action_rename_wallet, callback, qtbot, cls=WalletIdDialog)

        menu_action_rename_wallet()

        def menu_action_change_password() -> None:
            with patch("bitcoin_safe.gui.qt.qt_wallet.Message") as mock_message:

                def callback(dialog: PasswordCreation) -> None:
                    shutter.save(dialog)
                    dialog.password_input1.setText("new password")
                    dialog.password_input2.setText("new password")
                    shutter.save(dialog)

                    shutter.save(main_window)
                    dialog.submit_button.click()

                do_modal_click(main_window.menu_action_change_password, callback, qtbot, cls=PasswordCreation)

                QTest.qWait(200)

                # Inspect the call arguments for each call
                calls = mock_message.call_args_list

                first_call_args = calls[0][0]  # args of the first call
                assert first_call_args == ("Wallet saved",)

        menu_action_change_password()

        def menu_action_export_pdf() -> None:
            with patch("bitcoin_safe.pdfrecovery.xdg_open_file") as mock_open:
                main_window.menu_action_export_pdf.trigger()

                mock_open.assert_called_once()

                temp_file = os.path.join(Path.home(), f"Seed backup of {wallet_name}.pdf")
                assert Path(temp_file).exists()
                # remove the file again
                Path(temp_file).unlink()

        menu_action_export_pdf()

        def menu_action_export_descriptor() -> None:
            def callback(dialog: DescriptorExport) -> None:
                shutter.save(dialog)
                dialog.close()

            do_modal_click(main_window.menu_action_export_descriptor, callback, qtbot, cls=DescriptorExport)

        menu_action_export_descriptor()

        def menu_action_register_multisig() -> None:
            def callback(dialog: RegisterMultisigInteractionWidget) -> None:
                shutter.save(dialog)

                with tempfile.TemporaryDirectory() as temp_dir:
                    # export qr gifs
                    for action in dialog.export_qr_widget.button_file._menu.actions():
                        # export as file
                        filename = (
                            Path(temp_dir) / f"file_{action.text()}.t"
                        )  # check that it also works with incomplete extensions
                        with patch("bitcoin_safe.gui.qt.export_data.save_file_dialog") as mock_dialog:
                            mock_dialog.return_value = str(filename)
                            action.trigger()

                            mock_dialog.assert_called_once()
                        assert filename.exists()

                    # export qr gifs
                    assert dialog.export_qr_widget
                    for i in reversed(
                        range(dialog.export_qr_widget.combo_qr_type.count())
                    ):  # reversed to it always has to set the widget to trigger signal_set_qr_images
                        text = dialog.export_qr_widget.combo_qr_type.itemText(i)
                        basename = (
                            f"file_{text}.png"
                            if text.startswith(DescriptorQrExportTypes.text.display_name)
                            else f"file_{text}.gif"
                        )
                        filename = Path(temp_dir) / basename
                        with patch("bitcoin_safe.gui.qt.export_data.save_file_dialog") as mock_dialog:
                            mock_dialog.return_value = str(filename)
                            # set the qr code
                            with qtbot.waitSignal(
                                dialog.export_qr_widget.signal_set_qr_images, timeout=5000
                            ) as blocker:
                                dialog.export_qr_widget.combo_qr_type.setCurrentIndex(i)
                            dialog.export_qr_widget.button_save_qr.click()

                            mock_dialog.assert_called_once()
                        assert filename.exists()

                dialog.export_qr_widget.close()
                dialog.close()

            do_modal_click(
                main_window.menu_action_register_multisig,
                callback,
                qtbot,
                cls=RegisterMultisigInteractionWidget,
            )

        menu_action_register_multisig()

        def menu_action_open_hwi_manager() -> None:
            def callback(dialog: ToolGui) -> None:
                shutter.save(dialog)
                dialog.close()

            do_modal_click(
                main_window.menu_action_open_hwi_manager,
                callback,
                qtbot,
                cls=ToolGui,
            )

        menu_action_open_hwi_manager()

        def menu_action_open_tx_from_str() -> None:
            def callback(dialog: ImportDialog) -> None:
                shutter.save(dialog)
                dialog.close()

            do_modal_click(
                main_window.menu_action_open_tx_from_str,
                callback,
                qtbot,
                cls=ImportDialog,
            )

        menu_action_open_tx_from_str()

        def menu_action_load_tx_from_qr() -> None:
            def callback(dialog: BitcoinVideoWidget) -> None:
                shutter.save(dialog)
                dialog.close()

            do_modal_click(
                main_window.menu_action_load_tx_from_qr,
                callback,
                qtbot,
                cls=BitcoinVideoWidget,
            )

        menu_action_load_tx_from_qr()

        def menu_action_network_settings() -> None:
            def callback(dialog: NetworkSettingsUI) -> None:
                shutter.save(dialog)
                dialog.close()

            do_modal_click(
                main_window.menu_action_network_settings,
                callback,
                qtbot,
                cls=NetworkSettingsUI,
            )

        menu_action_network_settings()

        def menu_action_check_update() -> None:
            main_window.menu_action_check_update.trigger()
            shutter.save(main_window)
            assert main_window.update_notification_bar.isVisible()

            with qtbot.waitSignal(
                main_window.update_notification_bar.signal_on_success, timeout=10000
            ):  # Timeout after 10 seconds
                main_window.update_notification_bar.check()

            assert main_window.update_notification_bar.assets

        menu_action_check_update()

        def menu_action_license() -> None:
            def callback(dialog: LicenseDialog) -> None:
                shutter.save(dialog)
                dialog.close()

            do_modal_click(
                main_window.menu_action_license,
                callback,
                qtbot,
                cls=LicenseDialog,
            )

        menu_action_license()

        def switch_language() -> None:
            main_window.language_chooser.switchLanguage("zh_CN")
            shutter.save(main_window)
            main_window.language_chooser.switchLanguage("en_US")
            shutter.save(main_window)

        switch_language()

        # end
        shutter.save(main_window)
        sleep(2)
