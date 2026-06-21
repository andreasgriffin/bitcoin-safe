#
# Bitcoin Safe
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

from dataclasses import dataclass
from types import SimpleNamespace

import bdkpython as bdk
from bitcoin_qr_tools.unified_encoder import QrExportTypes
from PyQt6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.signer_ui import SignedUI
from bitcoin_safe.gui.qt.tx_signing_steps import (
    ExportImportUI,
    SignerUI,
    SigningDevice,
    TxSigningDeviceCard,
    TxSigningDeviceGuidance,
    TxSigningDeviceList,
    TxSigningHeaderState,
    TxSigningSteps,
    allows_psbt_qr_type_choice,
    preferred_psbt_qr_type,
)
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.hardware_signers import HardwareSigners
from bitcoin_safe.psbt_util import InputGroup, PartialSig, PubKeyInfo, SimpleInput, SimplePSBT
from bitcoin_safe.signals import Signals, WalletFunctions
from bitcoin_safe.signer import (
    SignatureImporterFile,
    SignatureImporterQR,
    SignatureImporterWallet,
    SignerIdentity,
)

from ...non_gui.test_psbt_util import (
    mixed_input_no_signatures_partially_signed,
    tr_psbt_singlesig,
)
from ...non_gui.utils import create_test_seed_keystores


def test_krux_psbt_qr_prefers_bbqr() -> None:
    assert preferred_psbt_qr_type(HardwareSigners.krux_diy) == QrExportTypes.bbqr


def test_generic_signer_allows_psbt_qr_type_choice() -> None:
    assert allows_psbt_qr_type_choice(HardwareSigners.generic)
    assert not allows_psbt_qr_type_choice(HardwareSigners.krux_diy)


@dataclass
class DummyWallet:
    id: str
    keystores: list

    def signer_fallback_name(self, i: int) -> str:
        return f"Signer {i + 1}"


class DummyDescriptor:
    def to_string_with_secret(self) -> str:
        return "descriptor"


class DummyMultipathDescriptor:
    def to_single_descriptors(self) -> tuple[DummyDescriptor, DummyDescriptor]:
        return DummyDescriptor(), DummyDescriptor()


def test_signed_ui_is_shown_on_matching_device_card(qtbot: QtBot, loop_in_thread, monkeypatch) -> None:
    signals = Signals()
    keystores = create_test_seed_keystores(
        signers=2,
        key_origins=["m/48h/1h/0h/2h", "m/48h/1h/1h/2h"],
        network=bdk.Network.REGTEST,
    )
    keystores[0].hardware_signer_id = HardwareSigners.jade.id
    keystores[1].hardware_signer_id = HardwareSigners.passport.id

    wallet = DummyWallet(id="multisig", keystores=keystores)
    signed_importer = SignatureImporterFile(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label=keystores[0].fingerprint,
        signer_identities=[SignerIdentity(id=keystores[0].fingerprint, fingerprint=keystores[0].fingerprint)],
        signatures={0: PartialSig(signature="3044deadbeef", sighash_type="ALL")},
    )
    unsigned_importer = SignatureImporterQR(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label=keystores[1].fingerprint,
        signer_identities=[SignerIdentity(id=keystores[1].fingerprint, fingerprint=keystores[1].fingerprint)],
    )
    monkeypatch.setattr(TxSigningSteps, "_involved_wallets", lambda self: [wallet])

    widget = TxSigningSteps(
        signature_importer_dict={"wallet.0": [signed_importer, unsigned_importer]},
        psbt=tr_psbt_singlesig,
        network=bdk.Network.REGTEST,
        wallet_functions=WalletFunctions(signals),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)
    assert len(step_widget.cards) == 2

    signed_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[0].fingerprint
    )
    unsigned_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[1].fingerprint
    )

    signed_card.expand()
    signed_ui = signed_card.body.findChild(SignedUI)
    assert signed_ui
    assert keystores[0].fingerprint in signed_ui.edit_signature.toPlainText()
    assert unsigned_card.body.findChild(SignedUI) is None
    assert signed_card.header_status.textLabel.text() == "Signed"


