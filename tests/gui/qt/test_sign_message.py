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

from types import SimpleNamespace

import bdkpython as bdk
from PyQt6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.sign_message import SignMessageBase, _SignTab
from bitcoin_safe.signals import Signals, UpdateFilter, UpdateFilterReason, WalletFunctions
from bitcoin_safe.signer import SeedSignOption

from ...non_gui.test_seed_sign_message import _wallet


class DummySignMessage(SignMessageBase):
    def __init__(self, network: bdk.Network, signals: Signals, loop_in_thread) -> None:
        self.follow_up_visibility_states: list[bool] = []
        super().__init__(
            network=network,
            signals_min=signals,
            close_all_video_widgets=signals.close_all_video_widgets,
            loop_in_thread=loop_in_thread,
            parent=None,
        )
        self.grid_layout.addWidget(self.sign_qr_button, 0, 0)

    def get_message(self) -> str:
        return "hello bitcoin safe"

    def get_bip32_path(self) -> str:
        return "m/84h/1h/0h/0/0"

    def dialog_open_qr_scanner(self) -> None:
        self.follow_up_visibility_states.append(self.sign_qr_button.export_qr_widget.isVisible())


def _make_sign_message_widget(qtbot: QtBot, loop_in_thread) -> DummySignMessage:
    signals = Signals()
    widget = DummySignMessage(network=bdk.Network.REGTEST, signals=signals, loop_in_thread=loop_in_thread)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_sign_message_qr_popup_shows_follow_up_scan_group(qtbot: QtBot, loop_in_thread) -> None:
    widget = _make_sign_message_widget(qtbot, loop_in_thread)

    widget.sign_qr_button.show_export_widget()
    export_widget = widget.sign_qr_button.export_qr_widget
    qtbot.waitUntil(export_widget.isVisible)

    follow_up_group = next(
        group
        for group in export_widget.findChildren(type(export_widget.group_qr))
        if group.title() == "2. Detect signed message"
    )
    assert follow_up_group
    scan_button = next(
        button for button in follow_up_group.findChildren(QPushButton) if button.text() == "Scan QR code"
    )
    assert scan_button
    export_widget.close()


def test_sign_message_qr_follow_up_closes_popup_before_opening_scanner(qtbot: QtBot, loop_in_thread) -> None:
    widget = _make_sign_message_widget(qtbot, loop_in_thread)

    widget.sign_qr_button.show_export_widget()
    export_widget = widget.sign_qr_button.export_qr_widget
    qtbot.waitUntil(export_widget.isVisible)

    follow_up_group = next(
        group
        for group in export_widget.findChildren(type(export_widget.group_qr))
        if group.title() == "2. Detect signed message"
    )
    scan_button = next(
        button for button in follow_up_group.findChildren(QPushButton) if button.text() == "Scan QR code"
    )

    scan_button.click()
    qtbot.waitUntil(lambda: bool(widget.follow_up_visibility_states))

    assert widget.follow_up_visibility_states == [False]


def test_sign_message_manual_qr_popup_close_does_not_open_scanner(qtbot: QtBot, loop_in_thread) -> None:
    widget = _make_sign_message_widget(qtbot, loop_in_thread)

    widget.sign_qr_button.show_export_widget()
    export_widget = widget.sign_qr_button.export_qr_widget
    qtbot.waitUntil(export_widget.isVisible)

    export_widget.close()
    qtbot.wait(50)

    assert not widget.follow_up_visibility_states


def test_seed_button_hidden_without_seed_sign_options(qtbot: QtBot, loop_in_thread) -> None:
    widget = _make_sign_message_widget(qtbot, loop_in_thread)

    assert not widget.sign_seed_button.isVisibleTo(widget)
    assert widget.seed_menu.actions() == []


class _FakeSeedSigner:
    def __init__(self, signature: str = "") -> None:
        self.signature = signature
        self.calls: list[tuple[str, str]] = []

    def sign_message(self, message: str, bip32_path: str) -> str:
        self.calls.append((message, bip32_path))
        return self.signature

    def get_fingerprint(self) -> str:
        return "00000000"


def _option(name: str, signer: _FakeSeedSigner, bip32_path: str = "m/84h/1h/0h/0/0") -> SeedSignOption:
    return SeedSignOption(signer_label=name, signer=signer, bip32_path=bip32_path)  # type: ignore[arg-type]


