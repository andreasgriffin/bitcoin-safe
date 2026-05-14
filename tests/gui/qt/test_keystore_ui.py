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

from __future__ import annotations

import bdkpython as bdk
from bitcoin_qr_tools.data import SignerInfo
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_usb.address_types import AddressTypes
from bitcoin_usb.dialogs import AutoScanMode
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.keystore_ui import KeyStoreUI, KeyStoreUiState
from bitcoin_safe.gui.qt.util import ColorScheme
from bitcoin_safe.hardware_signers import HardwareSigners
from bitcoin_safe.signals import SignalsMin

from ...non_gui.utils import create_test_seed_keystores


def _make_widget(
    qtbot: QtBot,
    loop_in_thread: LoopInThread,
    read_only_mode: bool = False,
    network: bdk.Network = bdk.Network.REGTEST,
    show_register_button: bool = True,
) -> KeyStoreUI:
    widget = KeyStoreUI(
        network=network,
        get_address_type=lambda: AddressTypes.p2wsh,
        signals_min=SignalsMin(),
        loop_in_thread=loop_in_thread,
        hardware_signer_label="Signer 1",
        read_only_mode=read_only_mode,
        show_register_button=show_register_button,
    )
    qtbot.addWidget(widget)
    widget.show()
    return widget


def _select_signer(widget: KeyStoreUI, signer_id: str) -> None:
    hardware_signer = HardwareSigners.from_id(signer_id)
    assert hardware_signer
    widget.combo_brand.setCurrentText(hardware_signer.brand_name)
    widget.combo_model.setCurrentText(hardware_signer.display_name)
    widget.confirm_device_type_selection()


def test_keystore_ui_add_state(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)

    assert widget.state == KeyStoreUiState.Add
    assert widget.header_icon.text() == "+"
    assert widget.sizePolicy().verticalPolicy() == widget.sizePolicy().Policy.Fixed
    assert widget.combo_brand.isVisible()
    assert widget.combo_model.isVisible()
    assert widget.button_confirm_signer.isVisible()
    assert not widget.left_widget.isVisible()
    assert not widget.right_widget.isVisible()


def test_keystore_ui_empty_state(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    _select_signer(widget, HardwareSigners.krux.id)

    assert widget.state == KeyStoreUiState.Empty
    assert widget.left_widget.isVisible()
    assert widget.right_widget.isVisible()
    assert widget.connect_help_label.isVisible()
    assert widget.connect_help_label.textLabel.text() == "Connect"
    assert widget.button_connect_qr.isVisible()
    assert not widget.edit_fingerprint.isVisible()
    assert widget.edit_seed.isVisible()
    assert widget.textEdit_description.isVisible()


def test_selecting_device_type_updates_header_label_before_xpub(
    qtbot: QtBot, loop_in_thread: LoopInThread
) -> None:
    widget = _make_widget(qtbot, loop_in_thread)

    _select_signer(widget, HardwareSigners.krux.id)

    assert widget.hardware_signer_label == HardwareSigners.krux.display_name
    assert widget.header_title.text() == HardwareSigners.krux.display_name


def test_keystore_ui_empty_state_hides_seed_on_mainnet(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread, network=bdk.Network.BITCOIN)
    _select_signer(widget, HardwareSigners.krux.id)

    assert widget.state == KeyStoreUiState.Empty
    assert not widget.edit_seed.isVisible()


def test_keystore_ui_empty_state_hides_seed_in_demo_mode(
    qtbot: QtBot, loop_in_thread: LoopInThread, monkeypatch
) -> None:
    monkeypatch.setattr("bitcoin_safe.gui.qt.keystore_ui.DEMO_MODE", True)
    widget = _make_widget(qtbot, loop_in_thread)
    _select_signer(widget, HardwareSigners.krux.id)

    assert widget.state == KeyStoreUiState.Empty
    assert not widget.edit_seed.isVisible()


def test_brand_selection_defaults_to_first_model(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)

    widget.combo_brand.setCurrentText("Coinkite")

    assert widget.combo_model.count() == 2
    assert widget.combo_model.currentData() == HardwareSigners.coldcard.id
    assert widget.button_confirm_signer.isEnabled()


def test_device_selection_expands_collapsed_card(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    widget.collapse()

    _select_signer(widget, HardwareSigners.krux.id)

    assert widget.is_expanded
    assert widget.left_widget.isVisible()
    assert widget.right_widget.isVisible()


def test_keystore_ui_filled_state(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    _select_signer(widget, HardwareSigners.krux.id)
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST)],
        network=bdk.Network.REGTEST,
    )[0]
    widget.set_using_signer_info(SignerInfo(keystore.fingerprint, keystore.key_origin, keystore.xpub))

    assert widget.state == KeyStoreUiState.Filled
    assert widget.button_connect_qr.isVisible()
    assert widget.edit_fingerprint.isVisible()
    assert widget.edit_xpub.isVisible()
    assert widget.header_status_icon.isVisible()


def test_change_device_type_keeps_existing_details_visible(
    qtbot: QtBot, loop_in_thread: LoopInThread
) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    _select_signer(widget, HardwareSigners.krux.id)
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST)],
        network=bdk.Network.REGTEST,
    )[0]
    widget.set_using_signer_info(SignerInfo(keystore.fingerprint, keystore.key_origin, keystore.xpub))

    widget.start_device_type_change()

    assert widget.edit_fingerprint.isVisible()
    assert widget.edit_xpub.isVisible()
    assert widget.button_confirm_signer.isVisible()
    assert not widget.button_device_instructions.isVisible()
    assert not widget.button_register.isVisible()
    assert widget.state == KeyStoreUiState.Filled


