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
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.import_export import HorizontalImportExportAll
from bitcoin_safe.gui.qt.keystore_ui import SignerUI
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.mempool_manager import TxPrio
from bitcoin_safe.psbt_util import SimplePSBT
from bitcoin_safe.pythonbdk_types import OutPoint, TxOut, robust_address_str_from_txout
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason
from bitcoin_safe.tx import TxUiInfos

from ...faucet import Faucet
from ...helpers import TestConfig
from .helpers import (
    CheckedDeletionContext,
    Shutter,
    close_wallet,
    fund_wallet,
    main_window_context,
)

SEND_TEST_WALLET_FUND_AMOUNT = 10000000

logger = logging.getLogger(__name__)


def _rounded(value: float, decimals: int) -> float:
    return round(value, decimals)


def _close_to(value: int, expected: int, tolerance: int) -> bool:
    return abs(value - expected) <= tolerance


def _outpoints_from_psbt(psbt) -> set[OutPoint]:
    return {OutPoint.from_bdk(txin.previous_output) for txin in psbt.extract_tx().input()}


def _outputs_by_address(psbt, network) -> dict[str, int]:
    output_map: dict[str, int] = {}
    for output in psbt.extract_tx().output():
        address = robust_address_str_from_txout(TxOut.from_bdk(output), network=network)
        output_map[address] = output.value.to_sat()
    return output_map


def _set_category(
    qt_wallet: QTWallet,
    address: str,
    category: str,
) -> None:
    qt_wallet.wallet.labels.set_addr_category(address, category, timestamp="now")
    qt_wallet.wallet_signals.updated.emit(
        UpdateFilter(addresses=[address], categories=[category], reason=UpdateFilterReason.CategoryChange)
    )


