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

from types import SimpleNamespace

import pytest
from bitcoin_qr_tools.data import DataType

from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.tx import HiddenTxUiInfos


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
        client=object(),
        save_local_tx=save_local_tx,
        _get_robust_height=lambda: 0,
        _set_blockchain=lambda: None,
        _broadcast=broadcast,
        tr=lambda message: message,
    )

    UITx_Viewer.broadcast(viewer)

    assert events == expected_events