def test_mixed_steps_keep_device_cards_instead_of_step_summary(
    qtbot: QtBot, loop_in_thread, monkeypatch
) -> None:
    signals = Signals()
    keystores = create_test_seed_keystores(
        signers=2,
        key_origins=["m/48h/1h/0h/2h", "m/48h/1h/1h/2h"],
        network=bdk.Network.REGTEST,
    )
    wallet = DummyWallet(id="multisig", keystores=keystores)
    signed_importer = SignatureImporterFile(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label=keystores[0].fingerprint,
        signer_identities=[SignerIdentity(id=keystores[0].fingerprint, fingerprint=keystores[0].fingerprint)],
        signatures={0: PartialSig(signature="3044deadbeef", sighash_type="ALL")},
    )
    unsigned_importer = SignatureImporterQR(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label=keystores[1].fingerprint,
        signer_identities=[SignerIdentity(id=keystores[1].fingerprint, fingerprint=keystores[1].fingerprint)],
    )
    monkeypatch.setattr(TxSigningSteps, "_involved_wallets", lambda self: [wallet])

    widget = TxSigningSteps(
        signature_importer_dict={
            "wallet.0": [signed_importer],
            "wallet.1": [unsigned_importer],
        },
        psbt=tr_psbt_singlesig,
        network=bdk.Network.REGTEST,
        wallet_functions=WalletFunctions(signals),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    signed_step_widget = widget.stacked_widget.widget(0)
    unsigned_step_widget = widget.stacked_widget.widget(1)

    assert isinstance(unsigned_step_widget, TxSigningDeviceList)
    assert not isinstance(signed_step_widget, TxSigningDeviceList)

    unsigned_card = next(
        card for card in unsigned_step_widget.cards if card.device.fingerprint == keystores[1].fingerprint
    )
    unsigned_card.expand()

    assert unsigned_card.body.findChild(SignedUI) is None
    assert unsigned_card.button_sign.text() == "Sign with this device"
    assert {button.text() for button in unsigned_card.body.findChildren(QPushButton)} == {"Show QR Code"}

    widget.set_current_index(0)
    signed_step_widget = widget.stacked_widget.widget(0)
    assert isinstance(signed_step_widget, TxSigningDeviceList)


def test_non_seed_wallet_importer_keeps_hardware_signer_device_identity(qtbot: QtBot, loop_in_thread) -> None:
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    keystores = create_test_seed_keystores(
        signers=1,
        key_origins=["m/48h/1h/0h/2h"],
        network=bdk.Network.REGTEST,
    )
    keystore = keystores[0]
    keystore.hardware_signer_id = HardwareSigners.jade.id
    keystore.mnemonic = None
    wallet = DummyWallet(id="multisig", keystores=[keystore])
    wallet_functions.get_wallets.connect(lambda: wallet)

    qr_importer = SignatureImporterQR(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label=keystore.fingerprint,
        signer_identities=[SignerIdentity(id=keystore.fingerprint, fingerprint=keystore.fingerprint)],
    )

    widget = TxSigningSteps(
        signature_importer_dict={"wallet.0": [qr_importer]},
        psbt=tr_psbt_singlesig,
        network=bdk.Network.REGTEST,
        wallet_functions=wallet_functions,
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    assert len(widget.signing_devices) == 1
    device = widget.signing_devices[0]
    assert device.fingerprint == keystore.fingerprint
    assert device.hardware_signer == HardwareSigners.jade
    assert not device.has_seed

    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)
    assert len(step_widget.cards) == 1

    card = step_widget.cards[0]
    assert card.header_title.text() == HardwareSigners.jade.display_name
    assert card.device.hardware_signer == HardwareSigners.jade

    card.expand()

    assert {button.text() for button in card.body.findChildren(QPushButton)} == {"Show QR Code"}


def _make_qr_device_card(
    qtbot: QtBot,
    loop_in_thread,
    hardware_signer=HardwareSigners.jade,
) -> TxSigningDeviceCard:
    signals = Signals()
    qr_importer = SignatureImporterQR(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label="836DA7F8",
        signer_identities=[SignerIdentity(id="836DA7F8", fingerprint="836DA7F8")],
    )
    card = TxSigningDeviceCard(
        device=SigningDevice(
            fingerprint="836DA7F8",
            label=hardware_signer.display_name,
            hardware_signer=hardware_signer,
            wallet_ids=["multisig with jade"],
        ),
        signature_importers=[qr_importer],
        psbt=tr_psbt_singlesig,
        network=bdk.Network.REGTEST,
        wallet_functions=WalletFunctions(signals),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(card)
    card.show()
    card.expand()
    return card


def _make_file_device_card(qtbot: QtBot, loop_in_thread) -> TxSigningDeviceCard:
    signals = Signals()
    file_importer = SignatureImporterFile(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label="836DA7F8",
        signer_identities=[SignerIdentity(id="836DA7F8", fingerprint="836DA7F8")],
    )
    card = TxSigningDeviceCard(
        device=SigningDevice(
            fingerprint="836DA7F8",
            label=HardwareSigners.jade.display_name,
            hardware_signer=HardwareSigners.jade,
            wallet_ids=["multisig with jade"],
        ),
        signature_importers=[file_importer],
        psbt=tr_psbt_singlesig,
        network=bdk.Network.REGTEST,
        wallet_functions=WalletFunctions(signals),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(card)
    card.show()
    card.expand()
    return card


def _make_guided_steps_widget(
    qtbot: QtBot,
    loop_in_thread,
    monkeypatch,
    wizard_send_test_index: int,
    group_indexes: list[list[int]],
    signed_indexes: tuple[int, ...] = (),
    signer_count: int = 3,
) -> tuple[TxSigningSteps, list]:
    signals = Signals()
    keystores = create_test_seed_keystores(
        signers=signer_count,
        key_origins=[f"m/48h/1h/{i}h/2h" for i in range(signer_count)],
        network=bdk.Network.REGTEST,
    )
    wallet = DummyWallet(id="multisig", keystores=keystores)
    signer_groups = [[keystores[index].fingerprint for index in group] for group in group_indexes]
    qr_importer = SignatureImporterQR(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label=keystores[0].fingerprint,
        signer_identities=[SignerIdentity(id=keystores[0].fingerprint, fingerprint=keystores[0].fingerprint)],
    )
    signature_importers: list = [qr_importer]
    for index in signed_indexes:
        fingerprint = keystores[index].fingerprint
        signature_importers.append(
            SignatureImporterFile(
                network=bdk.Network.REGTEST,
                close_all_video_widgets=signals.close_all_video_widgets,
                loop_in_thread=loop_in_thread,
                display_label=fingerprint,
                signer_identities=[SignerIdentity(id=fingerprint, fingerprint=fingerprint)],
                signatures={0: PartialSig(signature="3044deadbeef", sighash_type="ALL")},
            )
        )

    monkeypatch.setattr(TxSigningSteps, "_involved_wallets", lambda self: [wallet])
    widget = TxSigningSteps(
        signature_importer_dict={"wallet.0": signature_importers},
        psbt=tr_psbt_singlesig,
        network=bdk.Network.REGTEST,
        wallet_functions=WalletFunctions(signals),
        loop_in_thread=loop_in_thread,
        wizard_send_test_signer_groups=signer_groups,
        wizard_send_test_index=wizard_send_test_index,
    )
    qtbot.addWidget(widget)
    widget.show()
    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)
    return widget, keystores


def test_show_qr_code_opens_popup_and_shows_import_only_detail(qtbot: QtBot, loop_in_thread) -> None:
    card = _make_qr_device_card(qtbot, loop_in_thread)

    button_show_qr = next(
        button for button in card.body.findChildren(QPushButton) if button.text() == "Show QR Code"
    )
    button_show_qr.click()

    export_widget = card.qr_export_widget
    assert export_widget
    qtbot.waitUntil(export_widget.isVisible)

    assert card.body.findChild(ExportImportUI) is None

    signer_ui = card.body.findChild(SignerUI)
    assert signer_ui
    assert signer_ui.button.text() == "Scan QR code"
    assert signer_ui.button.isDefault()

    body_button_texts = {button.text() for button in card.body.findChildren(QPushButton)}
    assert body_button_texts == {"Scan QR code"}
    export_widget.close()


def test_current_send_test_target_keeps_sign_button(qtbot: QtBot, loop_in_thread, monkeypatch) -> None:
    widget, keystores = _make_guided_steps_widget(
        qtbot=qtbot,
        loop_in_thread=loop_in_thread,
        monkeypatch=monkeypatch,
        wizard_send_test_index=0,
        group_indexes=[[0, 1], [1, 2]],
    )
    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)

    current_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[0].fingerprint
    )
    future_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[2].fingerprint
    )

    assert current_card.button_sign.isVisible()
    assert current_card.button_sign.text() == "Sign with this device"
    assert not current_card.header_status.isVisible()
    assert future_card.header_status.isVisible()
    assert future_card.header_status.textLabel.text() == "Keep ready for test 2"
    assert (
        future_card.header_status.toolTip()
        == "This signer is needed in send test 2. Do not sign with it yet."
    )
    assert future_card.header_status.click_url is None


