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

import bdkpython as bdk
from PyQt6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.sign_message import SignMessageBase
from bitcoin_safe.signals import Signals


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
