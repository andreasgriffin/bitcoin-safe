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
from datetime import datetime
from pathlib import Path
from time import sleep
from unittest.mock import patch

from PyQt6 import QtGui
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialogButtonBox, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.keystore_ui import SignerUI
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.gui.qt.tutorial import (
    BackupSeed,
    BuyHardware,
    DistributeSeeds,
    GenerateSeed,
    ImportXpubs,
    ReceiveTest,
    SendTest,
    TutorialStep,
    ValidateBackup,
    WalletSteps,
)
from bitcoin_safe.gui.qt.tx_signing_steps import HorizontalImporters
from bitcoin_safe.gui.qt.ui_tx import UITx_Viewer
from bitcoin_safe.logging_setup import setup_logging  # type: ignore
from bitcoin_safe.util import Satoshis

from ...test_setup_bitcoin_core import Faucet, bitcoin_core, faucet  # type: ignore
from ...test_signers import test_seeds
from .test_helpers import (  # type: ignore
    Shutter,
    assert_message_box,
    close_wallet,
    do_modal_click,
    get_tab_with_title,
    get_widget_top_level,
    main_window_context,
    save_wallet,
    test_config,
    test_start_time,
)

logger = logging.getLogger(__name__)


def test_tutorial_wallet_setup(
    qtbot: QtBot,
    test_start_time: datetime,
    test_config: UserConfig,
    bitcoin_core: Path,
    faucet: Faucet,
    wallet_name="test_tutorial_wallet_setup",
    amount=int(1e6),
) -> None:  # bitcoin_core: Path,
    logger.debug(f"start test_tutorial_wallet_setup")
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{test_start_time}_{inspect.getframeinfo(frame).function    }")
    shutter.create_symlink(test_config=test_config)
    logger.debug(f"shutter = {shutter}")
    with main_window_context(test_config=test_config) as (app, main_window):
        logger.debug(f"(app, main_window) = {(app, main_window)}")
        QTest.qWaitForWindowExposed(main_window)  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        w = main_window.welcome_screen.pushButton_singlesig

        def on_wallet_id_dialog(dialog: WalletIdDialog):
            shutter.save(dialog)
            dialog.name_input.setText(wallet_name)
            shutter.save(dialog)

            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()
            shutter.save(main_window)

        do_modal_click(w, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        w = get_tab_with_title(main_window.tab_wallets, title=wallet_name)
        qt_proto_wallet = main_window.tab_wallets.get_data_for_tab(w)
        assert isinstance(qt_proto_wallet, QTProtoWallet)
        wallet_steps: WalletSteps = qt_proto_wallet.wallet_steps

        def page1():
            shutter.save(main_window)
            step: BuyHardware = wallet_steps.tab_generators[TutorialStep.buy]
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

        page1()

        def page2():
            shutter.save(main_window)
            step: GenerateSeed = wallet_steps.tab_generators[TutorialStep.generate]
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

        page2()

        def page3():
            shutter.save(main_window)
            step: ImportXpubs = wallet_steps.tab_generators[TutorialStep.import_xpub]

            # check that you cannot go further without import xpub
            def wrong_entry(dialog: QMessageBox):
                shutter.save(dialog)

                assert (
                    dialog.text() == "Please import the public key information from the hardware wallet first"
                )
                dialog.button(QMessageBox.StandardButton.Ok).click()

            do_modal_click(step.button_create_wallet, wrong_entry, qtbot, cls=QMessageBox)

            # import xpub
            keystore = step.keystore_uis.keystore_uis[0]
            keystore.tabs_import_type.setCurrentWidget(keystore.tab_manual)
            shutter.save(main_window)

            # check that inputting in the wrong field gives an error
            for edit in [keystore.edit_xpub, keystore.edit_key_origin, keystore.edit_fingerprint]:
                edit.setText(test_seeds[0])
                shutter.save(main_window)
                assert "{ background-color: #ff6c54; }" in edit.input_field.styleSheet()

                # check that you cannot go further without import xpub
                def wrong_entry_xpub_try_to_proceed(dialog: QMessageBox):
                    shutter.save(dialog)
                    assert dialog.text() == f"{test_seeds[0]} is not a valid public xpub"
                    dialog.button(QMessageBox.StandardButton.Ok).click()

                do_modal_click(
                    step.button_create_wallet, wrong_entry_xpub_try_to_proceed, qtbot, cls=QMessageBox
                )
                shutter.save(main_window)

            # correct entry
            keystore.edit_seed.setText(test_seeds[0])
            shutter.save(main_window)
            assert keystore.edit_fingerprint.text().lower() == "5aa39a43"
            assert (
                keystore.edit_xpub.text()
                == "tpubDD2ww8jti4Xc8vkaJH2yC1r7C9TVb9bG3kTi6BFm5w3aAZmtFHktK6Mv2wfyBvSPqV9QeH1QXrmHzabuNh1sgRtAsUoG7dzVjc9WvGm78PD"
            )
            assert keystore.edit_key_origin.text() == "m/84h/1h/0h"
            assert keystore.edit_seed.text() == test_seeds[0]

            keystore.textEdit_description.setText("test description")

            # check no error warning
            for edit in [
                keystore.edit_seed,
                keystore.edit_xpub,
                keystore.edit_key_origin,
                keystore.edit_fingerprint,
            ]:
                assert keystore.edit_xpub.input_field.styleSheet() == ""

            save_wallet(
                shutter=shutter,
                test_config=test_config,
                wallet_name=wallet_name,
                qtbot=qtbot,
                save_button=step.button_create_wallet,
            )

        page3()

        ######################################################
        # now that the qt wallet is created i have to reload the
        w = get_tab_with_title(main_window.tab_wallets, title=wallet_name)
        qt_wallet = main_window.get_qt_wallet(tab=w)
        assert qt_wallet
        wallet_steps = qt_wallet.wallet_steps

        def page4():
            shutter.save(main_window)
            step: BackupSeed = wallet_steps.tab_generators[TutorialStep.backup_seed]
            with patch("webbrowser.open_new_tab") as mock_open:
                assert step.custom_yes_button.isVisible()
                step.custom_yes_button.click()
                mock_open.assert_called_once()

                temp_file = os.path.join(Path.home(), f"Descriptor and seed backup of {wallet_name}.pdf")
                assert Path(temp_file).exists()
                # remove the file again
                Path(temp_file).unlink()

        page4()

        def page5():
            shutter.save(main_window)
            step: ValidateBackup = wallet_steps.tab_generators[TutorialStep.validate_backup]
            assert step.custom_yes_button.isVisible()
            step.custom_yes_button.click()

        page5()

        def page6():
            shutter.save(main_window)
            step: ReceiveTest = wallet_steps.tab_generators[TutorialStep.receive]
            assert step.quick_receive
            address = step.quick_receive.text_edit.input_field.toPlainText()
            assert address == "bcrt1q3qt0n3z69sds3u6zxalds3fl67rez4u2wm4hes"
            faucet.send(address, amount=amount)

            assert_message_box(
                step.check_button,
                "Information",
                f"Received {Satoshis(amount, test_config.network).str_with_unit()}",
            )
            assert not step.check_button.isVisible()
            assert step.next_button.isVisible()
            shutter.save(main_window)
            step.next_button.click()
            shutter.save(main_window)

        page6()

        def page7():
            shutter.save(main_window)
            step: SendTest = wallet_steps.tab_generators[TutorialStep.send]
            assert step.refs.floating_button_box.isVisible()
            assert step.refs.floating_button_box.tutorial_button_prefill.isVisible()

            step.refs.floating_button_box.tutorial_button_prefill.click()
            shutter.save(main_window)

            assert qt_wallet.tabs.currentWidget() == qt_wallet.send_tab
            box = qt_wallet.uitx_creator.recipients.get_recipient_group_boxes()[0]
            shutter.save(main_window)
            assert [recipient.address for recipient in qt_wallet.uitx_creator.recipients.recipients] == [
                "bcrt1qmx7ke6j0amadeca65xqxpwh0utju5g3uka2sj5"
            ]
            assert box.address_line_edit.text() == "bcrt1qmx7ke6j0amadeca65xqxpwh0utju5g3uka2sj5"
            assert (
                box.address_line_edit.input_field.palette().color(QtGui.QPalette.ColorRole.Base).name()
                == "#8af296"
            )
            assert qt_wallet.uitx_creator.recipients.recipients[0].amount == amount
            assert qt_wallet.uitx_creator.recipients.recipients[0].checked_max_amount

            assert step.refs.floating_button_box.button_create_tx.isVisible()
            step.refs.floating_button_box.button_create_tx.click()
            shutter.save(main_window)

        page7()

        def page8():
            shutter.save(main_window)
            viewer = main_window.tab_wallets.getCurrentTabData()
            assert isinstance(viewer, UITx_Viewer)
            assert [recipient.address for recipient in viewer.recipients.recipients] == [
                "bcrt1qmx7ke6j0amadeca65xqxpwh0utju5g3uka2sj5"
            ]
            assert [recipient.label for recipient in viewer.recipients.recipients] == ["Send Test"]
            assert [recipient.amount for recipient in viewer.recipients.recipients] == [999890]
            assert viewer.fee_info
            assert round(viewer.fee_info.fee_rate(), 1) == 2.7
            assert not viewer.fee_group.allow_edit
            assert viewer.fee_group.spin_fee_rate.value() == 2.7
            assert viewer.fee_group.approximate_fee_label.isVisible()

            assert viewer.button_next.isVisible()
            viewer.button_next.click()
            shutter.save(main_window)

            assert viewer.tx_singning_steps
            importers = list(viewer.tx_singning_steps.signature_importer_dict.values())[0]
            assert [importer.__class__.__name__ for importer in importers] == [
                "SignatureImporterWallet",
                "SignatureImporterQR",
                "SignatureImporterFile",
                "SignatureImporterClipboard",
                "SignatureImporterUSB",
            ]
            assert viewer.tx_singning_steps
            widget = viewer.tx_singning_steps.stacked_widget.currentWidget()
            assert isinstance(widget, HorizontalImporters)
            assert isinstance(widget.group_seed.data, SignerUI)
            for button in widget.group_seed.data.findChildren(QPushButton):
                assert button.text() == "Sign with mnemonic seed"
                assert button.isVisible()
                button.click()

            # send it away now
            shutter.save(main_window)

            assert viewer.button_send.isVisible()
            viewer.button_send.click()

            # hist list
            shutter.save(main_window)

        page8()

        def page9():
            shutter.save(main_window)
            assert isinstance(main_window.tab_wallets.getCurrentTabData(), QTWallet)

            step: SendTest = wallet_steps.tab_generators[TutorialStep.send]
            assert step.refs.floating_button_box.isVisible()
            assert step.refs.floating_button_box.button_yes_it_is_in_hist.isVisible()

            # because updating the cache is threaded by default, I have to force a nonthreaded update
            qt_wallet.refresh_caches_and_ui_lists(threaded=False)

            assert len(qt_wallet.wallet.bdkwallet.list_transactions()) == 2
            assert len(qt_wallet.wallet.sorted_delta_list_transactions()) == 2

            assert step.refs.floating_button_box.button_yes_it_is_in_hist.isVisible()
            step.refs.floating_button_box.button_yes_it_is_in_hist.click()
            shutter.save(main_window)

        page9()

        def page10():
            shutter.save(main_window)

            step: DistributeSeeds = wallet_steps.tab_generators[TutorialStep.distribute]
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

            shutter.save(main_window)

        page10()

        # end
        shutter.save(main_window)
        sleep(2)