def test_fallback_verified_candidates_remain_expandable_while_overlap_slot_is_open(
    qtbot: QtBot, loop_in_thread, monkeypatch
) -> None:
    widget, keystores = _make_guided_steps_widget(
        qtbot=qtbot,
        loop_in_thread=loop_in_thread,
        monkeypatch=monkeypatch,
        wizard_send_test_index=1,
        group_indexes=[[0, 1], [1, 2]],
    )
    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)

    previous_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[0].fingerprint
    )
    overlap_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[1].fingerprint
    )
    current_new_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[2].fingerprint
    )

    assert previous_card.header_status.isVisible()
    assert previous_card.header_status.textLabel.text() == "Test verified"
    assert previous_card.button_sign.isHidden()
    assert previous_card.guidance.expandable
    assert overlap_card.button_sign.isVisible()
    assert overlap_card.button_sign.text() == "Sign with this device"
    assert not overlap_card.header_status.isVisible()
    assert current_new_card.button_sign.isVisible()
    assert current_new_card.button_sign.text() == "Sign with this device"


def test_verified_candidate_locks_after_another_verified_signer_signed(
    qtbot: QtBot, loop_in_thread, monkeypatch
) -> None:
    widget, keystores = _make_guided_steps_widget(
        qtbot=qtbot,
        loop_in_thread=loop_in_thread,
        monkeypatch=monkeypatch,
        wizard_send_test_index=1,
        group_indexes=[[0, 1], [1, 2]],
        signed_indexes=(0,),
    )
    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)

    remaining_verified_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[1].fingerprint
    )
    current_new_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[2].fingerprint
    )

    assert remaining_verified_card.header_status.isVisible()
    assert remaining_verified_card.header_status.textLabel.text() == "Test verified"
    assert not remaining_verified_card.guidance.expandable
    assert remaining_verified_card.button_sign.isHidden()
    assert current_new_card.button_sign.isVisible()


