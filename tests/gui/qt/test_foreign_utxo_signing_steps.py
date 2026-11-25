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

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.util import network_kind
from bitcoin_usb.address_types import AddressTypes
from PyQt6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from bitcoin_safe.foreign_utxo import ForeignUtxo
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.tx_signing_steps import TxSigningDeviceList, TxSigningSteps
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.psbt_util import SimplePSBT
from bitcoin_safe.pythonbdk_types import OutPoint, PythonUtxo, Recipient
from bitcoin_safe.signals import Signals, WalletFunctions
from bitcoin_safe.wallet import ProtoWallet, Wallet
from tests.gui.qt.helpers import Shutter, main_window_context, setup_single_sig_wallet
from tests.helpers import TestConfig as ConfigForTest
from tests.non_gui.test_foreign_utxo import NETWORK, make_wallet, transaction
from tests.non_gui.test_seed_sign_message import _wallet as _multisig_wallet
from tests.non_gui.test_signers import test_seeds
from tests.non_gui.utils import create_keystore

SEEDS = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
    "legal winner thank year wave sausage worth useful legal winner thank yellow",
)


@pytest.mark.marker_qt_2
def test_viewer_signs_inputs_from_two_open_seed_wallets(
    qtbot: QtBot, mytest_start_time: datetime, test_config: ConfigForTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_two_seed_wallets")
    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        first = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="signer_0",
            seed=SEEDS[0],
        )
        keystores = [create_keystore(seed, "m/48h/1h/0h/1h", "signer") for seed in (SEEDS[1], test_seeds[2])]
        protowallet = ProtoWallet("nested", 2, NETWORK, keystores, AddressTypes.p2sh_p2wsh)
        nested_wallet = Wallet.from_protowallet(protowallet, test_config, main_window.loop_in_thread)
        second = QTWallet(
            wallet=nested_wallet,
            config=test_config,
            wallet_functions=main_window.wallet_functions,
            mempool_manager=main_window.mempool_manager,
            fx=main_window.fx,
            loop_in_thread=main_window.loop_in_thread,
            file_path=str(Path(test_config.config_dir) / "nested.wallet"),
        )
        second.save_to(second.file_path)
        main_window.add_qt_wallet(second)
        qt_wallets = [first, second]
        wallets = [qt_wallet.wallet for qt_wallet in qt_wallets]
        wallets[1].bdkwallet.reveal_addresses_to(bdk.KeychainKind.EXTERNAL, 50)
        funding_psbt = _mixed_psbt(wallets[0], wallets[1], other_open=True)
        points = []
        for wallet in wallets:
            item = next(
                item for item in SimplePSBT.from_psbt(funding_psbt).inputs if wallet.owns_psbt_input(item)
            )
            point = OutPoint.from_bdk(item.txin.previous_output)
            previous = item.previous_txout()
            assert previous
            utxo = PythonUtxo(
                str(bdk.Address.from_script(previous.script_pubkey, wallet.network)), point, previous
            )
            monkeypatch.setattr(wallet, "get_all_utxos", MagicMock(return_value=[utxo]))
            monkeypatch.setattr(
                wallet, "get_all_txos_dict", MagicMock(return_value={str(utxo.outpoint): utxo})
            )
            points.append(point)
        creator = qt_wallets[0].uitx_creator
        creator.import_wallet_utxos(wallets[1])
        qtbot.waitUntil(lambda: not creator._import_busy, timeout=10_000)
        assert points[1] in creator.foreign_inputs
        creator.set_selected_outpoints(set(points))
        destination = wallets[0].bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        creator.recipients.recipients = [Recipient(str(destination), 150_000)]
        psbt = wallets[0].create_psbt(creator.get_tx_ui_infos(use_categories=False)).psbt
        main_window.open_tx_like_in_tab(psbt)
        viewer = main_window.tab_wallets.currentWidget()
        assert isinstance(viewer, UITx_Viewer)

        for index, fingerprint in enumerate(
            [
                wallets[0].keystores[0].fingerprint,
                *[keystore.fingerprint for keystore in wallets[1].keystores],
            ]
        ):
            assert viewer.tx_singning_steps
            device_list = viewer.tx_singning_steps.stacked_widget.currentWidget()
            assert isinstance(device_list, TxSigningDeviceList)
            card = next(card for card in device_list.cards if card.device.fingerprint == fingerprint)
            card.expand()
            button = next(
                button for button in card.body.findChildren(QPushButton) if button.text() == "Sign now"
            )
            button.click()
            if index == 0:
                assert isinstance(viewer.data.data, bdk.Psbt)
                for item in SimplePSBT.from_psbt(viewer.data.data).inputs:
                    assert item.is_fully_signed() == wallets[index].owns_psbt_input(item)
            if index == 1:
                assert isinstance(viewer.data.data, bdk.Psbt)
                nested_input = next(
                    item
                    for item in SimplePSBT.from_psbt(viewer.data.data).inputs
                    if wallets[1].owns_psbt_input(item)
                )
                assert nested_input.fingerprint_has_signature(fingerprint)
                assert not nested_input.is_fully_signed()

        assert isinstance(viewer.data.data, bdk.Transaction)
        assert all(txin.witness for txin in viewer.data.data.input())


