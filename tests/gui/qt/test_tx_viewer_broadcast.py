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

import asyncio
from types import SimpleNamespace

import pytest
from bitcoin_qr_tools.data import DataType
from PyQt6.QtWidgets import QMessageBox

from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.util import MessageType
from bitcoin_safe.tx import HiddenTxUiInfos, PostBroadcastEnum


def test_broadcast_timeout_shows_explanation(monkeypatch) -> None:
    """A timeout should use the dedicated explanation instead of a raw error."""

    class TimeoutClient:
        def broadcast(self, _tx: object) -> None:
            raise asyncio.TimeoutError

    events: list[str] = []
    emitted_transactions: list[object] = []
    viewer = SimpleNamespace(
        client=TimeoutClient(),
        signals=SimpleNamespace(
            signal_broadcast_tx=SimpleNamespace(emit=emitted_transactions.append),
        ),
        _show_broadcast_timeout=lambda: events.append("timeout_message"),
        tr=lambda message: message,
    )

    assert not UITx_Viewer._broadcast(viewer, object())
    assert not emitted_transactions
    assert events == ["timeout_message"]


def test_broadcast_timeout_dialog_links_and_defaults_to_block_explorer(monkeypatch) -> None:
    """The timeout dialog should make checking the explorer the primary action."""

    class FakeDialog:
        def __init__(self) -> None:
            self.view_button = object()
            self.added_button: tuple[str, QMessageBox.ButtonRole] | None = None
            self.default_button: object | None = None
            self.executed = False

        def addButton(self, text: str, role: QMessageBox.ButtonRole) -> object:
            self.added_button = (text, role)
            return self.view_button

        def setDefaultButton(self, button: object) -> None:
            self.default_button = button

        def exec(self) -> None:
            self.executed = True

        def clickedButton(self) -> object:
            return self.view_button

    dialog = FakeDialog()
    messages: list[dict[str, object]] = []

    class FakeMessage:
        def __init__(self, message: str, **kwargs: object) -> None:
            messages.append({"message": message, **kwargs})

        def create(self) -> FakeDialog:
            return dialog

    monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.Message", FakeMessage)

    opened_urls: list[str] = []
    tx_url = "https://mempool.example/tx/txid"
    viewer = SimpleNamespace(
        txid_label=SimpleNamespace(
            get_tx_url=lambda: tx_url,
            open_txid_in_block_explorer=lambda: opened_urls.append(tx_url),
        ),
        tr=lambda message: message,
    )

    UITx_Viewer._show_broadcast_timeout(viewer)

    assert len(messages) == 1
    message = messages[0]["message"]
    assert isinstance(message, str)
    assert "fee is too low" in message
    assert "already broadcast" in message
    assert f'href="{tx_url}"' in message
    assert messages[0]["title"] == "Broadcast status unknown"
    assert messages[0]["type"] == MessageType.Warning
    assert messages[0]["buttons"] == QMessageBox.StandardButton.Close
    assert messages[0]["no_show"] is True
    assert dialog.added_button == (
        "View in block explorer",
        QMessageBox.ButtonRole.AcceptRole,
    )
    assert dialog.default_button is dialog.view_button
    assert dialog.executed
    assert opened_urls == [tx_url]


@pytest.mark.parametrize(
    ("locktime_valid", "dialog_response", "broadcast_success", "expected_events"),
    [
        (False, False, True, []),
        (True, True, False, ["broadcast"]),
        (True, True, True, ["broadcast", "save_local"]),
    ],
)
def test_broadcast_only_saves_local_tx_after_success(
    monkeypatch,
    locktime_valid: bool,
    dialog_response: bool,
    broadcast_success: bool,
    expected_events: list[str],
) -> None:
    """Local saves should happen only after a confirmed successful broadcast."""

    class FakeTransaction:
        def lock_time(self) -> int:
            return 0

        def compute_txid(self) -> str:
            return "txid"

    monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.bdk.Transaction", FakeTransaction)
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.is_nlocktime_already_valid",
        lambda _lock_time, _height: locktime_valid,
    )
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.question_dialog",
        lambda _message: dialog_response,
    )

    events: list[str] = []

    def save_local_tx() -> None:
        events.append("save_local")

    def broadcast(_tx: FakeTransaction) -> bool:
        events.append("broadcast")
        return broadcast_success

    viewer = SimpleNamespace(
        data=SimpleNamespace(data_type=DataType.Tx, data=FakeTransaction()),
        hidden_tx_infos=HiddenTxUiInfos(save_local_on_send=True),
        post_broadcast_action=PostBroadcastEnum.open_hist_list,
        _post_broadcast_consumed_txid=None,
        client=object(),
        save_local_tx=save_local_tx,
        _get_robust_height=lambda: 0,
        _set_blockchain=lambda: None,
        _broadcast=broadcast,
        signals=SimpleNamespace(signal_open_history_for_tx=SimpleNamespace(emit=lambda _tx: None)),
        txid=lambda: "txid",
        tr=lambda message: message,
    )

    UITx_Viewer.broadcast(viewer)

    assert events == expected_events