def test_preferred_verified_current_group_signers_show_sign_button_in_4_of_6(
    qtbot: QtBot, loop_in_thread, monkeypatch
) -> None:
    widget, keystores = _make_guided_steps_widget(
        qtbot=qtbot,
        loop_in_thread=loop_in_thread,
        monkeypatch=monkeypatch,
        wizard_send_test_index=1,
        group_indexes=[[0, 1, 2, 3], [2, 3, 4, 5]],
        signer_count=6,
    )
    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)

    fallback_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[0].fingerprint
    )
    preferred_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[2].fingerprint
    )
    current_new_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[4].fingerprint
    )

    assert fallback_card.header_status.isVisible()
    assert fallback_card.header_status.textLabel.text() == "Test verified"
    assert fallback_card.guidance.expandable
    assert preferred_card.button_sign.isVisible()
    assert preferred_card.button_sign.text() == "Sign with this device"
    assert current_new_card.button_sign.isVisible()


def test_verified_signers_without_overlap_slots_stay_locked(
    qtbot: QtBot, loop_in_thread, monkeypatch
) -> None:
    widget, keystores = _make_guided_steps_widget(
        qtbot=qtbot,
        loop_in_thread=loop_in_thread,
        monkeypatch=monkeypatch,
        wizard_send_test_index=1,
        group_indexes=[[0], [1], [2], [3], [4]],
        signer_count=5,
    )
    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)

    verified_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[0].fingerprint
    )
    current_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[1].fingerprint
    )

    assert verified_card.header_status.isVisible()
    assert verified_card.header_status.textLabel.text() == "Test verified"
    assert not verified_card.guidance.expandable
    assert current_card.button_sign.isVisible()


def test_signed_device_guidance_overrides_send_now(qtbot: QtBot, loop_in_thread, monkeypatch) -> None:
    widget, keystores = _make_guided_steps_widget(
        qtbot=qtbot,
        loop_in_thread=loop_in_thread,
        monkeypatch=monkeypatch,
        wizard_send_test_index=1,
        group_indexes=[[0, 1], [1, 2]],
        signed_indexes=(1,),
    )
    step_widget = widget.stacked_widget.widget(0)
    assert isinstance(step_widget, TxSigningDeviceList)

    signed_card = next(
        card for card in step_widget.cards if card.device.fingerprint == keystores[1].fingerprint
    )

    assert signed_card.header_status.isVisible()
    assert signed_card.header_status.textLabel.text() == "Signed"
    assert signed_card.button_sign.isHidden()