def _wallet(seed: str, wallet_id: str) -> MagicMock:
    wallet = make_wallet(seed, wallet_id)
    wallet.keystores = [create_keystore(seed, "m/84h/1h/0h", wallet_id)]
    descriptors = tuple(
        bdk.Descriptor(wallet.bdkwallet.public_descriptor(keychain), network_kind(NETWORK))
        for keychain in (bdk.KeychainKind.EXTERNAL, bdk.KeychainKind.INTERNAL)
    )
    wallet.multipath_descriptor = SimpleNamespace(to_single_descriptors=lambda: descriptors)
    wallet.get_mn_tuple.return_value = (1, 1)
    wallet.signer_fallback_name.side_effect = lambda index: wallet_id
    wallet.owns_psbt_input.side_effect = lambda simple_input: bool(
        (previous := simple_input.previous_txout()) and wallet.bdkwallet.is_mine(previous.script_pubkey)
    )
    return wallet


def _mixed_psbt(active: Wallet | MagicMock, other: Wallet | MagicMock, other_open: bool) -> bdk.Psbt:
    active_address = active.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    other_address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    local_tx = transaction([bytes(active_address.script_pubkey().to_bytes())])
    other_tx = transaction([bytes(other_address.script_pubkey().to_bytes())])
    active.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=local_tx, last_seen=1)])
    other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=other_tx, last_seen=1)])
    local_op = OutPoint(txid=local_tx.compute_txid(), vout=0)
    other_op = OutPoint(txid=other_tx.compute_txid(), vout=0)
    foreign = ForeignUtxo.from_outpoint(
        other_op,
        other_tx.output()[0],
        other_tx,
        [(other.id, other.bdkwallet)] if other_open else [],
        NETWORK,
    )
    return (
        bdk.TxBuilder()
        .add_utxo(local_op)
        .add_foreign_utxo(other_op, foreign.psbt_input, foreign.satisfaction_weight)
        .manually_selected_only()
        .add_recipient(active_address.script_pubkey(), bdk.Amount.from_sat(150_000))
        .finish(active.bdkwallet)
    )


def _steps(psbt: bdk.Psbt, wallets: list[Wallet | MagicMock], loop_in_thread, qtbot: QtBot) -> TxSigningSteps:
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    for wallet in wallets:
        wallet_functions.get_wallets.connect(lambda wallet=wallet: wallet, slot_name=wallet.id)
    viewer = SimpleNamespace(
        network=NETWORK,
        wallet_functions=wallet_functions,
        signals=signals,
        loop_in_thread=loop_in_thread,
        tr=lambda text: text,
        import_trusted_psbt=lambda psbt: None,
        tx_received=lambda tx: None,
    )
    viewer._normalize_fingerprint = UITx_Viewer._normalize_fingerprint
    viewer._normalize_fingerprints = UITx_Viewer._normalize_fingerprints.__get__(viewer, SimpleNamespace)
    viewer._wallet_signing_fingerprints = UITx_Viewer._wallet_signing_fingerprints.__get__(
        viewer, SimpleNamespace
    )
    viewer.enrich_simple_psbt_with_wallet_data = UITx_Viewer.enrich_simple_psbt_with_wallet_data.__get__(
        viewer, SimpleNamespace
    )
    importers = UITx_Viewer.get_combined_signature_importers(viewer, psbt)
    steps = TxSigningSteps(importers, psbt, NETWORK, wallet_functions, loop_in_thread)
    qtbot.addWidget(steps)
    steps.show()
    return steps


