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

import logging
from datetime import datetime

import pytest
from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.bitcoin_quick_receive import BitcoinQuickReceive
from bitcoin_safe.gui.qt.card_base import CardExpansionMode
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.wizard.wizard import (
    DistributeSeeds,
    ImportXpubs,
    PluginListStep,
    ReceiveTest,
    SendTest,
    TutorialStep,
    WalletSetupOptions,
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
    main_window_context,
    save_wallet,
    select_manual_entry_signer,
    sign_tx,
)

logger = logging.getLogger(__name__)


def enter_text(text: str, widget: QWidget) -> None:
    """Simulate key-by-key text entry into a widget."""
    for char in text:
        QTest.keyClick(widget, char)


def _run_multisig_wizard_test(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    backend: str,
    wallet_name: str,
    test_name: str,
    template: WalletSetupOptions.WalletTemplate,
    threshold: int,
    signers: int,
    amount: int,
) -> None:
    """Exercise the full multisig wizard, including the send-test card flow."""
    logger.debug(f"start {test_name}")
    del backend
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{test_name}")
    shutter.create_symlink(test_config=test_config)
    logger.debug(f"shutter = {shutter}")
    with main_window_context(test_config=test_config) as main_window:
        logger.debug(f"(app, main_window) = {main_window}")
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin-Safe - REGTEST"

        shutter.save(main_window)

        main_window.welcome_screen.set_wallet_name(wallet_name)
        shutter.save(main_window)
        qtbot.mouseClick(main_window.welcome_screen.card_connect_devices, Qt.MouseButton.LeftButton)
        shutter.save(main_window)

        qt_protowallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert isinstance(qt_protowallet, QTProtoWallet)
        wizard = qt_protowallet.wizard
        assert isinstance(wizard, Wizard)

        def page_wallet_setup(wizard: Wizard) -> None:
            shutter.save(main_window)
            step = wizard.tab_generators[TutorialStep.wallet_setup]
            assert isinstance(step, WalletSetupOptions)
            assert step.edit_wallet_name.text() == wallet_name
            assert step.template_options
            if template != step.WalletTemplate.two_of_three:
                qtbot.mouseClick(step.template_options[template], Qt.MouseButton.LeftButton)
                shutter.save(main_window)
            assert step.card_required_signers.label_value.text() == str(threshold)
            assert step.card_required_signers.label_subtitle.text() == (
                "signer" if threshold == 1 else "signers"
            )
            assert step.card_recovery_signers.label_value.text() == str(signers - threshold)
            assert step.card_recovery_signers.label_subtitle.text() == (
                "signer" if signers - threshold == 1 else "signers"
            )
            assert step.card_total_signers.label_value.text() == str(signers)
            assert step.card_total_signers.label_subtitle.text() == "signers"
            assert step.button_next.isVisible()
            step.button_next.click()

        page_wallet_setup(wizard)

        def page_import(wizard: Wizard) -> None:
            shutter.save(main_window)
            step = wizard.tab_generators[TutorialStep.import_xpub]
            assert isinstance(step, ImportXpubs)
            assert step.keystore_uis

            for seed, keystore in zip(
                test_seeds[32 : 32 + signers], step.keystore_uis.getAllTabData().values(), strict=False
            ):
                select_manual_entry_signer(keystore)
                keystore.edit_seed.setText(seed)
                shutter.save(main_window)

            save_wallet(
                test_config=test_config,
                wallet_name=wallet_name,
                save_button=step.button_create_wallet,
            )

        page_import(wizard)

        qt_wallet = main_window.tab_wallets.root.findNodeByTitle(wallet_name).data
        assert isinstance(qt_wallet, QTWallet)
        wizard = qt_wallet.wizard
        assert isinstance(wizard, Wizard)

        def do_all(wizard: Wizard, qt_wallet: QTWallet) -> None:
            def page_backup_not_in_wallet_wizard(wizard: Wizard) -> None:
                shutter.save(main_window)
                assert "backup_seed" not in TutorialStep.__members__

            page_backup_not_in_wallet_wizard(wizard)

            def switch_language() -> None:
                main_window.language_chooser.switchLanguage("zh_CN")
                shutter.save(main_window)
                main_window.language_chooser.switchLanguage("en_US")
                shutter.save(main_window)

            switch_language()

            def page_register(wizard: Wizard) -> None:
                shutter.save(main_window)
                if TutorialStep.register in wizard.tab_generators:
                    step = wizard.tab_generators[TutorialStep.register]
                    step.button_next.click()
                    shutter.save(main_window)

            page_register(wizard)

            def page_plugins_before_receive(wizard: Wizard) -> None:
                shutter.save(main_window)
                step = wizard.tab_generators[TutorialStep.plugins]
                assert isinstance(step, PluginListStep)
                assert wizard.current_step() == TutorialStep.plugins
                assert step.button_next.isVisible()
                step.button_next.click()
                qtbot.waitUntil(lambda: wizard.current_step() == TutorialStep.receive, timeout=5_000)
                shutter.save(main_window)

            page_plugins_before_receive(wizard)

            def page_receive(wizard: Wizard, qt_wallet: QTWallet) -> None:
                shutter.save(main_window)
                step = wizard.tab_generators[TutorialStep.receive]
                assert isinstance(step, ReceiveTest)
                assert isinstance(step.quick_receive, BitcoinQuickReceive)
                assert step.button_previous.isVisible()
                address = step.quick_receive.group_boxes[0].address
                assert address.startswith("bcrt1")
                faucet.send(destination_address=address, amount=amount, qtbot=qtbot)
                wait_for_sync(wallet=qt_wallet, qtbot=qtbot, minimum_funds=amount, timeout=30_000)

                if not step.check_button.isHidden():
                    step.check_button.click()
                assert not step.check_button.isVisible()
                assert step.next_button.isVisible()
                qtbot.waitUntil(lambda: step.get_received_txid() is not None, timeout=5_000)
                shutter.save(main_window)
                step.next_button.click()
                shutter.save(main_window)

            page_receive(wizard, qt_wallet)

            def page_send_and_sign(wizard: Wizard, qt_wallet: QTWallet) -> None:
                send_steps = wizard.get_send_tests_steps()
                assert len(send_steps) == 2
                if template == WalletSetupOptions.WalletTemplate.three_of_five:
                    send_test_labels = wizard.get_send_test_labels()
                    assert len(send_test_labels) == 2
                    assert "Signer 1" in send_test_labels[0]
                    assert "Signer 2" in send_test_labels[0]
                    assert "Signer 3" in send_test_labels[0]
                    assert "Signer 3" in send_test_labels[1]
                    assert "Recovery Signer 4" in send_test_labels[1]
                    assert "Recovery Signer 5" in send_test_labels[1]

                for send_step in send_steps:
                    wizard.set_current_index(wizard.index_of_step(send_step))
                    wizard.set_visibilities()
                    shutter.save(main_window)

                    step = wizard.tab_generators[send_step]
                    assert isinstance(step, SendTest)
                    uitx = qt_wallet.uitx_creator
                    assert uitx.button_box.isVisible()
                    assert uitx.button_ok.isVisible()
                    assert not uitx.button_back.isVisible()
                    assert uitx.button_clear is not None and not uitx.button_clear.isVisible()
                    assert wizard.send_test_previous_button.isVisible()
                    assert uitx.isVisible()
                    parent = uitx.parent()
                    assert parent is not None and parent.isVisible()
                    assert step.active_card.content_layout.indexOf(uitx) != -1

                    box = uitx.recipients.get_recipient_group_boxes()[0]
                    shutter.save(main_window)
                    assert box.address.startswith("bcrt1")
                    fee_info = uitx.estimate_fee_info(uitx.column_fee.fee_group.spin_fee_rate.value())
                    assert (
                        uitx.recipients.recipients[0].amount
                        == qt_wallet.wallet.get_balance().total - fee_info.fee_amount
                    )
                    assert uitx.recipients.recipients[0].checked_max_amount
                    assert main_window.tab_wallets.currentNode() != qt_wallet.hist_node

                    uitx.button_ok.click()
                    qtbot.waitUntil(lambda step=step: step.embedded_viewer is not None, timeout=10_000)
                    shutter.save(main_window)

                    viewer = step.embedded_viewer
                    assert isinstance(viewer, UITx_Viewer)
                    assert viewer.recipients.recipients
                    assert viewer.fee_info
                    assert not viewer.column_fee.fee_group.allow_edit
                    txid = str(viewer.extract_tx().compute_txid())
                    assert main_window.get_tx_viewer(txid) is None

                    sign_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer)
                    viewer.button_send.click()
                    assert main_window.tab_wallets.currentNode() != qt_wallet.hist_node

                    wait_for_sync(qtbot=qtbot, wallet=qt_wallet.wallet, txid=txid, timeout=40_000)
                    qtbot.waitUntil(lambda txid=txid: txid in wizard.recognized_txids, timeout=40_000)
                    qtbot.waitUntil(lambda step=step: step.buttonbox.isVisible(), timeout=5_000)
                    qtbot.waitUntil(lambda step=step: step.embedded_viewer is None, timeout=5_000)
                    assert txid in wizard.recognized_txids
                    assert step.active_card.expansion_mode() == CardExpansionMode.FIXED_COLLAPSED
                    assert txid[:4] in step.active_card.header_subtitle.text()
                    assert main_window.tab_wallets.currentNode() != qt_wallet.hist_node
                    step.button_next.click()

            page_send_and_sign(wizard, qt_wallet)

            def page_distribute_and_plugins(wizard: Wizard) -> None:
                shutter.save(main_window)

                step = wizard.tab_generators[TutorialStep.distribute]
                assert isinstance(step, DistributeSeeds)
                step.backup_sheets_printed = True
                step.seed_words_attached_confirmed = True
                step._refresh_action_buttons()
                assert step.button_next.isVisible()
                qtbot.waitUntil(lambda: step.button_next.isEnabled(), timeout=5_000)
                step.button_next.click()
                qtbot.waitUntil(lambda: not wizard.should_be_visible, timeout=5_000)
                shutter.save(main_window)

            page_distribute_and_plugins(wizard)

        do_all(wizard, qt_wallet)

        def check_address_balances(qt_wallet: QTWallet) -> None:
            wallet = qt_wallet.wallet
            addresses = wallet.get_addresses()
            assert addresses

            total = 0
            for address in addresses:
                total += wallet.get_addr_balance(address).total

            assert total
            assert total == wallet.get_balance().total

        check_address_balances(qt_wallet)

        def check_utxo_list(qt_wallet: QTWallet) -> None:
            qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
            qt_wallet.uitx_creator.column_inputs.checkBox_manual_coin_select.setChecked(True)
            QCoreApplication.processEvents()

            utxo_list = qt_wallet.uitx_creator.utxo_list
            total = 0
            model = utxo_list._source_model
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
        shutter.save(main_window)


