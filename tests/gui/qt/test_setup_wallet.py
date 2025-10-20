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
from unittest.mock import patch

import pytest
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.util import insert_invisible_spaces_for_wordwrap
from PyQt6 import QtGui
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.bitcoin_quick_receive import BitcoinQuickReceive
from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.util import MessageType
from bitcoin_safe.gui.qt.wizard import (
    BackupSeed,
    BuyHardware,
    DistributeSeeds,
    GenerateSeed,
    ImportXpubs,
    LabelBackup,
    ReceiveTest,
    SendTest,
    StickerTheHardware,
    TutorialStep,
    Wizard,
)
from tests.setup_fulcrum import Faucet

from ...non_gui.test_signers import test_seeds
from .helpers import (
    CheckedDeletionContext,
    Shutter,
    close_wallet,
    do_modal_click,
    get_called_args_message_box,
    main_window_context,
    save_wallet,
    sign_tx,
    type_text_in_edit,
)

logger = logging.getLogger(__name__)


def enter_text(text: str, widget: QWidget) -> None:
    """
    Simulates key-by-key text entry into a specified PyQt widget.

    :param text: The string of text to be entered into the widget.
    :param widget: The PyQt widget where the text will be entered.
    """
    for char in text:
        QTest.keyClick(widget, char)