def test_read_only_guidance_card_does_not_expand(qtbot: QtBot, loop_in_thread) -> None:
    signals = Signals()
    qr_importer = SignatureImporterQR(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label="836DA7F8",
        signer_identities=[SignerIdentity(id="836DA7F8", fingerprint="836DA7F8")],
    )
    card = TxSigningDeviceCard(
        device=SigningDevice(
            fingerprint="836DA7F8",
            label=HardwareSigners.jade.display_name,
            hardware_signer=HardwareSigners.jade,
        ),
        signature_importers=[qr_importer],
        psbt=tr_psbt_singlesig,
        network=bdk.Network.REGTEST,
        wallet_functions=WalletFunctions(signals),
        loop_in_thread=loop_in_thread,
        guidance=TxSigningDeviceGuidance(
            state=TxSigningHeaderState.keep_ready,
            next_test_number=2,
            expandable=False,
        ),
    )
    qtbot.addWidget(card)
    card.show()

    card.expand()

    assert not card.is_expanded
    assert card.header_status.textLabel.text() == "Keep ready for test 2"
    assert card.header_status.toolTip() == "This signer is needed in send test 2. Do not sign with it yet."


def test_generic_signer_qr_popup_keeps_qr_type_choice_visible(qtbot: QtBot, loop_in_thread) -> None:
    card = _make_qr_device_card(qtbot, loop_in_thread, hardware_signer=HardwareSigners.generic)

    button_show_qr = next(
        button for button in card.body.findChildren(QPushButton) if button.text() == "Show QR Code"
    )
    button_show_qr.click()

    export_widget = card.qr_export_widget
    assert export_widget
    qtbot.waitUntil(export_widget.isVisible)
    assert export_widget.combo_qr_type.isVisible()
    export_widget.close()


def test_detail_widget_is_vertically_centered(qtbot: QtBot, loop_in_thread) -> None:
    card = _make_file_device_card(qtbot, loop_in_thread)
    card._show_file_detail()

    assert card.body_layout.count() == 3
    assert card.body_layout.itemAt(0).spacerItem() is not None
    assert card.body_layout.itemAt(1).widget() is not None
    assert card.body_layout.itemAt(2).spacerItem() is not None