@pytest.mark.parametrize("first_signer", [0, 1])
def test_signing_two_open_wallets_updates_existing_signer_card(
    qtbot: QtBot, loop_in_thread, first_signer: int
) -> None:
    # BDK shuffles inputs, so generate until the foreign input is first.
    for _ in range(50):
        active, other = [_wallet(seed, name) for seed, name in zip(SEEDS, ("active", "other"), strict=True)]
        psbt = _mixed_psbt(active, other, other_open=True)
        inputs = SimplePSBT.from_psbt(psbt).inputs
        if other.owns_psbt_input(inputs[0]):
            break
    assert other.owns_psbt_input(inputs[0]) and active.owns_psbt_input(inputs[1])
    before = _steps(psbt, [active, other], loop_in_thread, qtbot)
    assert before.count() == 2
    wallets = [active, other]
    first_list = before.stacked_widget.currentWidget()
    assert isinstance(first_list, TxSigningDeviceList)
    first_card = next(
        card
        for card in first_list.cards
        if card.device.fingerprint == wallets[first_signer].keystores[0].fingerprint
    )
    first_card.expand()
    first_button = next(
        button for button in first_card.body.findChildren(QPushButton) if button.text() == "Sign now"
    )
    first_importer = first_card._wallet_importer()
    assert first_importer and first_importer.wallet_id == wallets[first_signer].id
    with qtbot.waitSignal(first_importer.signal_signature_added, timeout=5_000) as signal:
        first_button.click()
    psbt = signal.args[0]
    for item in SimplePSBT.from_psbt(psbt).inputs:
        assert item.is_fully_signed() == wallets[first_signer].owns_psbt_input(item)
    steps = _steps(psbt, [active, other], loop_in_thread, qtbot)
    assert steps.count() == 2
    assert steps.current_index() == 1
    device_list = steps.stacked_widget.currentWidget()
    assert isinstance(device_list, TxSigningDeviceList)
    assert len(device_list.cards) == 2
    devices = {card.device.fingerprint: card.device for card in device_list.cards}
    assert devices[wallets[first_signer].keystores[0].fingerprint].signature_available
    assert not devices[wallets[1 - first_signer].keystores[0].fingerprint].signature_available
    signed_card = next(card for card in device_list.cards if card.device.signature_available)
    assert signed_card.header_status.textLabel.text() == "Signed"
    remaining_card = next(card for card in device_list.cards if not card.device.signature_available)
    remaining_card.expand()
    sign_button = next(
        button for button in remaining_card.body.findChildren(QPushButton) if button.text() == "Sign now"
    )
    remaining_importer = remaining_card._wallet_importer()
    assert remaining_importer and remaining_importer.wallet_id == wallets[1 - first_signer].id
    with qtbot.waitSignal(remaining_importer.signal_signature_added, timeout=5_000) as signal:
        sign_button.click()
    assert all(item.is_fully_signed() for item in SimplePSBT.from_psbt(signal.args[0]).inputs)


@pytest.mark.parametrize("signer_index", [0, 1])
def test_seed_card_signs_only_its_fingerprint_in_multisig_wallet(
    qtbot: QtBot, loop_in_thread, test_config, signer_index: int
) -> None:
    wallet = _multisig_wallet(signers=2, test_config=test_config, threshold=2)
    address = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding_tx = transaction([bytes(address.script_pubkey().to_bytes())])
    wallet.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding_tx, last_seen=1)])
    psbt = (
        bdk.TxBuilder()
        .add_utxo(OutPoint(txid=funding_tx.compute_txid(), vout=0))
        .manually_selected_only()
        .add_recipient(address.script_pubkey(), bdk.Amount.from_sat(50_000))
        .finish(wallet.bdkwallet)
    )
    steps = _steps(psbt, [wallet], loop_in_thread, qtbot)
    device_list = steps.stacked_widget.currentWidget()
    assert isinstance(device_list, TxSigningDeviceList)
    keystore = wallet.keystores[signer_index]
    card = next(card for card in device_list.cards if card.device.fingerprint == keystore.fingerprint)
    card.expand()
    button = next(button for button in card.body.findChildren(QPushButton) if button.text() == "Sign now")
    importer = card._wallet_importer()
    assert importer
    with qtbot.waitSignal(importer.signal_signature_added, timeout=5_000) as signal:
        button.click()
    signed_input = SimplePSBT.from_psbt(signal.args[0]).inputs[0]
    assert signed_input.fingerprint_has_signature(keystore.fingerprint)
    assert not signed_input.fingerprint_has_signature(wallet.keystores[1 - signer_index].fingerprint)


def test_unsigned_input_without_known_signer_has_a_signing_card(qtbot: QtBot, loop_in_thread) -> None:
    active, other = [_wallet(seed, name) for seed, name in zip(SEEDS, ("active", "other"), strict=True)]
    psbt = _mixed_psbt(active, other, other_open=False)
    steps = _steps(psbt, [active], loop_in_thread, qtbot)
    assert steps.count() == 2
    devices = steps.signing_devices
    assert len(devices) == 2
    assert any(device.fingerprint == active.keystores[0].fingerprint for device in devices)
    assert any(not device.fingerprint for device in devices)
    active.bdkwallet.sign(psbt)
    signed_steps = _steps(psbt, [active], loop_in_thread, qtbot)
    assert signed_steps.count() == 2
    assert signed_steps.current_index() == 1
    device_list = signed_steps.stacked_widget.currentWidget()
    assert isinstance(device_list, TxSigningDeviceList)
    assert len(device_list.cards) == 2
    assert sum(card.device.signature_available for card in device_list.cards) == 1
    unknown_card = next(card for card in device_list.cards if not card.device.fingerprint)
    assert not unknown_card.device.signature_available
    unknown_card.expand()
    assert any(button.text() == "Show QR Code" for button in unknown_card.body.findChildren(QPushButton))
    assert other.bdkwallet.sign(psbt)