def test_seed_menu_has_one_entry_per_option(qtbot: QtBot, loop_in_thread) -> None:
    widget = _make_sign_message_widget(qtbot, loop_in_thread)

    widget.set_seed_sign_options([_option("A", _FakeSeedSigner()), _option("B", _FakeSeedSigner())])
    assert widget.sign_seed_button.isVisibleTo(widget)
    assert [action.text() for action in widget.seed_menu.actions()] == ["A - 00000000", "B - 00000000"]

    widget.set_seed_sign_options([_option("C", _FakeSeedSigner())])
    assert widget.sign_seed_button.isVisibleTo(widget)
    assert [action.text() for action in widget.seed_menu.actions()] == ["C - 00000000"]

    widget.set_seed_sign_options([])
    assert not widget.sign_seed_button.isVisibleTo(widget)


def test_seed_menu_action_signs_with_its_own_option(qtbot: QtBot, loop_in_thread) -> None:
    widget = _make_sign_message_widget(qtbot, loop_in_thread)
    first = _FakeSeedSigner(signature="signed-by-first")
    second = _FakeSeedSigner(signature="signed-by-second")
    widget.set_seed_sign_options(
        [_option("first", first, "m/84h/1h/0h/0/0"), _option("second", second, "m/85h/1h/0h/0/3")]
    )
    widget.get_message = lambda: "hello bitcoin safe"  # type: ignore[method-assign]

    emitted: list[str] = []
    widget.signal_signed_message.connect(emitted.append)
    widget.seed_menu.actions()[1].trigger()

    assert first.calls == []
    assert second.calls == [("hello bitcoin safe", "m/85h/1h/0h/0/3")]
    assert emitted == ["signed-by-second"]


def test_sign_tab_seed_button_follows_entered_address(qtbot: QtBot, test_config, loop_in_thread) -> None:
    wallet = _wallet(signers=1, test_config=test_config)
    address = str(wallet.get_force_new_address(is_change=False).address)

    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    wallet_functions.get_qt_wallets.connect(lambda: SimpleNamespace(wallet=wallet))

    tab = _SignTab(
        network=bdk.Network.REGTEST,
        signals_min=signals,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        wallet_functions=wallet_functions,
    )
    qtbot.addWidget(tab)
    tab.show()

    assert tab.sign_seed_button.isHidden()
    tab.sign_address_edit.setText(address)
    assert not tab.sign_seed_button.isHidden()
    assert len(tab.seed_menu.actions()) == 1

    tab.sign_address_edit.setText("")
    assert tab.sign_seed_button.isHidden()
    assert tab.seed_menu.actions() == []


def test_closing_wallet_clears_seed_menu_of_open_sign_tab(qtbot: QtBot, test_config, loop_in_thread) -> None:
    wallet = _wallet(signers=1, test_config=test_config)
    address = str(wallet.get_force_new_address(is_change=False).address)

    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    open_wallets: dict[str, SimpleNamespace] = {"wallet": SimpleNamespace(wallet=wallet)}
    wallet_functions.get_qt_wallets.connect(lambda: open_wallets["wallet"])

    tab = _SignTab(
        network=bdk.Network.REGTEST,
        signals_min=signals,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        wallet_functions=wallet_functions,
    )
    qtbot.addWidget(tab)
    tab.show()
    tab.sign_address_edit.setText(address)
    assert len(tab.seed_menu.actions()) == 1

    open_wallets.clear()
    signals.any_wallet_updated.emit(UpdateFilter(reason=UpdateFilterReason.WalletClosed))

    assert tab.sign_seed_button.isHidden()
    assert tab.seed_menu.actions() == []


def test_result_dialog_used_for_usb_qr_and_seed(
    qtbot: QtBot, test_config, loop_in_thread, monkeypatch
) -> None:
    wallet = _wallet(signers=1, test_config=test_config)
    address = str(wallet.get_force_new_address(is_change=False).address)
    info = wallet.get_address_info_min(address)
    assert info
    from bitcoin_safe.signer import seed_sign_options

    option = seed_sign_options(wallet, info)[0]
    message = "signed message"
    signature = option.signer.sign_message(message=message, bip32_path=option.bip32_path)
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    wallet_functions.get_qt_wallets.connect(lambda: SimpleNamespace(wallet=wallet))
    tab = _SignTab(
        network=bdk.Network.REGTEST,
        signals_min=signals,
        close_all_video_widgets=signals.close_all_video_widgets,
        loop_in_thread=loop_in_thread,
        wallet_functions=wallet_functions,
    )
    qtbot.addWidget(tab)
    tab.sign_address_edit.setText(address)
    tab.sign_message_edit.setPlainText(message)
    tab.usb_gui.sign_message = lambda message, bip32_path: signature  # type: ignore[method-assign]
    tab.on_sign_usb_message_button()
    assert "BEGIN BITCOIN SIGNED MESSAGE" in tab.result_dialog.signature_edit.toPlainText()
    tab.result_dialog.close()
    tab.on_show_export_widget()
    assert tab.qr_signing_info
    assert tab.qr_signing_info.keystores[0].mnemonic is None
    fingerprint = tab.qr_signing_info.keystores[0].fingerprint
    wallet.keystores[0].fingerprint = "00000000"
    assert tab.qr_signing_info.keystores[0].fingerprint == fingerprint
    wallet.keystores[0].fingerprint = fingerprint
    tab.sign_message_edit.setPlainText("changed while waiting")
    tab.on_raw_content(signature)
    assert "BEGIN BITCOIN SIGNED MESSAGE" in tab.result_dialog.signature_edit.toPlainText()
    tab.result_dialog.close()
    tab.sign_message_edit.setPlainText(message)
    tab.sign_with_option(option)
    assert "BEGIN BITCOIN SIGNED MESSAGE" in tab.result_dialog.signature_edit.toPlainText()


