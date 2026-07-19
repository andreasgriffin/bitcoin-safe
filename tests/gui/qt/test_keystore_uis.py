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

import bdkpython as bdk
from bitcoin_qr_tools.data import SignerInfo
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_usb.address_types import AddressTypes
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.keystore_ui import KeyStoreUiState
from bitcoin_safe.gui.qt.keystore_uis import KeyStoreUIs
from bitcoin_safe.hardware_signers import HardwareSigners
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.wallet import ProtoWallet

from ...non_gui.utils import create_test_seed_keystores


def test_keystore_uis_empty_slots_render_as_add_cards(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    protowallet = ProtoWallet(
        wallet_id="wallet",
        threshold=2,
        network=bdk.Network.REGTEST,
        keystores=[None, None],
        address_type=AddressTypes.p2wsh,
    )
    widget = KeyStoreUIs(
        get_editable_protowallet=lambda: protowallet,
        get_address_type=lambda: AddressTypes.p2wsh,
        signals_min=SignalsMin(),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    assert widget.count() == 2
    assert [keystore_ui.state for keystore_ui in widget.getAllTabData().values()] == [
        KeyStoreUiState.Add,
        KeyStoreUiState.Add,
    ]


def test_keystore_uis_syncs_back_to_protowallet(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    protowallet = ProtoWallet(
        wallet_id="wallet",
        threshold=1,
        network=bdk.Network.REGTEST,
        keystores=[None],
        address_type=AddressTypes.p2wpkh,
    )
    widget = KeyStoreUIs(
        get_editable_protowallet=lambda: protowallet,
        get_address_type=lambda: AddressTypes.p2wpkh,
        signals_min=SignalsMin(),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    keystore_ui = list(widget.getAllTabData().values())[0]
    hardware_signer = HardwareSigners.krux_diy
    keystore_ui.combo_brand.setCurrentText(hardware_signer.brand_name)
    keystore_ui.combo_model.setCurrentText(hardware_signer.display_name)
    keystore_ui.confirm_device_type_selection()
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[AddressTypes.p2wpkh.key_origin(bdk.Network.REGTEST)],
        network=bdk.Network.REGTEST,
    )[0]
    keystore_ui.set_using_signer_info(SignerInfo(keystore.fingerprint, keystore.key_origin, keystore.xpub))

    widget.set_protowallet_from_keystore_ui()

    assert protowallet.keystores[0] is not None
    assert protowallet.keystores[0].hardware_signer_id == hardware_signer.id


def test_keystore_uis_expand_only_collapses_other_cards(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    protowallet = ProtoWallet(
        wallet_id="wallet",
        threshold=2,
        network=bdk.Network.REGTEST,
        keystores=[None, None],
        address_type=AddressTypes.p2wsh,
    )
    widget = KeyStoreUIs(
        get_editable_protowallet=lambda: protowallet,
        get_address_type=lambda: AddressTypes.p2wsh,
        signals_min=SignalsMin(),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    first, second = list(widget.getAllTabData().values())

    widget.expand_only(1)

    assert widget.currentIndex() == 1
    assert not first.is_expanded
    assert second.is_expanded


def test_keystore_uis_show_device_instructions_label_after_signer_selection(
    qtbot: QtBot, loop_in_thread: LoopInThread
) -> None:
    protowallet = ProtoWallet(
        wallet_id="wallet",
        threshold=1,
        network=bdk.Network.REGTEST,
        keystores=[None],
        address_type=AddressTypes.p2wsh,
    )
    widget = KeyStoreUIs(
        get_editable_protowallet=lambda: protowallet,
        get_address_type=lambda: AddressTypes.p2wsh,
        signals_min=SignalsMin(),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.resize(420, 220)
    widget.show()

    keystore_ui = list(widget.getAllTabData().values())[0]
    keystore_ui.combo_brand.setCurrentText(HardwareSigners.jade.brand_name)
    keystore_ui.combo_model.setCurrentText(HardwareSigners.jade.display_name)
    keystore_ui.confirm_device_type_selection()

    assert keystore_ui.connect_help_label.isVisible()
    assert keystore_ui.connect_help_label.textLabel.text() == "Device instructions"


def test_keystore_uis_header_click_expands_only_clicked_card(
    qtbot: QtBot, loop_in_thread: LoopInThread
) -> None:
    protowallet = ProtoWallet(
        wallet_id="wallet",
        threshold=2,
        network=bdk.Network.REGTEST,
        keystores=[None, None],
        address_type=AddressTypes.p2wsh,
    )
    widget = KeyStoreUIs(
        get_editable_protowallet=lambda: protowallet,
        get_address_type=lambda: AddressTypes.p2wsh,
        signals_min=SignalsMin(),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    first, second = list(widget.getAllTabData().values())
    widget.collapse_all()

    qtbot.mouseClick(second.header_title, Qt.MouseButton.LeftButton)

    assert widget.currentIndex() == 1
    assert not first.is_expanded
    assert second.is_expanded


def test_keystore_uis_uses_card_list_scroll_behavior(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    protowallet = ProtoWallet(
        wallet_id="wallet",
        threshold=1,
        network=bdk.Network.REGTEST,
        keystores=[None] * 6,
        address_type=AddressTypes.p2wsh,
    )
    widget = KeyStoreUIs(
        get_editable_protowallet=lambda: protowallet,
        get_address_type=lambda: AddressTypes.p2wsh,
        signals_min=SignalsMin(),
        loop_in_thread=loop_in_thread,
    )
    widget.resize(420, 180)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    assert widget.card_list.only_one_expanded_at_a_time()

    widget.expand_only(5)

    assert widget.currentIndex() == 5
    assert widget.scroll_area.verticalScrollBar().maximum() > 0
    assert widget.scroll_area.verticalScrollBar().value() > 0


def test_keystore_uis_reports_duplicate_xpub_signer_slots(qtbot: QtBot, loop_in_thread: LoopInThread) -> None:
    protowallet = ProtoWallet(
        wallet_id="wallet",
        threshold=2,
        network=bdk.Network.REGTEST,
        keystores=[None, None],
        address_type=AddressTypes.p2wsh,
    )
    widget = KeyStoreUIs(
        get_editable_protowallet=lambda: protowallet,
        get_address_type=lambda: AddressTypes.p2wsh,
        signals_min=SignalsMin(),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(widget)
    widget.show()

    first, second = list(widget.getAllTabData().values())
    for keystore_ui in (first, second):
        keystore_ui.combo_brand.setCurrentText(HardwareSigners.krux_diy.brand_name)
        keystore_ui.combo_model.setCurrentText(HardwareSigners.krux_diy.display_name)
        keystore_ui.confirm_device_type_selection()

    first_keystore, second_keystore = create_test_seed_keystores(
        signers=2,
        key_origins=[AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST)] * 2,
        network=bdk.Network.REGTEST,
    )
    first.set_using_signer_info(
        SignerInfo(
            fingerprint=first_keystore.fingerprint,
            key_origin=first_keystore.key_origin,
            xpub=first_keystore.xpub,
        )
    )
    second.set_using_signer_info(
        SignerInfo(
            fingerprint=second_keystore.fingerprint,
            key_origin=second_keystore.key_origin,
            xpub=first_keystore.xpub,
        )
    )
    widget.ui_keystore_ui_change()

    messages = widget.get_warning_and_error_messages([first, second])
    expected_message = (
        "Signer slots 1, 2 contain the same xpub. This usually means the same signer export "
        "was imported twice. Please import a different device or account for each signer."
    )

    assert first.edit_xpub.toolTip() == expected_message
    assert second.edit_xpub.toolTip() == expected_message
    assert first.get_worst_analysis().msg == expected_message
    assert second.get_worst_analysis().msg == expected_message
    assert any(message.msg == expected_message for message in messages)
