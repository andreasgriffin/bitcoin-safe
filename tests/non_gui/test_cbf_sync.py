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
from unittest.mock import Mock

import bdkpython as bdk
import pytest

from bitcoin_safe.cbf.cbf_sync import CBF_UPDATE_INTERVAL, CbfSync
from bitcoin_safe.client import Client
from bitcoin_safe.client_helpers import SyncStatus


def test_cbf_sync_close_shuts_down_node() -> None:
    """Closing CBF sync shuts down its running node."""
    cbf_sync = object.__new__(CbfSync)
    cbf_sync.shutdown_node = Mock()

    cbf_sync.close()

    cbf_sync.shutdown_node.assert_called_once_with()


@pytest.mark.parametrize(
    ("checkpoint", "is_new_wallet", "expected"),
    [
        (0, True, bdk.ScanType.NEW_WALLET),
        (0, False, bdk.ScanType.RECOVERY),
        (100, True, bdk.ScanType.SYNC),
        (100, False, bdk.ScanType.SYNC),
    ],
)
def test_cbf_builder_selects_scan_type(monkeypatch, tmp_path, checkpoint, is_new_wallet, expected):
    wallet = Mock()
    wallet.latest_checkpoint.return_value.height = checkpoint
    builder = Mock()
    builder.scan_type.return_value = builder
    builder.emit_update_every_n_blocks.return_value = builder
    builder.connections.return_value = builder
    monkeypatch.setattr("bitcoin_safe.cbf.cbf_sync.bdk.CbfBuilder", lambda: builder)
    monkeypatch.setattr("bitcoin_safe.cbf.cbf_sync.DescriptorInfo.from_str", lambda _descriptor: Mock())
    monkeypatch.setattr(
        "bitcoin_safe.cbf.cbf_sync.get_recovery_point",
        lambda *args, **kwargs: bdk.RecoveryPoint.GENESIS_BLOCK(),
    )
    cbf = CbfSync("test", wallet, [], tmp_path, None, 1, is_new_wallet=is_new_wallet)

    cbf.build_node()

    assert isinstance(builder.scan_type.call_args.kwargs["scan_type"], expected)
    builder.emit_update_every_n_blocks.assert_called_once_with(CBF_UPDATE_INTERVAL)
    builder.build.assert_called_once_with(wallet)


def test_cbf_intermediate_updates_do_not_mark_wallet_synced(tmp_path):
    wallet = Mock()
    wallet.latest_checkpoint.return_value.height = 1_000
    cbf = CbfSync("test", wallet, [], tmp_path, None, 1)
    cbf._height = 2_000
    client = object.__new__(Client)
    client.client = cbf
    client._sync_status = SyncStatus.syncing
    client.progress = 0.5
    client.status_msg = ""
    client._update_queue = asyncio.Queue()
    update = Mock()

    client.queue_update(update)
    client.on_update(update)
    assert client.sync_status == SyncStatus.syncing
    assert client.progress < 1

    wallet.latest_checkpoint.return_value.height = 2_000
    client.on_update(update)
    assert client.sync_status == SyncStatus.synced
    assert client.progress == 1