def test_address_details_signs_with_explicit_keystores(qtbot: QtBot, test_config, loop_in_thread) -> None:
    from bitcoin_safe.descriptors import get_address_bip32_path
    from bitcoin_safe.gui.qt.address_dialog import AddressDetailsAdvanced
    from bitcoin_safe.message_signing_result import MessageSigningInfo
    from bitcoin_safe.signer import seed_sign_options

    wallet = _wallet(signers=1, test_config=test_config)
    address = str(wallet.get_force_new_address(is_change=False).address)
    info = wallet.get_address_info_min(address)
    assert info
    signals = Signals()
    widget = AddressDetailsAdvanced(
        address_path_str=wallet.get_address_path_str(address),
        signing_info=MessageSigningInfo(
            get_address_bip32_path(str(wallet.multipath_descriptor), info.keychain, info.index),
            wallet.network,
            tuple(wallet.keystores),
        ),
        seed_options=seed_sign_options(wallet, info),
        close_all_video_widgets=signals.close_all_video_widgets,
        signals_min=signals,
        loop_in_thread=loop_in_thread,
        parent=None,
    )
    qtbot.addWidget(widget)
    widget.sign_message.sign_edit.setText("hello bitcoin")
    widget.sign_message.sign_with_option(seed_sign_options(wallet, info)[0])
    assert "BEGIN BITCOIN SIGNED MESSAGE" in widget.sign_message.result_dialog.signature_edit.toPlainText()


def test_message_signature_dialog_shows_verified_signer_address_and_status(
    qtbot: QtBot, test_config, loop_in_thread
) -> None:
    from bitcoin_safe.gui.qt.message_signature_dialog import MessageSignatureDialog
    from bitcoin_safe.message_signing_result import MessageSigningInfo
    from bitcoin_safe.signer import seed_sign_options

    wallet = _wallet(signers=2, test_config=test_config, threshold=2)
    address = str(wallet.get_force_new_address(is_change=False).address)
    info = wallet.get_address_info_min(address)
    assert info
    option = seed_sign_options(wallet, info)[0]
    message = "hello bitcoin"
    signature = option.signer.sign_message(message=message, bip32_path=option.bip32_path)
    signing_info = MessageSigningInfo(option.bip32_path, wallet.network, tuple(wallet.keystores)).snapshot()
    signals = Signals()
    dialog = MessageSignatureDialog(message, signing_info, signature, signals.close_all_video_widgets)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.signer_label.textLabel.text() == option.label
    signer_pixmap = dialog.signer_label.icon_label.pixmap()
    assert signer_pixmap and not signer_pixmap.isNull()
    assert dialog.signer_label.icon_label.isVisible()
    from bitcoin_safe.gui.qt.util import svg_tools_hardware_signer
    from bitcoin_safe.hardware_signers import HardwareSigners

    hardware_signer = (
        HardwareSigners.from_id(signing_info.keystores[0].hardware_signer_id) or HardwareSigners.generic
    )
    expected_icon = svg_tools_hardware_signer.get_QIcon(hardware_signer.icon_name).pixmap(24, 24)
    assert signer_pixmap.toImage() == expected_icon.toImage()
    assert "one key" in dialog.signer_label.toolTip()
    assert dialog.address_edit.text() != address
    assert dialog.address_edit.copy_button
    assert dialog.address_edit.input_field.isReadOnly()
    assert dialog.status_label.textLabel.text() == "Signature verified"
    assert dialog.status_label.icon_label.pixmap()
    assert dialog.layout().indexOf(dialog.status_label) > dialog.layout().indexOf(dialog.signature_edit)

    unverified = MessageSignatureDialog(
        message + "changed", signing_info, signature, signals.close_all_video_widgets
    )
    qtbot.addWidget(unverified)
    assert "could not be verified" in unverified.status_label.textLabel.text()
    assert unverified.signature_edit.toPlainText() == signature
    assert unverified.layout().indexOf(unverified.status_label) > unverified.layout().indexOf(
        unverified.signature_edit
    )