@pytest.mark.marker_qt_1
def test_wizard_multisig(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    backend: str,
    wallet_name: str = "test_wizard_multisig",
    amount: int = int(1e6),
) -> None:
    """Exercise the default 2-of-3 multisig wizard flow."""
    _run_multisig_wizard_test(
        qtbot=qtbot,
        mytest_start_time=mytest_start_time,
        test_config=test_config,
        faucet=faucet,
        caplog=caplog,
        backend=backend,
        wallet_name=wallet_name,
        test_name="test_wizard_multisig",
        template=WalletSetupOptions.WalletTemplate.two_of_three,
        threshold=2,
        signers=3,
        amount=amount,
    )


@pytest.mark.marker_qt_1
def test_wizard_multisig_3_of_5(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    backend: str,
    wallet_name: str = "test_wizard_multisig_3_of_5",
    amount: int = int(1e6),
) -> None:
    """Exercise the extended 3-of-5 multisig wizard flow."""
    _run_multisig_wizard_test(
        qtbot=qtbot,
        mytest_start_time=mytest_start_time,
        test_config=test_config,
        faucet=faucet,
        caplog=caplog,
        backend=backend,
        wallet_name=wallet_name,
        test_name="test_wizard_multisig_3_of_5",
        template=WalletSetupOptions.WalletTemplate.three_of_five,
        threshold=3,
        signers=5,
        amount=amount,
    )
