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

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bitcoin_qr_tools.data import DataType
from PyQt6.QtWidgets import QMessageBox

from bitcoin_safe.broadcast_types import BroadcastCompletion, BroadcastOutcome, BroadcastRequest
from bitcoin_safe.gui.qt.ui_tx.ui_tx_base import UITx_Base
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.util import MessageType
from bitcoin_safe.tx import HiddenTxUiInfos, PostBroadcastEnum


def test_broadcast_queues_request_without_blocking() -> None:
    """The viewer submits a request and defers all UI results until completion."""
    emitted_requests: list[BroadcastRequest] = []
    spin_events: list[str] = []
    viewer = SimpleNamespace(
        signals=SimpleNamespace(signal_broadcast_request=SimpleNamespace(emit=emitted_requests.append)),
        button_send=SimpleNamespace(start_spin=lambda: spin_events.append("start")),
        _broadcast_requests={},
    )

    assert UITx_Viewer._broadcast(viewer, object())
    assert len(emitted_requests) == 1
    assert spin_events == ["start"]
    assert viewer._broadcast_requests == {emitted_requests[0].request_id: emitted_requests[0].tx}


def test_broadcast_timeout_completion_shows_explanation() -> None:
    """A timeout result retains the dedicated unknown-status explanation."""
    tx = SimpleNamespace()
    events: list[str] = []
    viewer = SimpleNamespace(
        _broadcast_requests={"request": tx},
        signal_broadcast_finished=SimpleNamespace(emit=lambda: events.append("spinner_stop")),
        _show_broadcast_timeout=lambda: events.append("timeout_message"),
        tr=lambda message: message,
    )

    UITx_Viewer.on_broadcast_complete(
        viewer,
        BroadcastCompletion(
            txid="txid",
            request_ids=("request",),
            outcome=BroadcastOutcome.failure,
            successful_route=None,
            attempts=(),
            wallet_timeout=True,
        ),
    )

    assert not viewer._broadcast_requests
    assert events == ["spinner_stop", "timeout_message"]


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


def test_broadcast_ignores_repeat_send_while_in_flight(monkeypatch) -> None:
    """A second send while a request is pending must not queue or save again."""
    monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.is_nlocktime_already_valid", lambda *_: True)
    events: list[str] = []
    tx = SimpleNamespace(lock_time=lambda: 0)
    viewer = SimpleNamespace(
        data=SimpleNamespace(data_type=DataType.Tx, data=tx),
        _broadcast_requests={"pending": tx},
        _get_robust_height=lambda: 0,
        _set_blockchain=lambda: None,
        client=object(),
        _broadcast=lambda _tx: events.append("broadcast") or True,
    )

    UITx_Viewer.broadcast(viewer)

    assert events == []


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

    def save_local_tx(_tx: FakeTransaction | None = None) -> None:
        events.append("save_local")

    requests: list[BroadcastRequest] = []

    def broadcast(_tx: FakeTransaction) -> bool:
        events.append("broadcast")
        request = BroadcastRequest.create(_tx)
        requests.append(request)
        return broadcast_success

    viewer = SimpleNamespace(
        data=SimpleNamespace(data_type=DataType.Tx, data=FakeTransaction()),
        hidden_tx_infos=HiddenTxUiInfos(save_local_on_send=True),
        post_broadcast_action=PostBroadcastEnum.open_hist_list,
        _post_broadcast_consumed_txid=None,
        _broadcast_requests={},
        signal_broadcast_finished=SimpleNamespace(emit=lambda: None),
        _on_broadcast_success=lambda tx: UITx_Viewer._on_broadcast_success(viewer, tx),
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

    if requests and broadcast_success:
        request = requests[0]
        viewer._broadcast_requests[request.request_id] = request.tx
        UITx_Viewer.on_broadcast_complete(
            viewer,
            BroadcastCompletion(
                txid="txid",
                request_ids=(request.request_id,),
                outcome=BroadcastOutcome.success,
                successful_route=None,
                attempts=(),
            ),
        )

    assert events == expected_events


@pytest.mark.parametrize(
    "wallet_heights, mempool_height, expected",
    [
        ([0, 250], 999, 250),  # an unsynced wallet must not win over a synced one
        ([120, 250], 999, 250),  # the highest synced wallet is the chain tip
        ([0, 0], 999, 999),  # no synced wallet: fall back to the mempool tip
        ([], 999, 999),  # no wallet loaded: fall back to the mempool tip
    ],
)
def test_robust_height_uses_chain_tip(wallet_heights: list[int], mempool_height: int, expected: int) -> None:
    """The robust height is the highest synced wallet height, else the mempool tip."""
    wallets = [SimpleNamespace(id=f"w{i}", get_height=lambda h=h: h) for i, h in enumerate(wallet_heights)]
    viewer = SimpleNamespace(
        wallet_functions=object(),
        mempool_manager=SimpleNamespace(block_tip_height=lambda: mempool_height),
    )
    with patch("bitcoin_safe.gui.qt.ui_tx.ui_tx_base.get_wallets", return_value=wallets):
        assert UITx_Base._get_robust_height(viewer) == expected
