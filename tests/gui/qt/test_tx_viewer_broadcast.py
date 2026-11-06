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


def test_broadcast_requests_broadcast_from_main_window() -> None:
    """The viewer must not touch the client itself; it requests the broadcast via a signal."""
    requests: list[tuple[object, object]] = []
    client = object()
    tx = object()
    viewer = SimpleNamespace(
        client=client,
        signals=SimpleNamespace(
            signal_do_broadcast_tx=SimpleNamespace(emit=lambda c, t: requests.append((c, t))),
        ),
    )

    UITx_Viewer._broadcast(viewer, tx)

    assert requests == [(client, tx)]


def test_broadcast_timeout_result_shows_explanation() -> None:
    """A failed broadcast result should show the timeout explanation."""
    events: list[str] = []
    viewer = SimpleNamespace(
        txid=lambda: "txid",
        _show_broadcast_timeout=lambda: events.append("timeout_message"),
        _on_broadcast_succeeded=lambda _tx: events.append("succeeded"),
    )
    tx = SimpleNamespace(compute_txid=lambda: "txid")

    UITx_Viewer._on_broadcast_finished(viewer, tx, False)

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
    ("locktime_valid", "dialog_response", "expected_events"),
    [
        (False, False, []),
        (True, True, ["broadcast"]),
    ],
)
def test_broadcast_requests_only_when_locktime_and_dialog_allow(
    monkeypatch,
    locktime_valid: bool,
    dialog_response: bool,
    expected_events: list[str],
) -> None:
    """The broadcast request is only sent when nLocktime is valid or the user confirms."""

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

    def broadcast(_tx: FakeTransaction) -> None:
        events.append("broadcast")

    viewer = SimpleNamespace(
        data=SimpleNamespace(data_type=DataType.Tx, data=FakeTransaction()),
        client=object(),
        _get_robust_height=lambda: 0,
        _set_blockchain=lambda: None,
        _broadcast=broadcast,
        tr=lambda message: message,
    )

    UITx_Viewer.broadcast(viewer)

    assert events == expected_events


def test_broadcast_success_saves_local_tx_and_opens_history() -> None:
    """Local saves and history opening happen only after the broadcast is confirmed sent."""
    events: list[str] = []
    viewer = SimpleNamespace(
        hidden_tx_infos=HiddenTxUiInfos(save_local_on_send=True),
        save_local_tx=lambda: events.append("save_local"),
        post_broadcast_action=PostBroadcastEnum.open_hist_list,
        _post_broadcast_consumed_txid=None,
        signals=SimpleNamespace(
            signal_open_history_for_tx=SimpleNamespace(emit=lambda _tx: events.append("history"))
        ),
        txid=lambda: "txid",
    )

    UITx_Viewer._on_broadcast_succeeded(viewer, SimpleNamespace(compute_txid=lambda: "txid"))

    assert events == ["save_local", "history"]


def test_main_window_falls_back_to_p2p_on_timeout() -> None:
    """On a CBF timeout the main window retries via p2p and reports success."""
    from bitcoin_safe.gui.qt.main import MainWindow

    class TimeoutClient:
        def broadcast(self, _tx: object) -> None:
            raise asyncio.TimeoutError

    events: list[object] = []

    async def p2p_broadcast(_tx: object) -> bool:
        return True

    window = SimpleNamespace(
        p2p_listener=SimpleNamespace(broadcast_tx=p2p_broadcast),
        signals=SimpleNamespace(
            signal_broadcast_tx=SimpleNamespace(emit=lambda tx: events.append(("broadcast", tx))),
            signal_broadcast_tx_finished=SimpleNamespace(
                emit=lambda tx, sent: events.append(("finished", sent))
            ),
            signal_broadcast_tx_failed=SimpleNamespace(emit=lambda tx, e: events.append(("failed", e))),
        ),
        _broadcast_tx_via_p2p_peers=lambda tx: MainWindow._broadcast_tx_via_p2p_peers(window, tx),
    )

    tx = object()
    asyncio.run(MainWindow._broadcast_tx_in_background(window, TimeoutClient(), tx))

    assert events == [("broadcast", tx), ("finished", True)]


def test_main_window_reports_non_timeout_error_without_p2p_fallback(monkeypatch) -> None:
    """A non-timeout error is shown as an error and is not retried via p2p."""
    from bitcoin_safe.gui.qt import main as main_module
    from bitcoin_safe.gui.qt.main import MainWindow

    error = RuntimeError("non-mandatory-script-verify-flag")
    shown: list[Exception] = []
    monkeypatch.setattr(main_module, "caught_exception_message", lambda e, **_kwargs: shown.append(e))

    class FailingClient:
        def broadcast(self, _tx: object) -> None:
            raise error

    events: list[object] = []

    async def p2p_broadcast(_tx: object) -> bool:
        events.append("p2p")
        return True

    window = SimpleNamespace(
        p2p_listener=SimpleNamespace(broadcast_tx=p2p_broadcast),
        signals=SimpleNamespace(
            signal_broadcast_tx=SimpleNamespace(emit=lambda tx: events.append("broadcast")),
            signal_broadcast_tx_finished=SimpleNamespace(
                emit=lambda tx, sent: events.append(("finished", sent))
            ),
        ),
        tr=lambda message: message,
        _broadcast_tx_via_p2p_peers=lambda tx: MainWindow._broadcast_tx_via_p2p_peers(window, tx),
    )

    asyncio.run(MainWindow._broadcast_tx_in_background(window, FailingClient(), object()))

    assert shown == [error]
    assert events == [("finished", False)]
