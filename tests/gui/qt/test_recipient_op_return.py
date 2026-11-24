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

from unittest.mock import MagicMock

import bdkpython as bdk
import pytest
from PyQt6.QtCore import QPoint, QSignalBlocker, QTimer
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtWidgets import QApplication, QInputDialog
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.ui_tx.recipients import RecipientBox, describe_op_return
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.signals import Signals, WalletFunctions


@pytest.mark.parametrize(
    ("address", "description"),
    [
        ("script:6a026869", "OP_RETURN: hi"),
        ("script:6a4c02686902c3a9", "OP_RETURN: hi | é"),
        ("script:6a02ff00", "OP_RETURN: 0xff00"),
        ("script:6a03610a62", "OP_RETURN: a\\nb"),
        ("script:6a51", "OP_RETURN: OP_1"),
        ("script:6a4c05ff", "OP_RETURN: [error]"),
        ("script:6a", "OP_RETURN"),
        ("script:00146a026869", None),
        ("script:6a0", None),
        ("6a026869", None),
    ],
)
def test_describe_op_return(address: str, description: str | None) -> None:
    assert describe_op_return(address) == description


def test_recipient_header_updates_and_escapes_payload(qtbot: QtBot) -> None:
    box = RecipientBox(fx=None, wallet_functions=WalletFunctions(Signals()), network=bdk.Network.REGTEST)
    qtbot.addWidget(box)

    box.address = "script:6a063c623e686921"
    assert box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: &lt;b&gt;hi!"
    box.updateUi()
    assert box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: &lt;b&gt;hi!"

    wallet = MagicMock()
    wallet.id = "My wallet"
    wallet.is_change.return_value = True
    wallet.is_my_address_with_peek.return_value = True
    wallet.get_label_for_address.return_value = None
    wallet.labels.get_category.return_value = ""

    def get_wallet() -> MagicMock:
        return wallet

    box.wallet_functions.get_wallets.connect(get_wallet, slot_name=wallet.id)
    box.autofill_wallet_id()
    assert box.notification_bar.icon_label.textLabel.text() == (
        "This address belongs to wallet: <b>My wallet</b> (possible change)"
    )
    wallet.is_change.assert_called_with(box.address)
    assert box.notification_bar.icon_label.toolTip() == ""
    box.wallet_functions.signals.language_switch.emit()
    assert box.notification_bar.icon_label.textLabel.text() == (
        "This address belongs to wallet: <b>My wallet</b> (possible change)"
    )
    wallet.is_change.return_value = False
    box.autofill_wallet_id()
    assert (
        box.notification_bar.icon_label.textLabel.text() == "This address belongs to wallet: <b>My wallet</b>"
    )
    box.wallet_functions.get_wallets.disconnect(get_wallet)

    box.address = "script:6a4c" + "78" + "61" * 120
    assert box.notification_bar.icon_label.textLabel.text().endswith("…")
    assert "a" * 120 in box.notification_bar.icon_label.toolTip()

    box.address = "script:0014" + "42" * 20
    assert box.notification_bar.icon_label.textLabel.text() == ""
    assert box.notification_bar.icon_label.toolTip() == ""


def test_header_refresh_reads_current_address(qtbot: QtBot) -> None:
    signals = Signals()
    box = RecipientBox(fx=None, wallet_functions=WalletFunctions(signals), network=bdk.Network.REGTEST)
    qtbot.addWidget(box)

    with QSignalBlocker(box.recipient_widget.address_edit):
        box.address = "script:6a026869"
    signals.language_switch.emit()

    assert box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: hi"


def test_generate_op_return_from_header_context_menu(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    box = RecipientBox(fx=None, wallet_functions=WalletFunctions(Signals()), network=bdk.Network.REGTEST)
    qtbot.addWidget(box)
    box.show()

    def choose_action(menu: Menu, position: QPoint) -> None:
        assert [action.text() for action in menu.actions()] == ["Generate OP_RETURN"]
        menu.actions()[0].trigger()

    def fill_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        dialog.setTextValue("Hello, 世界!\nLine 2")
        dialog.accept()

    monkeypatch.setattr(Menu, "exec", choose_action)
    QTimer.singleShot(0, fill_dialog)
    label = box.notification_bar.icon_label.textLabel
    position = QPoint(1, 1)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, label.mapToGlobal(position))
    QApplication.sendEvent(label, event)

    expected = "Hello, 世界!\nLine 2".encode()
    assert box.address == "script:6a" + bytes([len(expected)]).hex() + expected.hex()
    assert box.notification_bar.icon_label.textLabel.text() == "OP_RETURN: Hello, 世界!\\nLine 2"


@pytest.mark.parametrize(("length", "prefix"), [(75, "6a4b"), (76, "6a4c4c"), (256, "6a4d0001")])
def test_generate_op_return_push_lengths(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, length: int, prefix: str
) -> None:
    box = RecipientBox(fx=None, wallet_functions=WalletFunctions(Signals()), network=bdk.Network.REGTEST)
    qtbot.addWidget(box)
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *args: ("a" * length, True))

    box.generate_op_return()

    assert box.address == "script:" + prefix + "61" * length


def test_generate_op_return_does_not_overwrite_or_edit_read_only(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = RecipientBox(fx=None, wallet_functions=WalletFunctions(Signals()), network=bdk.Network.REGTEST)
    qtbot.addWidget(box)
    menus: list[Menu] = []
    monkeypatch.setattr(Menu, "exec", lambda menu, position: menus.append(menu))
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *args: ("unused", False))

    box.show_header_context_menu(QPoint())
    assert len(menus) == 1
    box.generate_op_return()
    assert box.address == ""

    box.address = "some address"
    box.show_header_context_menu(QPoint())
    box.generate_op_return()
    assert box.address == "some address"
    assert len(menus) == 1

    box.address = ""
    box.set_allow_edit(False)
    box.show_header_context_menu(QPoint())
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *args: ("unused", True))
    box.generate_op_return()
    assert box.address == ""
    assert len(menus) == 1