@pytest.mark.marker_qt_1  # repeated gui tests let the RAM usage increase (unclear why the memory isnt freed), and to stay under the github VM limit, we split the tests
def test_wizard(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: UserConfig,
    bitcoin_core: Path,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    wallet_name="test_tutorial_wallet_setup",
    amount=int(1e6),
) -> None:  # bitcoin_core: Path,
    logger.debug(f"start test_tutorial_wallet_setup")
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(
        qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }"
    )
    shutter.create_symlink(test_config=test_config)
    logger.debug(f"shutter = {shutter}")
    with main_window_context(test_config=test_config) as main_window:
        logger.debug(f"(app, main_window) = {main_window}")
        QTest.qWaitForWindowExposed(main_window)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        w = main_window.welcome_screen.pushButton_singlesig

        def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
            shutter.save(dialog)
            dialog.name_input.setText(wallet_name)
            shutter.save(dialog)

            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()
            shutter.save(main_window)

        do_modal_click(w, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        qt_protowallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert isinstance(qt_protowallet, QTProtoWallet)
        wizard: Wizard = qt_protowallet.wizard

        def page1() -> None:
            shutter.save(main_window)
            step: BuyHardware = wizard.tab_generators[TutorialStep.buy]
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

        page1()

        def page_sticker() -> None:
            shutter.save(main_window)
            step: StickerTheHardware = wizard.tab_generators[TutorialStep.sticker]
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

        page_sticker()

        def page_generate() -> None:
            shutter.save(main_window)
            step: GenerateSeed = wizard.tab_generators[TutorialStep.generate]
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

        page_generate()

        def page_import() -> None:
            shutter.save(main_window)
            step: ImportXpubs = wizard.tab_generators[TutorialStep.import_xpub]

            # check that you cannot go further without import xpub
            def wrong_entry(dialog: QMessageBox) -> None:
                shutter.save(dialog)

                assert dialog.text() == "Please import the complete data for Signer 1!"
                dialog.button(QMessageBox.StandardButton.Ok).click()

            do_modal_click(step.button_create_wallet, wrong_entry, qtbot, cls=QMessageBox)

            # import xpub
            assert step.keystore_uis
            keystore = list(step.keystore_uis.getAllTabData().values())[0]
            keystore.tabs_import_type.setCurrentWidget(keystore.tab_manual)
            shutter.save(main_window)

            # # fingerprint
            # type_text_in_edit("0000", keystore.edit_fingerprint.input_field)
            # shutter.save(main_window)
            # assert "{ background-color: #ff6c54; }" in edit.input_field.styleSheet()

            # def wrong_entry_xpub_try_to_proceed(dialog: QMessageBox) -> None:
            #     shutter.save(dialog)
            #     assert dialog.text() == f"Please import the information from all hardware signers first"
            #     dialog.button(QMessageBox.StandardButton.Ok).click()

            # do_modal_click(step.button_create_wallet, wrong_entry_xpub_try_to_proceed, qtbot, cls=QMessageBox)
            # shutter.save(main_window)
            # check that inputting in the wrong field gives an error
            for edit, wrong_text, valid_text, error_message in [
                (
                    keystore.edit_xpub.input_field,
                    "tpub1111",
                    "tpubDDnGNapGEY6AZAdQbfRJgMg9fvz8pUBrLwvyvUqEgcUfgzM6zc2eVK4vY9x9L5FJWdX8WumXuLEDV5zDZnTfbn87vLe9XceCFwTu9so9Kks",
                    "Please import the complete data for Signer 1!",
                ),
                (
                    keystore.edit_fingerprint.input_field,
                    "000",
                    "a42c6dd3",
                    "Please import the complete data for Signer 1!",
                ),
            ]:
                type_text_in_edit(wrong_text, edit)
                shutter.save(main_window)
                assert "{ background-color: #ff6c54; }" in edit.styleSheet()

                # check that you cannot go further without import xpub
                def wrong_entry_xpub_try_to_proceed(dialog: QMessageBox) -> None:
                    shutter.save(dialog)
                    assert dialog.text() == error_message
                    dialog.button(QMessageBox.StandardButton.Ok).click()

                do_modal_click(
                    step.button_create_wallet, wrong_entry_xpub_try_to_proceed, qtbot, cls=QMessageBox
                )
                shutter.save(main_window)
                edit.clear()
                type_text_in_edit(valid_text, edit)

            # key_origin
            edit, wrong_text, valid_text, error_message = (
                keystore.edit_key_origin.input_field,
                "m/0h00",
                "m/84h/1h/0h",
                "Signer 1: ('Invalid BIP32 path', 'm/0h00')",
            )
            type_text_in_edit(wrong_text, edit)
            shutter.save(main_window)
            assert "{ background-color: #ff6c54; }" in edit.styleSheet()

            with patch("bitcoin_safe.gui.qt.main.Message") as mock_message:

                # check that you cannot go further without import xpub
                def wrong_entry_xpub_try_to_proceed(dialog: QMessageBox) -> None:
                    shutter.save(dialog)
                    assert dialog.text() == error_message
                    dialog.button(QMessageBox.StandardButton.Ok).click()

                do_modal_click(
                    step.button_create_wallet, wrong_entry_xpub_try_to_proceed, qtbot, cls=QMessageBox
                )

                QTest.qWait(200)

            shutter.save(main_window)
            edit.clear()
            type_text_in_edit(valid_text, edit)
            shutter.save(main_window)

            # correct entry
            for edit in [keystore.edit_xpub, keystore.edit_key_origin, keystore.edit_fingerprint]:
                edit.setText("")
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
                assert "background-color" not in keystore.edit_xpub.input_field.styleSheet()

            save_wallet(
                test_config=test_config,
                wallet_name=wallet_name,
                save_button=step.button_create_wallet,
            )

        page_import()

        ######################################################
        # now that the qt wallet is created i have to reload the
        qt_wallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert qt_wallet
        wizard = qt_wallet.wizard

        def do_all(qt_wallet: QTWallet):
            "any implicit reference to qt_wallet (including the function page_send) will create a cell refrence"

            def page_backup() -> None:
                shutter.save(main_window)
                step: BackupSeed = wizard.tab_generators[TutorialStep.backup_seed]
                with patch("bitcoin_safe.pdfrecovery.xdg_open_file") as mock_open:
                    assert step.custom_yes_button.isVisible()
                    step.custom_yes_button.click()
                    mock_open.assert_called_once()

                    temp_file = os.path.join(Path.home(), f"Seed backup of {wallet_name}.pdf")
                    assert Path(temp_file).exists()
                    # remove the file again
                    Path(temp_file).unlink()

            page_backup()

            def switch_language() -> None:
                main_window.language_chooser.switchLanguage("zh_CN")
                shutter.save(main_window)
                main_window.language_chooser.switchLanguage("en_US")
                shutter.save(main_window)

            switch_language()

            def page_receive() -> None:
                shutter.save(main_window)
                step: ReceiveTest = wizard.tab_generators[TutorialStep.receive]
                assert isinstance(step.quick_receive, BitcoinQuickReceive)
                address_with_spaces = step.quick_receive.group_boxes[0].label.text()
                assert address_with_spaces == insert_invisible_spaces_for_wordwrap(
                    "bcrt1q3qt0n3z69sds3u6zxalds3fl67rez4u2wm4hes", max_word_length=1
                )
                address = step.quick_receive.group_boxes[0].address
                assert address == "bcrt1q3qt0n3z69sds3u6zxalds3fl67rez4u2wm4hes"
                faucet.send(address, amount=amount)

                called_args_message_box = get_called_args_message_box(
                    "bitcoin_safe.gui.qt.wizard.Message",
                    step.check_button,
                    repeat_clicking_until_message_box_called=True,
                )
                assert str(called_args_message_box) == str(
                    (
                        "Balance = {amount}".format(
                            amount=Satoshis(amount, network=test_config.network).str_with_unit()
                        ),
                    )
                )
                assert not step.check_button.isVisible()
                assert step.next_button.isVisible()
                shutter.save(main_window)
                step.next_button.click()
                shutter.save(main_window)

            page_receive()

            def page_send() -> None:
                shutter.save(main_window)
                step: SendTest = wizard.tab_generators[TutorialStep.send]
                assert step.refs.floating_button_box.isVisible()
                assert step.refs.floating_button_box.button_create_tx.isVisible()
                assert not step.refs.floating_button_box.tutorial_button_prefill.isVisible()

                shutter.save(main_window)

                assert qt_wallet.uitx_creator.isVisible()
                box = qt_wallet.uitx_creator.recipients.get_recipient_group_boxes()[0]
                shutter.save(main_window)
                assert [recipient.address for recipient in qt_wallet.uitx_creator.recipients.recipients] == [
                    "bcrt1qmx7ke6j0amadeca65xqxpwh0utju5g3uka2sj5"
                ]
                assert box.address == "bcrt1qmx7ke6j0amadeca65xqxpwh0utju5g3uka2sj5"
                assert (
                    box.recipient_widget.address_edit.input_field.palette()
                    .color(QtGui.QPalette.ColorRole.Base)
                    .name()
                    == "#8af296"
                )
                fee_info = qt_wallet.uitx_creator.estimate_fee_info(
                    qt_wallet.uitx_creator.column_fee.fee_group.spin_fee_rate.value()
                )
                assert qt_wallet.uitx_creator.recipients.recipients[0].amount == amount - fee_info.fee_amount
                assert qt_wallet.uitx_creator.recipients.recipients[0].checked_max_amount

                assert step.refs.floating_button_box.button_create_tx.isVisible()
                step.refs.floating_button_box.button_create_tx.click()
                shutter.save(main_window)

            page_send()

            def page_sign() -> None:
                shutter.save(main_window)
                viewer = main_window.tab_wallets.currentNode().data
                assert isinstance(viewer, UITx_Viewer)
                assert [recipient.address for recipient in viewer.recipients.recipients] == [
                    "bcrt1qmx7ke6j0amadeca65xqxpwh0utju5g3uka2sj5"
                ]
                assert [recipient.label for recipient in viewer.recipients.recipients] == ["Send Test"]
                assert [recipient.amount for recipient in viewer.recipients.recipients] == [999890]
                assert viewer.fee_info
                assert round(viewer.fee_info.fee_rate(), 1) == 1.0
                assert not viewer.column_fee.fee_group.allow_edit
                assert viewer.column_fee.fee_group.spin_fee_rate.value() == 1.0
                assert viewer.column_fee.fee_group.cpfp_fee_label.isVisible()
                assert not viewer.column_fee.fee_group.approximate_fee_label.isVisible()

                sign_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer)

                with patch("bitcoin_safe.gui.qt.wizard.Message") as mock_message:
                    with qtbot.waitSignal(
                        main_window.signals.wallet_signals[qt_wallet.wallet.id].updated, timeout=10000
                    ):  # Timeout after 10 seconds
                        viewer.button_send.click()
                    qtbot.wait(10000)
                    mock_message.assert_called_with(
                        main_window.tr("All Send tests done successfully."), type=MessageType.Info
                    )

                # hist list
                shutter.save(main_window)

            page_sign()

            def page10() -> None:
                shutter.save(main_window)

                step: DistributeSeeds = wizard.tab_generators[TutorialStep.distribute]
                assert step.buttonbox_buttons[0].isVisible()
                step.buttonbox_buttons[0].click()

                shutter.save(main_window)

            page10()

            def page11() -> None:
                shutter.save(main_window)

                step: LabelBackup = wizard.tab_generators[TutorialStep.sync]
                assert step.buttonbox_buttons[0].isVisible()
                step.buttonbox_buttons[0].click()

                shutter.save(main_window)

            page11()

        do_all(qt_wallet)
        del wizard

        def check_address_balances():
            wallet = qt_wallet.wallet

            # check that spent utxos do not count into the address balance
            addresses = wallet.get_addresses()
            assert addresses
            total = 0
            for address in addresses:
                total += wallet.get_addr_balance(address).total

            assert total
            assert total == wallet.get_balance().total

        check_address_balances()

        def check_utxo_list():
            qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
            qt_wallet.uitx_creator.column_inputs.checkBox_manual_coin_select.setChecked(True)
            QCoreApplication.processEvents()

            utxo_list = qt_wallet.uitx_creator.utxo_list

            total = 0
            model = utxo_list._source_model
            # Select rows with an ID in id_list
            for row in range(model.rowCount()):
                amount = model.data(
                    model.index(row, utxo_list.Columns.AMOUNT), role=MyItemDataRole.ROLE_CLIPBOARD_DATA
                )
                total += amount

            assert total
            assert total == qt_wallet.wallet.get_balance().total

        check_utxo_list()

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
            main_window.on_close_all_tx_tabs()

            shutter.save(main_window)

        def check_that_it_is_in_recent_wallets() -> None:
            assert any(
                [
                    (wallet_name in name)
                    for name in main_window.config.recently_open_wallets[main_window.config.network]
                ]
            )

            shutter.save(main_window)

        check_that_it_is_in_recent_wallets()

        # end
        shutter.save(main_window)