@pytest.mark.marker_qt_2
def test_wallet_send(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    caplog: pytest.LogCaptureFixture,
    wallet_file: str = "send_test.wallet",
) -> None:
    """Test wallet send."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        temp_dir = Path(tempfile.mkdtemp()) / wallet_file

        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert qt_wallet

        def do_all(qt_wallet: QTWallet):
            "any implicit reference to qt_wallet (including the function page_send) will create a cell refrence"

            qt_wallet.tabs.setCurrentWidget(qt_wallet.address_tab)

            shutter.save(main_window)
            # check wallet address
            assert qt_wallet.wallet.get_addresses()[0] == "bcrt1q3y9dezdy48czsck42q5udzmlcyjlppel5eg92k"

            fund_wallet(
                qt_wallet=qt_wallet,
                amount=SEND_TEST_WALLET_FUND_AMOUNT,
                faucet=faucet,
                qtbot=qtbot,
            )

            def select_utxos_for_sending() -> None:
                """Ensure selecting addresses seeds the send flow with the right UTXOs."""
                address_list = qt_wallet.address_list
                wallet = qt_wallet.wallet

                target_address = wallet.get_addresses()[0]
                grouped_addresses: dict[str, list[str]] = {wallet.id: [target_address]}

                captured: list[TxUiInfos] = []

                wallet_utxos = wallet.get_all_utxos()
                assert wallet_utxos

                def on_open_tx_like(tx_ui_infos: TxUiInfos) -> None:
                    captured.append(tx_ui_infos)

                qt_wallet.wallet_functions.signals.open_tx_like.connect(on_open_tx_like)
                try:
                    address_list._select_utxos_for_sending(grouped_addresses)
                    qtbot.wait_until(lambda: qt_wallet.tabs.currentWidget() is qt_wallet.uitx_creator)
                finally:
                    qt_wallet.wallet_functions.signals.open_tx_like.disconnect(on_open_tx_like)

                assert captured
                tx_ui_infos = captured[-1]
                assert tx_ui_infos.main_wallet_id == wallet.id
                assert tx_ui_infos.spend_all_utxos is True
                assert tx_ui_infos.hide_UTXO_selection is False
                assert set(utxo.address for utxo in tx_ui_infos.utxo_dict.values()) == {target_address}

                uitx_creator = qt_wallet.uitx_creator
                assert qt_wallet.tabs.currentWidget() is uitx_creator
                assert uitx_creator.column_inputs.checkBox_manual_coin_select.isChecked()
                assert uitx_creator.utxo_list.isVisible()

                def _selection_matches() -> bool:
                    selected_outpoints = set(uitx_creator.utxo_list.get_selected_outpoints())
                    return selected_outpoints == set(tx_ui_infos.utxo_dict.keys())

                qtbot.wait_until(_selection_matches)
                assert _selection_matches()

            select_utxos_for_sending()

            def import_recipients() -> None:
                """Import recipients."""
                qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
                shutter.save(main_window)
                qt_wallet.uitx_creator.recipients.add_recipient_button.click()
                shutter.save(main_window)

                test_file_path = "tests/data/recipients.csv"
                with open(str(test_file_path)) as file:
                    test_file_content = file.read()

                qt_wallet.uitx_creator.recipients.import_csv(test_file_path)
                shutter.save(main_window)

                assert len(qt_wallet.uitx_creator.recipients.recipients) == 2
                r = qt_wallet.uitx_creator.recipients.recipients[0]
                assert r.address == "bcrt1q8tzpytutwlxpqjyhku3c4pyzz62sx5dv9ly67cx4qvran7stwlgqvmvhrw"
                assert r.amount == 1000
                assert r.label == "1"

                r = qt_wallet.uitx_creator.recipients.recipients[1]
                assert r.address == "bcrt1q6dqexpz2rp3r08nm6w8l5h3tgvqgn3c96jl6jt9vv3heylvmr8lskchhzn"
                assert r.amount == 2000
                assert r.label == "2"

                shutter.save(main_window)

                with tempfile.TemporaryDirectory() as tempdir:
                    file_path = Path(tempdir) / "test.csv"
                    qt_wallet.uitx_creator.recipients.export_csv(
                        qt_wallet.uitx_creator.recipients.recipients, file_path=file_path
                    )

                    assert file_path.exists()

                    with open(str(file_path)) as file:
                        output_file_content = file.read()

                    assert test_file_content == output_file_content

            import_recipients()

            def create_signed_tx() -> None:
                """Create signed tx."""
                with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=10_000):
                    qt_wallet.uitx_creator.button_ok.click()
                shutter.save(main_window)

                ui_tx_viewer = main_window.tab_wallets.currentNode().data
                assert isinstance(ui_tx_viewer, UITx_Viewer)
                assert len(ui_tx_viewer.recipients.recipients) == 3

                sorted_recipients = sorted(
                    ui_tx_viewer.recipients.recipients, key=lambda recipient: recipient.address
                )

                r = sorted_recipients[1]
                assert r.address == "bcrt1q8tzpytutwlxpqjyhku3c4pyzz62sx5dv9ly67cx4qvran7stwlgqvmvhrw"
                assert r.amount == 1000
                assert r.label == "1"

                r = sorted_recipients[0]
                assert r.address == "bcrt1q6dqexpz2rp3r08nm6w8l5h3tgvqgn3c96jl6jt9vv3heylvmr8lskchhzn"
                assert r.amount == 2000
                assert r.label == "2"

                r = sorted_recipients[2]
                assert r.address == "bcrt1qdcn67p707adhet4a9lh6pt8m5h4yjjf2nayqlq"
                assert r.address == qt_wallet.wallet.get_change_addresses()[0]
                assert r.amount == 9996804
                assert r.label == "Change of: 1, 2"

                ui_tx_viewer.button_next.click()

                widget = ui_tx_viewer.tx_singning_steps.stacked_widget.widget(0)
                assert isinstance(widget, HorizontalImportExportAll)
                signer_ui = widget.wallet_importers.signer_ui
                assert isinstance(signer_ui, SignerUI)
                for button in signer_ui.findChildren(QPushButton):
                    assert button.text() == f"Seed of '{qt_wallet.wallet.id}'"
                    assert button.isVisible()
                    button.click()

                    with qtbot.waitSignal(signer_ui.signal_signature_added, timeout=10_000):
                        button.click()

                shutter.save(main_window)

            create_signed_tx()

            def send_tx() -> None:
                """Send tx."""
                shutter.save(main_window)

                ui_tx_viewer = main_window.tab_wallets.currentNode().data
                assert isinstance(ui_tx_viewer, UITx_Viewer)
                assert len(ui_tx_viewer.recipients.recipients) == 3

                sorted_recipients = sorted(
                    ui_tx_viewer.recipients.recipients, key=lambda recipient: recipient.address
                )

                r = sorted_recipients[1]
                assert r.address == "bcrt1q8tzpytutwlxpqjyhku3c4pyzz62sx5dv9ly67cx4qvran7stwlgqvmvhrw"
                assert r.amount == 1000
                assert r.label == "1"

                r = sorted_recipients[0]
                assert r.address == "bcrt1q6dqexpz2rp3r08nm6w8l5h3tgvqgn3c96jl6jt9vv3heylvmr8lskchhzn"
                assert r.amount == 2000
                assert r.label == "2"

                r = sorted_recipients[2]
                assert r.address == "bcrt1qdcn67p707adhet4a9lh6pt8m5h4yjjf2nayqlq"
                assert r.address == qt_wallet.wallet.get_change_addresses()[0]
                assert r.amount == 9996804
                assert r.label == "Change of: 1, 2"

                with qtbot.waitSignal(qt_wallet.wallet_signals.updated, timeout=60_000):
                    ui_tx_viewer.button_send.click()

                shutter.save(main_window)
                qt_wallet_tab = main_window.tab_wallets.currentNode().parent_node.data
                assert isinstance(qt_wallet_tab, QTWallet)
                QApplication.processEvents()

                # check the tx is in the hist list
                model = qt_wallet_tab.history_list._source_model
                for row in range(model.rowCount()):
                    index = model.index(row, model.key_column)
                    this_content = model.data(index, MyItemDataRole.ROLE_KEY)
                    if this_content == ui_tx_viewer.txid():
                        break
                else:
                    raise Exception("tx not found in hist list")

            send_tx()

        do_all(qt_wallet)

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

        def check_that_it_is_in_recent_wallets() -> None:
            """Check that it is in recent wallets."""
            assert any(
                [
                    (wallet_file in name)
                    for name in main_window.config.recently_open_wallets[main_window.config.network]
                ]
            )

            shutter.save(main_window)

        check_that_it_is_in_recent_wallets()

        # end
        shutter.save(main_window)


@pytest.mark.marker_qt_3
def test_send_tab_complex_interactions(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    wallet_file: str = "send_test.wallet",
) -> None:
    """Test send tab interactions: recipients, fee, PSBT, categories, max, reset, edit."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        temp_dir = Path(tempfile.mkdtemp()) / wallet_file
        wallet_path = Path("tests") / "data" / wallet_file
        shutil.copy(str(wallet_path), str(temp_dir))

        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert isinstance(qt_wallet, QTWallet)
        shutter.save(main_window)

        wallet = qt_wallet.wallet
        receiving_addresses = wallet.get_receiving_addresses()
        assert len(receiving_addresses) >= 3
        kyc_address = receiving_addresses[0]
        private_address = receiving_addresses[1]
        unused_recipient_address = receiving_addresses[2]
        category_recipient_address = str(wallet.get_address(force_new=True).address)

        _set_category(qt_wallet, kyc_address, "KYC")
        _set_category(qt_wallet, private_address, "Private")
        shutter.save(main_window)

        fund_wallet(qtbot=qtbot, faucet=faucet, qt_wallet=qt_wallet, amount=250_000, address=kyc_address)
        fund_wallet(qtbot=qtbot, faucet=faucet, qt_wallet=qt_wallet, amount=150_000, address=private_address)

        qtbot.waitUntil(lambda: wallet.get_addr_balance(kyc_address).total > 0, timeout=20_000)
        qtbot.waitUntil(lambda: wallet.get_addr_balance(private_address).total > 0, timeout=20_000)
        shutter.save(main_window)

        qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)
        uitx_creator = qt_wallet.uitx_creator
        uitx_creator.enable_refresh_counters()
        shutter.save(main_window)

        fee_spin = uitx_creator.column_fee.fee_group.spin_fee_rate
        fee_decimals = fee_spin.decimals()
        expected_fee_rate = uitx_creator.mempool_manager.get_prio_fee_rates()[TxPrio.low]
        # Default fee rate should match the mempool "low" preset shown to the user.
        assert _rounded(fee_spin.value(), fee_decimals) == _rounded(expected_fee_rate, fee_decimals)
        shutter.save(main_window)

        recipients = uitx_creator.recipients
        # Start with one recipient and verify add/remove paths update the UI list.
        assert recipients.count() == 1
        recipients.add_recipient_button.click()
        recipients.add_recipient_button.click()
        qtbot.waitUntil(lambda: recipients.count() == 3)
        shutter.save(main_window)

        recipient_boxes = recipients.get_recipient_group_boxes()
        assert len(recipient_boxes) == 3
        close_button = recipient_boxes[0].notification_bar.closeButton
        close_button.click()
        qtbot.waitUntil(lambda: recipients.count() == 2)
        shutter.save(main_window)

        recipient_boxes = recipients.get_recipient_group_boxes()
        assert len(recipient_boxes) == 2

        # Mix one wallet-owned recipient with one external address.
        external_address = str(faucet.wallet.get_address().address)
        recipient_boxes[0].address = unused_recipient_address
        recipient_boxes[1].address = external_address

        recipient_boxes[1].amount = 50_000
        shutter.save(main_window)

        uitx_creator.column_inputs.checkBox_manual_coin_select.setChecked(True)
        shutter.save(main_window)

        utxos = wallet.get_all_utxos()
        kyc_utxos = [utxo for utxo in utxos if utxo.address == kyc_address]
        private_utxos = [utxo for utxo in utxos if utxo.address == private_address]
        assert kyc_utxos
        assert private_utxos

        selected_outpoint = kyc_utxos[0].outpoint
        uitx_creator.utxo_list.select_rows(
            [selected_outpoint],
            uitx_creator.utxo_list.key_column,
            role=MyItemDataRole.ROLE_KEY,
            scroll_to_last=True,
        )

        qtbot.waitUntil(lambda: set(uitx_creator.utxo_list.get_selected_outpoints()) == {selected_outpoint})
        shutter.save(main_window)

        # Set fee rate explicitly to verify PSBT fee rate propagation.
        fee_rate_target = 2.0
        fee_spin.setValue(fee_rate_target)
        qtbot.wait(100)
        shutter.save(main_window)

        # Single send-max should show "Max ≈" and compute from selected input - fee - fixed amount.
        recipient_boxes[0].recipient_widget.send_max_checkbox.click()
        assert recipient_boxes[0].recipient_widget.send_max_checkbox.text() == "Send max"
        fee_info = uitx_creator.estimate_fee_info(fee_rate=fee_spin.value())
        expected_single_max = (
            sum(utxo.value for utxo in kyc_utxos[:1]) - recipient_boxes[1].amount - fee_info.fee_amount
        )
        # Max amount should equal selected input minus fixed recipient amount and fee.
        qtbot.waitUntil(lambda: _close_to(recipient_boxes[0].amount, expected_single_max, 200))
        qtbot.waitUntil(lambda: "Max ≈" in recipient_boxes[0].recipient_widget.amount_spin_box.text())
        shutter.save(main_window)

        # Disable max and set explicit amount; UI text should drop the "Max ≈" indicator.
        recipient_boxes[0].recipient_widget.send_max_checkbox.click()
        recipient_boxes[0].amount = 60_000
        assert recipient_boxes[0].amount == 60_000
        qtbot.waitUntil(lambda: "Max ≈" not in recipient_boxes[0].recipient_widget.amount_spin_box.text())
        shutter.save(main_window)

        # Dual send-max should split the remaining amount evenly between recipients.
        recipient_boxes[0].recipient_widget.send_max_checkbox.click()
        recipient_boxes[1].recipient_widget.send_max_checkbox.click()
        fee_info = uitx_creator.estimate_fee_info(fee_rate=fee_spin.value())
        total_input = sum(utxo.value for utxo in kyc_utxos[:1])
        qtbot.waitUntil(lambda: recipient_boxes[0].amount > 0)
        qtbot.waitUntil(lambda: recipient_boxes[0].amount == recipient_boxes[1].amount)
        combined = recipient_boxes[0].amount + recipient_boxes[1].amount + fee_info.fee_amount
        # Max split should consume the input minus fee, leaving at most rounding dust.
        assert total_input - combined >= 0
        assert total_input - combined <= 200
        max_amounts = (recipient_boxes[0].amount, recipient_boxes[1].amount)
        expected_split = (total_input - fee_info.fee_amount) // 2
        assert _close_to(recipient_boxes[0].amount, expected_split, 200)
        assert _close_to(recipient_boxes[1].amount, expected_split, 200)
        qtbot.waitUntil(lambda: "Max ≈" in recipient_boxes[0].recipient_widget.amount_spin_box.text())
        qtbot.waitUntil(lambda: "Max ≈" in recipient_boxes[1].recipient_widget.amount_spin_box.text())
        expected_text = f"Max ≈ {Satoshis(recipient_boxes[0].amount, wallet.network)}"
        assert recipient_boxes[0].recipient_widget.amount_spin_box.text() == expected_text
        assert recipient_boxes[1].recipient_widget.amount_spin_box.text() == expected_text
        shutter.save(main_window)

        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=20_000):
            uitx_creator.button_ok.click()
        shutter.save(main_window)

        ui_tx_viewer = main_window.tab_wallets.currentNode().data
        assert isinstance(ui_tx_viewer, UITx_Viewer)
        assert ui_tx_viewer.fee_info
        # Fee rate displayed in the PSBT view should match the selected fee spin value.
        assert _rounded(ui_tx_viewer.fee_info.fee_rate(), fee_decimals) == _rounded(
            fee_rate_target, fee_decimals
        )
        psbt = ui_tx_viewer.data.data
        assert psbt
        # PSBT fee should reflect the same fee value shown in the viewer.
        assert ui_tx_viewer.fee_info.fee_amount == psbt.fee()

        # PSBT should spend only the manually selected UTXO.
        psbt_outpoints = _outpoints_from_psbt(psbt)
        assert psbt_outpoints == {selected_outpoint}

        outputs = _outputs_by_address(psbt, network=wallet.network)
        # With both recipients on send-max, there should be no change output.
        assert set(outputs.keys()) == {unused_recipient_address, external_address}
        # Outputs should match the max-split amounts shown in the UI (tolerate rounding).
        assert _close_to(outputs[unused_recipient_address], outputs[external_address], 200)
        assert _close_to(outputs[unused_recipient_address], max_amounts[0], 200)
        assert _close_to(outputs[external_address], max_amounts[1], 200)
        shutter.save(main_window)

        ui_tx_viewer.button_edit_tx.click()
        qtbot.waitUntil(lambda: qt_wallet.tabs.currentWidget() is qt_wallet.uitx_creator, timeout=10_000)
        shutter.save(main_window)

        edited_creator = qt_wallet.uitx_creator
        edited_fee_spin = edited_creator.column_fee.fee_group.spin_fee_rate
        # Edit should restore fee rate and selected inputs from the PSBT (excluding change output).
        assert _rounded(edited_fee_spin.value(), fee_decimals) == _rounded(fee_spin.value(), fee_decimals)
        assert set(edited_creator.utxo_list.get_selected_outpoints()) == {selected_outpoint}

        edited_recipients = edited_creator.recipients.recipients
        edited_addresses = {recipient.address for recipient in edited_recipients}
        assert unused_recipient_address in edited_addresses
        assert external_address in edited_addresses
        for change_address in wallet.get_change_addresses():
            assert change_address not in edited_addresses

        # Reset should collapse recipients and clear coin-selection state.
        edited_creator.button_clear.click()
        qtbot.waitUntil(lambda: edited_creator.recipients.count() == 1)
        assert not edited_creator.column_inputs.checkBox_manual_coin_select.isChecked()
        assert edited_creator.utxo_list.get_selected_outpoints() == []
        shutter.save(main_window)

        edited_creator.column_inputs.checkBox_manual_coin_select.setChecked(False)
        edited_creator.category_list.select_row_by_clipboard("Private")
        qtbot.wait(100)
        shutter.save(main_window)

        recipient_boxes = edited_creator.recipients.get_recipient_group_boxes()
        assert len(recipient_boxes) == 1
        recipient_boxes[0].address = category_recipient_address
        recipient_boxes[0].amount = 25_000
        qtbot.wait(100)
        qtbot.waitUntil(
            lambda: wallet.labels.get_category(category_recipient_address) == "Private", timeout=10_000
        )
        shutter.save(main_window)

        edited_creator.category_list.select_row_by_clipboard("KYC")
        qtbot.waitUntil(
            lambda: wallet.labels.get_category(category_recipient_address) == "KYC", timeout=10_000
        )
        shutter.save(main_window)

        with qtbot.waitSignal(main_window.signals.open_tx_like, timeout=20_000):
            edited_creator.button_ok.click()
        shutter.save(main_window)

        ui_tx_viewer = main_window.tab_wallets.currentNode().data
        assert isinstance(ui_tx_viewer, UITx_Viewer)
        psbt = ui_tx_viewer.data.data
        assert psbt

        simple_psbt = SimplePSBT.from_psbt(psbt)
        input_outpoints = {OutPoint.from_bdk(inp.txin.previous_output) for inp in simple_psbt.inputs}
        wallet_utxos = {OutPoint.from_bdk(utxo.outpoint): utxo for utxo in wallet.get_all_utxos()}
        input_categories = {
            wallet.labels.get_category(wallet_utxos[outpoint].address)
            for outpoint in input_outpoints
            if outpoint in wallet_utxos
        }
        # Category-filtered send should pull inputs from the selected category only.
        assert input_categories == {"KYC"}

        refresh_counts = uitx_creator.refresh_counter_snapshot()
        logger.info("send_tab_refresh_counts=%s", refresh_counts)