def test_device_instructions_open_in_top_level_window(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    _select_signer(widget, HardwareSigners.krux.id)

    widget.show_device_instructions()

    assert widget._device_help_widget is not None
    assert widget._device_help_widget.parentWidget() is None
    assert widget._device_help_widget.isWindow()


def test_keystore_ui_read_only_state(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread, read_only_mode=True)
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST)],
        network=bdk.Network.REGTEST,
    )[0]
    keystore.hardware_signer_id = HardwareSigners.passport.id
    widget.set_ui_from_keystore(keystore)

    assert widget.state == KeyStoreUiState.ReadOnly
    assert not widget.connect_help_label.isVisible()
    assert not widget.button_device_instructions.isVisible()
    assert widget.action_device_instructions.isVisible()
    assert widget.button_register.isVisible()
    assert widget.edit_fingerprint.input_field.isReadOnly()
    widget.counter_register_button_clicked = 1
    widget.updateUi()
    assert not widget.button_register.isVisible()


def test_keystore_ui_read_only_state_can_hide_register_button(
    qtbot: QtBot, loop_in_thread: LoopInThread
) -> None:
    widget = _make_widget(qtbot, loop_in_thread, read_only_mode=True, show_register_button=False)
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST)],
        network=bdk.Network.REGTEST,
    )[0]
    keystore.hardware_signer_id = HardwareSigners.passport.id
    widget.set_ui_from_keystore(keystore)

    assert widget.state == KeyStoreUiState.ReadOnly
    assert not widget.button_register.isVisible()


def test_register_multisig_emit_request_signal(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread, read_only_mode=True)
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST)],
        network=bdk.Network.REGTEST,
    )[0]
    keystore.hardware_signer_id = HardwareSigners.passport.id
    widget.set_ui_from_keystore(keystore)

    with qtbot.waitSignal(widget.request_show_register_multisig) as blocker:
        widget.button_register.click()

    assert blocker.args == [HardwareSigners.passport]
    assert widget.counter_register_button_clicked == 1


def test_keystore_ui_connect_buttons_follow_capabilities(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)

    _select_signer(widget, HardwareSigners.passport.id)
    assert widget.button_connect_qr.isVisible()
    assert not widget.button_connect_usb.isVisible()
    assert not widget.button_connect_bluetooth.isVisible()
    assert widget.button_connect_import.isVisible()

    _select_signer(widget, HardwareSigners.q.id)
    assert widget.button_connect_qr.isVisible()
    assert widget.button_connect_usb.isVisible()
    assert not widget.button_connect_bluetooth.isVisible()
    assert widget.button_connect_import.isVisible()

    _select_signer(widget, HardwareSigners.jade.id)
    assert widget.button_connect_qr.isVisible()
    assert widget.button_connect_usb.isVisible()
    assert widget.button_connect_bluetooth.isVisible()
    assert widget.button_connect_import.isVisible()

    _select_signer(widget, HardwareSigners.generic.id)
    assert widget.button_connect_qr.isVisible()
    assert widget.button_connect_usb.isVisible()
    assert widget.button_connect_bluetooth.isVisible()
    assert widget.button_connect_import.isVisible()


def test_keystore_ui_transport_buttons_set_matching_autoscan_mode(
    qtbot: QtBot, loop_in_thread: LoopInThread, monkeypatch
) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    autoscan_modes: list[AutoScanMode] = []
    key_origins: list[str] = []

    monkeypatch.setattr(widget.usb_gui, "set_autoscan_mode", lambda mode: autoscan_modes.append(mode))
    monkeypatch.setattr(
        widget.usb_gui,
        "get_fingerprint_and_xpub",
        lambda key_origin: key_origins.append(key_origin) or None,
    )

    widget.on_hwi_click_usb()
    widget.on_hwi_click_bluetooth()

    assert autoscan_modes == [AutoScanMode.USB, AutoScanMode.BLUETOOTH]
    assert key_origins == [
        AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST),
        AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST),
    ]


def test_keystore_ui_unexpected_key_origin_uses_warning_styling(
    qtbot: QtBot, loop_in_thread: LoopInThread
) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    _select_signer(widget, HardwareSigners.krux.id)
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST)],
        network=bdk.Network.REGTEST,
    )[0]

    widget.edit_key_origin.setText("m/48h/1h/1h/2h")
    widget.edit_xpub.setText(keystore.xpub)
    widget.format_all_fields()

    warning_color = ColorScheme.WARNING.as_color(background=True).name()
    assert warning_color in widget.edit_key_origin.input_field.styleSheet()
    assert warning_color in widget.edit_xpub.input_field.styleSheet()


def test_collapsed_keystore_ui_expands_on_header_click(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    _select_signer(widget, HardwareSigners.krux.id)

    widget.collapse()

    assert not widget.is_expanded
    assert not widget.left_widget.isVisible()

    with qtbot.waitSignal(widget.signal_expand_requested):
        qtbot.mouseClick(widget.header_title, Qt.MouseButton.LeftButton)


def test_expanded_keystore_ui_collapses_on_header_click(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    widget = _make_widget(qtbot, loop_in_thread)
    _select_signer(widget, HardwareSigners.krux.id)

    assert widget.is_expanded
    assert widget.left_widget.isVisible()

    qtbot.mouseClick(widget.header_title, Qt.MouseButton.LeftButton)

    assert not widget.is_expanded
    assert not widget.left_widget.isVisible()
