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
import logging
import platform
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import bdkpython as bdk
import platformdirs
import pytest
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialogButtonBox, QWidget
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.bitcoin_quick_receive import BitcoinQuickReceive
from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
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
from tests.faucet import Faucet

from ...helpers import TestConfig
from ...non_gui.test_signers import test_seeds
from ...util import wait_for_sync
from .helpers import (
    CheckedDeletionContext,
    Shutter,
    close_wallet,
    do_modal_click,
    get_called_args_message_box,
    main_window_context,
    running_on_github,
    save_wallet,
    sign_tx,
)

logger = logging.getLogger(__name__)


def enter_text(text: str, widget: QWidget) -> None:
    """Simulates key-by-key text entry into a specified PyQt widget.

    :param text: The string of text to be entered into the widget.
    :param widget: The PyQt widget where the text will be entered.
    """
    for char in text:
        QTest.keyClick(widget, char)


@pytest.mark.marker_qt_1  # repeated gui tests let the RAM usage increase (unclear why the memory isnt freed), and to stay under the github VM limit, we split the tests
def test_wizard_multisig(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    backend: str,
    wallet_name: str = "test_wizard_multisig",
    amount: int = int(1e6),
) -> None:  # bitcoin_core: Path,
    """Test wizard."""
    logger.debug("start test_wizard")
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)
    logger.debug(f"shutter = {shutter}")
    with main_window_context(test_config=test_config) as main_window:
        logger.debug(f"(app, main_window) = {main_window}")
        # Wait for the main window to render before interacting.
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        w = main_window.welcome_screen.pushButton_multisig

        def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
            """On wallet id dialog."""
            # Provide a deterministic wallet name in the modal.
            shutter.save(dialog)
            dialog.name_input.setText(wallet_name)
            shutter.save(dialog)

            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()
            shutter.save(main_window)

        do_modal_click(w, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        # Resolve the proto wallet and wizard flow.
        qt_protowallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert isinstance(qt_protowallet, QTProtoWallet)
        wizard = qt_protowallet.wizard
        assert isinstance(wizard, Wizard)

        def page1(wizard: Wizard) -> None:
            """Page1."""
            shutter.save(main_window)
            step = wizard.tab_generators[TutorialStep.buy]
            assert isinstance(step, BuyHardware)
            # Advance from the "buy hardware" page.
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

        page1(wizard)

        def page_sticker(wizard: Wizard) -> None:
            """Page sticker."""
            shutter.save(main_window)
            step: StickerTheHardware = wizard.tab_generators[TutorialStep.sticker]
            # Advance from the sticker page.
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

        page_sticker(wizard)

        def page_generate(wizard: Wizard) -> None:
            """Page generate."""
            shutter.save(main_window)
            step: GenerateSeed = wizard.tab_generators[TutorialStep.generate]
            # Advance from the seed generation page.
            assert step.buttonbox_buttons[0].isVisible()
            step.buttonbox_buttons[0].click()

        page_generate(wizard)

        def page_import(wizard: Wizard) -> None:
            """Page import."""
            shutter.save(main_window)
            step: ImportXpubs = wizard.tab_generators[TutorialStep.import_xpub]

            assert step.keystore_uis
            seeds_iter = iter(test_seeds if isinstance(test_seeds, list) else test_seeds.splitlines())
            # fill all keystores with seeds; rely on auto-derivation for fingerprints/xpubs
            for keystore in step.keystore_uis.getAllTabData().values():
                keystore.tabs_import_type.setCurrentWidget(keystore.tab_manual)
                keystore.edit_seed.setText(next(seeds_iter))
                shutter.save(main_window)

            if platform.system() == "Darwin" and running_on_github():

                def all_signers_ready() -> bool:
                    for keystore in step.keystore_uis.getAllTabData().values():
                        try:
                            derived = keystore.get_ui_values_as_keystore()
                        except Exception:
                            return False
                        if not derived.fingerprint:
                            return False
                        if not derived.xpub:
                            return False
                    return True

                qtbot.waitUntil(all_signers_ready, timeout=30_000)

            # Save the wallet once all seeds have been entered.
            save_wallet(
                test_config=test_config,
                wallet_name=wallet_name,
                save_button=step.button_create_wallet,
            )

        page_import(wizard)

        ######################################################
        # Now that the wallet is created, reload from the wallet tree.
        qt_wallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert isinstance(qt_wallet, QTWallet)
        wizard = qt_wallet.wizard
        assert isinstance(wizard, Wizard)

        def do_all(qt_wallet: QTWallet) -> None:
            # Keep all operations in one scope to avoid lingering references to qt_wallet.

            wizard = qt_wallet.wizard
            assert isinstance(wizard, Wizard)

            def page_backup() -> None:
                """Page backup."""
                shutter.save(main_window)
                step = wizard.tab_generators[TutorialStep.backup_seed]
                assert isinstance(step, BackupSeed)
                # Ensure back navigation is disabled and open the PDF backup.
                assert not step.button_previous.isEnabled()
                assert not step.custom_cancel_button.isEnabled()
                with patch("bitcoin_safe.pdfrecovery.xdg_open_file") as mock_open:
                    assert step.custom_yes_button.isVisible()
                    step.custom_yes_button.click()
                    mock_open.assert_called_once()

                    # Clean up generated PDF backups from the cache.
                    cache_dir = Path(platformdirs.user_cache_dir("bitcoin_safe"))
                    prefix = f"Seed backup of {wallet_name}".replace(" ", "_")
                    temp_files = list(cache_dir.glob(f"{prefix}-*.pdf"))
                    assert temp_files
                    for temp_file in temp_files:
                        temp_file.unlink()

            page_backup()

            def switch_language() -> None:
                """Switch language."""
                # Briefly switch language to ensure translation updates.
                main_window.language_chooser.switchLanguage("zh_CN")
                shutter.save(main_window)
                main_window.language_chooser.switchLanguage("en_US")
                shutter.save(main_window)

            switch_language()

            def page_register() -> None:
                """Page register multisig."""
                shutter.save(main_window)
                if TutorialStep.register in wizard.tab_generators:
                    # Some flows include a registration step; advance if present.
                    step = wizard.tab_generators[TutorialStep.register]
                    step.buttonbox_buttons[0].click()
                    shutter.save(main_window)

            page_register()

            def page_receive() -> None:
                """Page receive."""
                shutter.save(main_window)
                step = wizard.tab_generators[TutorialStep.receive]
                assert isinstance(step, ReceiveTest)
                assert isinstance(step.quick_receive, BitcoinQuickReceive)
                address = step.quick_receive.group_boxes[0].address
                assert address.startswith("bcrt1")
                # Fund the address and wait for the wallet to sync.
                faucet.send(destination_address=address, amount=amount, qtbot=qtbot)
                wait_for_sync(wallet=qt_wallet.wallet, qtbot=qtbot, minimum_funds=amount, timeout=30_000)

                # The check button should report the updated balance, then disappear.
                called_args_message_box = get_called_args_message_box(
                    "bitcoin_safe.gui.qt.wizard.Message",
                    step.check_button,
                    repeat_clicking_until_message_box_called=True,
                )
                assert str(called_args_message_box) == str(
                    (f"Balance = {Satoshis(amount, network=test_config.network).str_with_unit()}",)
                )
                assert not step.check_button.isVisible()
                assert step.next_button.isVisible()
                shutter.save(main_window)
                step.next_button.click()
                shutter.save(main_window)

            page_receive()

            def page_send_and_sign() -> None:
                """Handle all send tests and signing."""
                send_steps = wizard.get_send_tests_steps()

                assert len(send_steps) == 2
                for send_step in send_steps:
                    wizard.set_current_index(wizard.index_of_step(send_step))
                    wizard.set_visibilities()
                    shutter.save(main_window)

                    step = wizard.tab_generators[send_step]
                    assert isinstance(step, SendTest)
                    assert step.refs.floating_button_box.isVisible()
                    assert step.refs.floating_button_box.button_create_tx.isVisible()
                    assert not step.refs.floating_button_box.tutorial_button_prefill.isVisible()

                    # Ensure the send UI is visible and anchored to this wizard step.
                    uitx = qt_wallet.uitx_creator
                    assert uitx.isVisible()
                    parent = uitx.parent()
                    assert parent is not None and parent.isVisible()
                    assert parent == wizard.widgets[send_step].widget

                    box = uitx.recipients.get_recipient_group_boxes()[0]
                    shutter.save(main_window)
                    assert box.address.startswith("bcrt1")
                    # The max amount should match balance minus fee.
                    fee_info = uitx.estimate_fee_info(uitx.column_fee.fee_group.spin_fee_rate.value())
                    assert (
                        uitx.recipients.recipients[0].amount
                        == qt_wallet.wallet.get_balance().total - fee_info.fee_amount
                    )
                    assert uitx.recipients.recipients[0].checked_max_amount

                    # Create a PSBT, then sign and send it.
                    step.refs.floating_button_box.button_create_tx.click()
                    shutter.save(main_window)

                    viewer = main_window.tab_wallets.currentNode().data
                    assert isinstance(viewer, UITx_Viewer)
                    assert viewer.recipients.recipients
                    assert viewer.fee_info
                    assert not viewer.column_fee.fee_group.allow_edit

                    sign_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer)

                    # Broadcast and wait for the wallet to observe the tx.
                    with patch("bitcoin_safe.gui.qt.wizard.Message") as mock_message:
                        viewer.button_send.click()
                        assert isinstance((tx := viewer.data.data), bdk.Transaction)
                        wait_for_sync(
                            qtbot=qtbot, wallet=qt_wallet.wallet, txid=str(tx.compute_txid()), timeout=20_000
                        )
                        qtbot.wait_until(lambda: bool(mock_message.call_count), timeout=10_000)
                        # only final send should show "all tests done", so don't assert message content strictly

            page_send_and_sign()

            def page_distribute_and_sync() -> None:
                """Finish tutorial."""
                shutter.save(main_window)

                step = wizard.tab_generators[TutorialStep.distribute]
                assert isinstance(step, DistributeSeeds)
                # Advance through distribute seeds.
                assert step.buttonbox_buttons[0].isVisible()
                step.buttonbox_buttons[0].click()
                shutter.save(main_window)

                step = wizard.tab_generators[TutorialStep.sync]
                assert isinstance(step, LabelBackup)
                # Advance through sync/label step.
                assert step.buttonbox_buttons[0].isVisible()
                step.buttonbox_buttons[0].click()
                shutter.save(main_window)

            page_distribute_and_sync()

        do_all(qt_wallet)

        def check_address_balances(qt_wallet: QTWallet):
            """Check address balances."""
            wallet = qt_wallet.wallet

            # check that spent utxos do not count into the address balance
            addresses = wallet.get_addresses()
            assert addresses
            total = 0
            for address in addresses:
                total += wallet.get_addr_balance(address).total

            assert total
            assert total == wallet.get_balance().total

        check_address_balances(qt_wallet)

        def check_utxo_list(qt_wallet: QTWallet) -> None:
            """Check utxo list."""
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

        check_utxo_list(qt_wallet)
        del wizard

        with CheckedDeletionContext(
            qt_wallet=qt_wallet, qtbot=qtbot, caplog=caplog, graph_directory=shutter.used_directory()
        ):
            # Delete and close the wallet to ensure cleanup paths are exercised.
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
            """Check that it is in recent wallets."""
            # The wallet should appear in recent wallets after closing.
            assert any(
                [
                    (wallet_name in name)
                    for name in main_window.config.recently_open_wallets[main_window.config.network]
                ]
            )

            shutter.save(main_window)

        check_that_it_is_in_recent_wallets()

        # Final screenshot after assertions.
        shutter.save(main_window)
