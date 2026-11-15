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

from types import MethodType, SimpleNamespace

from PyQt6.QtWidgets import QDialog

from bitcoin_safe.gui.qt import address_dialog
from bitcoin_safe.gui.qt.attached_widgets import AttachedWidgets
from bitcoin_safe.gui.qt.main import MainWindow


def _address_dialog_stub(wallet_id: str) -> SimpleNamespace:
    """Stand-in for AddressDialog: only the attributes the close logic reads."""
    return SimpleNamespace(wallet=SimpleNamespace(id=wallet_id), closed=False)


def _window_stub(attached_widgets: AttachedWidgets, message_dialog: QDialog | None) -> SimpleNamespace:
    window = SimpleNamespace(
        attached_widgets=attached_widgets,
        _message_signature_dialog=message_dialog,
    )
    window._close_widgets_with_seed_access = MethodType(MainWindow._close_widgets_with_seed_access, window)
    window._on_message_signature_dialog_finished = MethodType(
        MainWindow._on_message_signature_dialog_finished, window
    )
    return window


def test_closing_wallet_closes_its_address_dialogs_and_message_signing(qapp, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    closed: list[str] = []

    class _FakeAddressDialog(address_dialog.AddressDialog):
        def __init__(self, wallet_id: str, name: str) -> None:  # type: ignore[no-untyped-def]
            self.wallet = SimpleNamespace(id=wallet_id)
            self._name = name

        def close(self) -> bool:  # type: ignore[override]
            closed.append(self._name)
            return True

    message_dialog = QDialog()
    message_dialog.close = lambda: closed.append("message")  # type: ignore[method-assign]

    attached = AttachedWidgets(maxlen=10)
    attached.append(_FakeAddressDialog(wallet_id="closed-wallet", name="closed-address"))
    attached.append(_FakeAddressDialog(wallet_id="other-wallet", name="other-address"))
    window = _window_stub(attached, message_dialog)

    window._close_widgets_with_seed_access("closed-wallet")

    assert closed == ["closed-address", "message"]


def test_message_signing_dialog_reference_is_cleared_when_finished() -> None:
    dialog = QDialog()
    window = _window_stub(AttachedWidgets(maxlen=10), dialog)

    window._on_message_signature_dialog_finished(0)

    assert window._message_signature_dialog is None
