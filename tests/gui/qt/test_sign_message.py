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
