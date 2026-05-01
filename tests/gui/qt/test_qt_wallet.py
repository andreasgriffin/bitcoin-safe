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

from bitcoin_safe.client_helpers import UpdateInfo
from bitcoin_safe.gui.qt.qt_wallet import QTWallet, SyncStatus


class SignalRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def emit(self, *args: object) -> None:
        self.calls.append(args)


class LoopRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_task(self, coro, **kwargs) -> None:
        self.calls.append({"kwargs": kwargs})
        coro.close()


async def _noop() -> None:
    return None


def _make_qt_wallet_stub(has_gap_overhang: bool) -> tuple[SimpleNamespace, LoopRecorder]:
    loop_in_thread = LoopRecorder()
    wallet = SimpleNamespace(
        client=SimpleNamespace(sync_status=SyncStatus.synced),
        get_height_no_cache=lambda: 7,
        _more_than_gap_revealed_addresses=lambda: has_gap_overhang,
    )
    qt_wallet = SimpleNamespace(
        wallet=wallet,
        refresh_caches_and_ui_lists=lambda force_ui_refresh, chain_height_advanced: None,
        fx=SimpleNamespace(update_if_needed=lambda: None),
        save=lambda: None,
        signal_after_sync=SignalRecorder(),
        loop_in_thread=loop_in_thread,
        _sync_revealed_spks=lambda: _noop(),
        _sync_on_done=lambda result: None,
        _sync_on_success=lambda result: None,
        _sync_on_error=lambda error: None,
        tr=lambda message: message,
    )
    return qt_wallet, loop_in_thread


@pytest.mark.parametrize(
    ("update_type", "expected_runs"),
    [
        (UpdateInfo.UpdateType.full_sync, 1),
        (UpdateInfo.UpdateType.sync_revealed_spks, 0),
    ],
)
def test_on_update_resyncs_revealed_spks_only_after_full_sync(update_type, expected_runs) -> None:
    """The revealed-SPK follow-up sync should run only after the initial full scan."""
    qt_wallet, loop_in_thread = _make_qt_wallet_stub(has_gap_overhang=True)

    QTWallet.on_update(
        qt_wallet,
        UpdateInfo(update="ignored", update_type=update_type),
    )

    assert len(loop_in_thread.calls) == expected_runs


def test_notify_sync_error_only_emits_once_until_success() -> None:
    notifications: list[object] = []
    qt_wallet = SimpleNamespace(
        wallet=SimpleNamespace(id="wallet-1"),
        signals=SimpleNamespace(
            notification=SimpleNamespace(emit=lambda message: notifications.append(message))
        ),
        _has_unacknowledged_sync_error=False,
        tr=lambda message: message,
    )

    QTWallet._notify_sync_error(qt_wallet, RuntimeError("offline"))
    QTWallet._notify_sync_error(qt_wallet, RuntimeError("offline"))

    assert len(notifications) == 1

    QTWallet._sync_on_success(qt_wallet, result=None)
    QTWallet._notify_sync_error(qt_wallet, RuntimeError("offline again"))

    assert len(notifications) == 2