def test_grouped_display_label_does_not_create_synthetic_device(
    qtbot: QtBot, loop_in_thread, monkeypatch
) -> None:
    signals = Signals()
    keystores = create_test_seed_keystores(
        signers=1,
        key_origins=["m/48h/1h/0h/2h"],
        network=bdk.Network.REGTEST,
    )
    wallet = DummyWallet(id="multisig", keystores=keystores)
    grouped_importer = SignatureImporterFile(
        network=bdk.Network.REGTEST,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        display_label="43666, 42645, 45757",
        signer_identities=[SignerIdentity(id=keystores[0].fingerprint, fingerprint=keystores[0].fingerprint)],
        signatures={0: PartialSig(signature="3044deadbeef", sighash_type="ALL")},
    )
    monkeypatch.setattr(TxSigningSteps, "_involved_wallets", lambda self: [wallet])

    widget = TxSigningSteps(
        signature_importer_dict={"wallet.0": [grouped_importer]},
        psbt=tr_psbt_singlesig,
        network=bdk.Network.REGTEST,
        wallet_functions=WalletFunctions(signals),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    assert [device.fingerprint for device in widget.signing_devices] == [keystores[0].fingerprint]
    assert all(device.fingerprint != "43666, 42645, 45757" for device in widget.signing_devices)
    assert widget.signing_devices[0].signatures == {
        0: PartialSig(signature="3044deadbeef", sighash_type="ALL")
    }


def test_grouped_wallet_importer_only_uses_wallet_signable_unsigned_fingerprints(
    monkeypatch, loop_in_thread
) -> None:
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    keystores = create_test_seed_keystores(
        signers=3,
        key_origins=["m/48h/1h/0h/2h", "m/48h/1h/1h/2h", "m/48h/1h/2h/2h"],
        network=bdk.Network.REGTEST,
    )
    keystores[1].mnemonic = None
    wallet = DummyWallet(id="seed-wallet", keystores=keystores[:2])
    wallet.multipath_descriptor = DummyMultipathDescriptor()
    wallet_functions.get_wallets.connect(lambda: wallet)
    monkeypatch.setattr("bitcoin_safe.signer.SoftwareSigner", lambda **kwargs: object())

    fake_viewer = SimpleNamespace(
        network=bdk.Network.REGTEST,
        wallet_functions=wallet_functions,
        signals=signals,
        loop_in_thread=loop_in_thread,
        tr=lambda text: text,
        import_trusted_psbt=lambda psbt: None,
        tx_received=lambda tx: None,
    )
    fake_viewer._normalize_fingerprint = UITx_Viewer._normalize_fingerprint
    fake_viewer._normalize_fingerprints = UITx_Viewer._normalize_fingerprints.__get__(
        fake_viewer, SimpleNamespace
    )
    fake_viewer._wallet_signing_fingerprints = UITx_Viewer._wallet_signing_fingerprints.__get__(
        fake_viewer, SimpleNamespace
    )
    fake_viewer.enrich_simple_psbt_with_wallet_data = lambda simple_psbt: simple_psbt
    simple_psbt = SimplePSBT(
        txid="grouped",
        inputs=[
            SimpleInput(
                txin=tr_psbt_singlesig.extract_tx().input()[0],
                pubkeys=[
                    PubKeyInfo(pubkey="pubkey-1", fingerprint=keystores[0].fingerprint),
                    PubKeyInfo(pubkey="pubkey-2", fingerprint=keystores[1].fingerprint),
                    PubKeyInfo(pubkey="pubkey-3", fingerprint=keystores[2].fingerprint),
                ],
                m_of_n=(1, 3),
            )
        ],
    )
    monkeypatch.setattr(SimplePSBT, "from_psbt", classmethod(lambda cls, psbt: simple_psbt))
    monkeypatch.setattr(
        SimplePSBT,
        "group_inputs",
        lambda self: [
            InputGroup(
                group_id="43666, 42645, 45757",
                inputs=self.inputs,
                input_indices=[0],
                wallet_id=None,
                m_of_n=(1, 3),
                signer_identifiers={
                    keystores[0].fingerprint: self.inputs[0].pubkeys[0],
                    keystores[1].fingerprint: self.inputs[0].pubkeys[1],
                    keystores[2].fingerprint: self.inputs[0].pubkeys[2],
                },
            )
        ],
    )

    importers = UITx_Viewer.get_combined_signature_importers(fake_viewer, tr_psbt_singlesig)
    signer_list = importers["43666, 42645, 45757.0"]

    wallet_importer = next(
        importer for importer in signer_list if isinstance(importer, SignatureImporterWallet)
    )

    assert wallet_importer.display_label == "43666, 42645, 45757"
    assert wallet_importer.signing_fingerprints == [keystores[0].fingerprint]


def test_partially_signed_psbt_keeps_stable_steps_and_signed_cards(qtbot: QtBot, loop_in_thread) -> None:
    signals = Signals()
    wallet_functions = WalletFunctions(signals)

    fake_viewer = SimpleNamespace(
        network=bdk.Network.REGTEST,
        wallet_functions=wallet_functions,
        signals=signals,
        loop_in_thread=loop_in_thread,
        tr=lambda text: text,
        import_trusted_psbt=lambda psbt: None,
        tx_received=lambda tx: None,
    )
    fake_viewer._normalize_fingerprint = UITx_Viewer._normalize_fingerprint
    fake_viewer._normalize_fingerprints = UITx_Viewer._normalize_fingerprints.__get__(
        fake_viewer, SimpleNamespace
    )
    fake_viewer._wallet_signing_fingerprints = UITx_Viewer._wallet_signing_fingerprints.__get__(
        fake_viewer, SimpleNamespace
    )
    fake_viewer.enrich_simple_psbt_with_wallet_data = lambda simple_psbt: simple_psbt

    importers = UITx_Viewer.get_combined_signature_importers(
        fake_viewer, mixed_input_no_signatures_partially_signed
    )

    assert len(importers) == 4

    widget = TxSigningSteps(
        signature_importer_dict=importers,
        psbt=mixed_input_no_signatures_partially_signed,
        network=bdk.Network.REGTEST,
        wallet_functions=wallet_functions,
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    assert len(widget.signing_devices) == 5
    assert len([device for device in widget.signing_devices if device.signature_available]) == 2
    assert widget.current_index() == 2

    assert not isinstance(widget.stacked_widget.widget(0), TxSigningDeviceList)

    widget.set_current_index(0)
    signed_step_widget = widget.stacked_widget.widget(0)
    assert isinstance(signed_step_widget, TxSigningDeviceList)

    signed_card = next(card for card in signed_step_widget.cards if card.device.signature_available)
    signed_card.expand()

    signed_ui = signed_card.body.findChild(SignedUI)
    assert signed_ui
    assert "30440220044718089b2bd3f84d52370b9c7f0bf5" in signed_ui.edit_signature.toPlainText()
