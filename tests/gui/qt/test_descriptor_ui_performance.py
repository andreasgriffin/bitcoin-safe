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

from typing import Any

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_usb.address_types import AddressTypes
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.block_change_signals import BlockChangesSignals
from bitcoin_safe.gui.qt.descriptor_ui import DescriptorUI
from bitcoin_safe.gui.qt.keystore_ui import KeyStoreUI
from bitcoin_safe.signals import Signals, WalletFunctions
from bitcoin_safe.wallet import ProtoWallet, Wallet

from ...helpers import TestConfig
from ...non_gui.utils import create_multisig_protowallet


def _build_descriptor_ui(
    qtbot: QtBot,
    test_config: TestConfig,
    wallet_id: str = "descriptor-ui-delay-test",
) -> tuple[DescriptorUI, LoopInThread, Wallet | None]:
    loop_in_thread = LoopInThread()
    protowallet = ProtoWallet(
        threshold=2,
        keystores=[None, None, None],
        network=test_config.network,
        wallet_id=wallet_id,
    )
    descriptor_ui = DescriptorUI(
        protowallet=protowallet,
        wallet_functions=WalletFunctions(Signals()),
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(descriptor_ui)
    descriptor_ui.show()
    return descriptor_ui, loop_in_thread, None


def _build_existing_wallet_descriptor_ui(
    qtbot: QtBot,
    test_config: TestConfig,
    protowallet: ProtoWallet,
) -> tuple[DescriptorUI, LoopInThread, Wallet]:
    loop_in_thread = LoopInThread()
    wallet = Wallet.from_protowallet(
        protowallet=protowallet,
        config=test_config,
        loop_in_thread=loop_in_thread,
    )
    descriptor_ui = DescriptorUI(
        protowallet=wallet.as_protowallet(),
        wallet_functions=WalletFunctions(Signals()),
        loop_in_thread=loop_in_thread,
        wallet=wallet,
    )
    qtbot.addWidget(descriptor_ui)
    descriptor_ui.show()
    return descriptor_ui, loop_in_thread, wallet


def _snapshot_wallet_controls(descriptor_ui: DescriptorUI) -> dict[str, Any]:
    return {
        "combo_items": [
            descriptor_ui.comboBox_address_type.itemText(i)
            for i in range(descriptor_ui.comboBox_address_type.count())
        ],
        "combo_index": descriptor_ui.comboBox_address_type.currentIndex(),
        "combo_data": descriptor_ui.comboBox_address_type.currentData(),
        "combo_enabled": descriptor_ui.comboBox_address_type.isEnabled(),
        "spin_req_min": descriptor_ui.spin_req.minimum(),
        "spin_req_max": descriptor_ui.spin_req.maximum(),
        "spin_req_value": descriptor_ui.spin_req.value(),
        "spin_req_enabled": descriptor_ui.spin_req.isEnabled(),
        "spin_req_hidden": descriptor_ui.spin_req.isHidden(),
        "spin_signers_min": descriptor_ui.spin_signers.minimum(),
        "spin_signers_max": descriptor_ui.spin_signers.maximum(),
        "spin_signers_value": descriptor_ui.spin_signers.value(),
        "spin_signers_enabled": descriptor_ui.spin_signers.isEnabled(),
        "spin_signers_hidden": descriptor_ui.spin_signers.isHidden(),
        "spin_gap_value": descriptor_ui.spin_gap.value(),
        "spin_gap_enabled": descriptor_ui.spin_gap.isEnabled(),
        "descriptor_read_only": descriptor_ui.edit_descriptor.edit.input_field.isReadOnly(),
        "import_button_visible": descriptor_ui.edit_descriptor.import_button.isVisible(),
        "wallet_name": descriptor_ui.edit_wallet_name.text(),
    }


@pytest.mark.marker_qt_1
def test_descriptor_ui_init_repopulates_address_types_once(
    qtbot: QtBot,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = DescriptorUI.repopulate_comboBox_address_type

    def wrapped(self: DescriptorUI, is_multisig: bool) -> None:
        nonlocal calls
        calls += 1
        original(self, is_multisig)

    monkeypatch.setattr(DescriptorUI, "repopulate_comboBox_address_type", wrapped)

    descriptor_ui, loop_in_thread, wallet = _build_descriptor_ui(qtbot=qtbot, test_config=test_config)
    try:
        assert calls == 1
        assert descriptor_ui.comboBox_address_type.currentData() == descriptor_ui.protowallet.address_type
        assert descriptor_ui.spin_req.value() == descriptor_ui.protowallet.threshold
        assert descriptor_ui.spin_signers.value() == len(descriptor_ui.protowallet.keystores)
    finally:
        descriptor_ui.close()
        if wallet:
            wallet.close()
        loop_in_thread.stop()


@pytest.mark.marker_qt_1
def test_descriptor_ui_initializes_address_type_before_keystore_cards(
    qtbot: QtBot,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_apply_state = KeyStoreUI._apply_state

    def wrapped_apply_state(self: KeyStoreUI) -> None:
        self.get_expected_key_origin()
        original_apply_state(self)

    monkeypatch.setattr(KeyStoreUI, "_apply_state", wrapped_apply_state)

    descriptor_ui, loop_in_thread, wallet = _build_descriptor_ui(qtbot=qtbot, test_config=test_config)
    try:
        assert descriptor_ui.comboBox_address_type.currentData() == descriptor_ui.protowallet.address_type
    finally:
        descriptor_ui.close()
        if wallet:
            wallet.close()
        loop_in_thread.stop()


@pytest.mark.marker_qt_1
def test_descriptor_ui_noop_refreshes_skip_broad_signal_blocking(
    qtbot: QtBot,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor_ui, loop_in_thread, wallet = _build_descriptor_ui(qtbot=qtbot, test_config=test_config)
    try:
        enter_calls = 0
        original_enter = BlockChangesSignals.__enter__

        def wrapped_enter(self: BlockChangesSignals) -> None:
            nonlocal enter_calls
            enter_calls += 1
            original_enter(self)

        monkeypatch.setattr(BlockChangesSignals, "__enter__", wrapped_enter)

        before = _snapshot_wallet_controls(descriptor_ui)

        descriptor_ui.repopulate_comboBox_address_type(descriptor_ui.protowallet.is_multisig())
        descriptor_ui.disable_fields()
        descriptor_ui.set_wallet_ui_from_protowallet()

        after = _snapshot_wallet_controls(descriptor_ui)
        assert enter_calls == 0
        assert after == before
    finally:
        descriptor_ui.close()
        if wallet:
            wallet.close()
        loop_in_thread.stop()


@pytest.mark.marker_qt_1
def test_descriptor_ui_protowallet_mode_keeps_wallet_definition_editable(
    qtbot: QtBot,
    test_config: TestConfig,
) -> None:
    descriptor_ui, loop_in_thread, wallet = _build_descriptor_ui(qtbot=qtbot, test_config=test_config)
    try:
        assert descriptor_ui.edit_descriptor.edit.input_field.isReadOnly() is False
        assert descriptor_ui.edit_descriptor.import_button.isVisible()
        assert descriptor_ui.edit_descriptor.export_button.isVisible()
        assert descriptor_ui.spin_req.isEnabled()
        assert descriptor_ui.spin_signers.isEnabled()
        assert descriptor_ui.comboBox_address_type.isEnabled()
        assert descriptor_ui.spin_gap.isEnabled()
    finally:
        descriptor_ui.close()
        if wallet:
            wallet.close()
        loop_in_thread.stop()


@pytest.mark.marker_qt_1
def test_descriptor_ui_can_reduce_to_singlesig_with_incomplete_signers(
    qtbot: QtBot,
    test_config: TestConfig,
) -> None:
    descriptor_ui, loop_in_thread, wallet = _build_descriptor_ui(qtbot=qtbot, test_config=test_config)
    try:
        descriptor_ui.spin_req.setValue(1)
        descriptor_ui.spin_signers.setValue(1)

        assert descriptor_ui.spin_req.value() == 1
        assert descriptor_ui.spin_signers.value() == 1
        assert descriptor_ui.keystore_uis.count() == 1
        assert descriptor_ui.protowallet.is_multisig() is False
    finally:
        descriptor_ui.close()
        if wallet:
            wallet.close()
        loop_in_thread.stop()


@pytest.mark.marker_qt_1
def test_descriptor_ui_existing_wallet_mode_locks_descriptor_changes(
    qtbot: QtBot,
    test_config: TestConfig,
) -> None:
    protowallet = create_multisig_protowallet(
        threshold=2,
        signers=3,
        key_origins=[AddressTypes.p2wsh.key_origin(test_config.network)] * 3,
        wallet_id="descriptor-ui-existing-wallet",
        network=test_config.network,
    )
    descriptor_ui, loop_in_thread, wallet = _build_existing_wallet_descriptor_ui(
        qtbot=qtbot,
        test_config=test_config,
        protowallet=protowallet,
    )
    try:
        emitted_wallet_names: list[str] = []
        descriptor_ui.signal_wallet_name_changed.connect(emitted_wallet_names.append)

        assert descriptor_ui.label_wallet_name.parent() == descriptor_ui.box_wallet_type
        assert descriptor_ui.edit_wallet_name.parent() == descriptor_ui.box_wallet_type
        assert descriptor_ui.edit_wallet_name.text() == wallet.id
        assert descriptor_ui.edit_wallet_name.isEnabled()
        assert descriptor_ui.edit_wallet_name.isHidden() is False
        descriptor_ui.edit_wallet_name.setText(f"{wallet.id}-edited")
        assert emitted_wallet_names == []
        assert descriptor_ui.edit_descriptor.edit.input_field.isReadOnly()
        assert descriptor_ui.edit_descriptor.import_button.isHidden()
        assert descriptor_ui.edit_descriptor.export_button.isVisible()
        assert descriptor_ui.edit_descriptor.pdf_button.isVisible()
        assert descriptor_ui.edit_descriptor.register_button.isVisible()
        assert descriptor_ui.spin_req.isEnabled() is False
        assert descriptor_ui.spin_signers.isEnabled() is False
        assert descriptor_ui.comboBox_address_type.isEnabled() is False
        assert descriptor_ui.spin_gap.isEnabled()
    finally:
        descriptor_ui.close()
        wallet.close()
        loop_in_thread.stop()


@pytest.mark.marker_qt_1
@pytest.mark.parametrize(
    ("threshold", "signers", "key_origin"),
    [
        (1, 1, AddressTypes.p2wpkh.key_origin(bdk.Network.REGTEST)),
        (2, 3, AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST)),
    ],
)
@pytest.mark.parametrize("existing_wallet", [False, True])
def test_descriptor_ui_keeps_signer_controls_visible_without_no_edit_mode(
    qtbot: QtBot,
    test_config: TestConfig,
    threshold: int,
    signers: int,
    key_origin: str,
    existing_wallet: bool,
) -> None:
    protowallet = create_multisig_protowallet(
        threshold=threshold,
        signers=signers,
        key_origins=[key_origin] * signers,
        wallet_id=f"descriptor-ui-{threshold}-of-{signers}",
        network=test_config.network,
    )

    if existing_wallet:
        descriptor_ui, loop_in_thread, wallet = _build_existing_wallet_descriptor_ui(
            qtbot=qtbot,
            test_config=test_config,
            protowallet=protowallet,
        )
    else:
        loop_in_thread = LoopInThread()
        wallet = None
        descriptor_ui = DescriptorUI(
            protowallet=protowallet,
            wallet_functions=WalletFunctions(Signals()),
            loop_in_thread=loop_in_thread,
        )
        qtbot.addWidget(descriptor_ui)
        descriptor_ui.show()

    try:
        assert descriptor_ui.spin_req.isHidden() is False
        assert descriptor_ui.spin_signers.isHidden() is False
        assert descriptor_ui.label_signers.isHidden() is False
        assert descriptor_ui.label_of.isHidden() is False
    finally:
        descriptor_ui.close()
        if wallet:
            wallet.close()
        loop_in_thread.stop()
