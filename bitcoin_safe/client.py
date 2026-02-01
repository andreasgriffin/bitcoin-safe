#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread

from bitcoin_safe.cbf.cbf_sync import CbfSync
from bitcoin_safe.client_helpers import ProgressInfo, SyncStatus, UpdateInfo
from bitcoin_safe.i18n import translate
from bitcoin_safe.network_config import ElectrumConfig, Peer, Peers
from bitcoin_safe.network_utils import ProxyInfo, clean_electrum_url
from bitcoin_safe.p2p.peer_discovery import CBF_REQUIRED_SERVICE_FLAGS, PeerDiscovery

logger = logging.getLogger(__name__)


class Client:
    MAX_PROGRESS_WHILE_SYNC = 0.99
    BROADCAST_TIMEOUT = 3

    def __init__(
        self,
        client: bdk.ElectrumClient | bdk.EsploraClient | CbfSync,
        electrum_config: ElectrumConfig | None,
        proxy_info: ProxyInfo | None,
        loop_in_thread: LoopInThread,
    ) -> None:
        """Initialize instance."""
        self.client = client
        self.proxy_info = proxy_info
        self.electrum_config = electrum_config
        self.loop_in_thread = loop_in_thread

        self.start_time = datetime.now()
        self.progress: float = 0  # a number   "Between 0 and 1"
        self.status_msg = ""
        self._downloaded_blocks: set[str] = set()
        self._sync_status: SyncStatus = SyncStatus.unknown
        self._update_queue: asyncio.Queue[UpdateInfo] = asyncio.Queue()
        self._cbf_update_task: Future[None] | None = None
        self._stop_event: asyncio.Event = asyncio.Event()

        if isinstance(client, CbfSync):
            self.status_msg = translate("Client", "Connecting to nodes")
            self._sync_status = SyncStatus.syncing
            self._cbf_update_task = self.loop_in_thread.run_background(self._cbf_update_to_update_queue())

    @property
    def sync_status(self) -> SyncStatus:
        """Sync status."""
        return self._sync_status

    def set_sync_status(self, status: SyncStatus) -> bool:
        """Set sync status and returns if it was changed."""
        if status == self._sync_status:
            return False
        self._sync_status = status
        if self._sync_status == SyncStatus.synced:
            self.progress = 1
            self.status_msg = ""
        return True

    def handle_log_warning(self, warning: bdk.Warning) -> bool:
        """Handle log warning and returns and returns if the sync_status was changed."""
        if isinstance(warning, (bdk.Warning.NEED_CONNECTIONS, bdk.Warning.COULD_NOT_CONNECT)):
            self.status_msg = translate("Client", "Connecting to nodes")
        else:
            self.status_msg = warning.__class__.__name__
        if isinstance(self.client, CbfSync) and not self.client.node_running():
            return self.set_sync_status(SyncStatus.error)
        return False

    def handle_log_info(self, info: bdk.Info) -> bool:
        """Handle log info and returns if the sync_status was changed ."""
        if isinstance(info, bdk.Info.PROGRESS):
            new_progress = info.filters_downloaded_percent / 100
            if self.sync_status == SyncStatus.synced:
                # do not downgrade the sync status, merely on a Info.PROGRESS
                return False
            self.progress = min(self.MAX_PROGRESS_WHILE_SYNC, new_progress)
            self.status_msg = (
                translate("Client", "Chain height {height}").format(height=info.chain_height)
                if info.filters_downloaded_percent == 0
                else ""
            )

        if isinstance(info, bdk.Info.BLOCK_RECEIVED):
            if self._sync_status is SyncStatus.synced:
                return False

            self.progress = min(self.progress, self.MAX_PROGRESS_WHILE_SYNC)
            self._downloaded_blocks.update([str(v) for v in info._values])
            self.status_msg = translate("Client", "Downloaded {count} blocks").format(
                count=len(self._downloaded_blocks)
            )

        return self.set_sync_status(SyncStatus.syncing if self.progress < 1 else SyncStatus.synced)

    @property
    def passed_time(self):
        """Passed time."""
        return datetime.now() - self.start_time

    @property
    def remaining_time(
        self,
    ):
        """Remaining time."""
        if self.progress == 0:
            return self.passed_time
        return timedelta(
            seconds=self.passed_time.total_seconds() / max(0.001, self.progress) * (1 - self.progress)
        )

    @property
    def progress_info(self):
        """Progress info."""
        return ProgressInfo(
            progress=self.progress,
            passed_time=self.passed_time,
            remaining_time=self.remaining_time,
            status_msg=self.status_msg,
            sync_status=self.sync_status,
        )

    def on_update(self, update_info: UpdateInfo):
        """On update  and returns if the sync_status was changed ."""
        self.progress = 1
        self.status_msg = ""
        self.set_sync_status(SyncStatus.synced)

    def queue_update(self, update_info: UpdateInfo) -> None:
        """Queue update."""
        self._update_queue.put_nowait(update_info)
        self.on_update(update_info)

    def needs_progress_bar(
        self,
    ) -> bool:
        """Needs progress bar."""
        return isinstance(self.client, CbfSync)

    @classmethod
    def from_electrum(
        cls, url: str, use_ssl: bool, proxy_info: ProxyInfo | None, loop_in_thread: LoopInThread
    ) -> Client:
        """From electrum."""
        url = clean_electrum_url(url, use_ssl)
        client = bdk.ElectrumClient(
            url=url,
            socks5=(proxy_info.get_url_no_h() if proxy_info else None),
        )
        return cls(
            client=client,
            electrum_config=ElectrumConfig(url=url, use_ssl=use_ssl),
            proxy_info=proxy_info,
            loop_in_thread=loop_in_thread,
        )

    @classmethod
    def from_esplora(cls, url: str, proxy_info: ProxyInfo | None, loop_in_thread: LoopInThread) -> Client:
        """From esplora."""
        client = bdk.EsploraClient(url=url, proxy=(proxy_info.get_url_no_h() if proxy_info else None))
        return cls(client=client, electrum_config=None, proxy_info=proxy_info, loop_in_thread=loop_in_thread)

    @classmethod
    def from_cbf(
        cls,
        manual_peers: Peers | list[Peer] | None,
        bdkwallet: bdk.Wallet,
        proxy_info: ProxyInfo | None,
        data_dir: Path,
        cbf_connections: int,
        wallet_id: str,
        gap: int,
        loop_in_thread: LoopInThread,
        is_new_wallet=False,
    ):
        """From cbf."""
        peers: set[Peer] = set()

        if manual_peers:
            peers.update(manual_peers)

        p2p_discovery = PeerDiscovery(network=bdkwallet.network(), loop_in_thread=loop_in_thread)
        discovered_peers = loop_in_thread.run_foreground(
            p2p_discovery.get_bitcoin_peers(required_services=CBF_REQUIRED_SERVICE_FLAGS, lower_bound=200)
        )
        peers = peers.union(discovered_peers)

        client = CbfSync(
            wallet_id=wallet_id,
            gap=gap,
            data_dir=data_dir,
            wallet=bdkwallet,
            peers=[bdk_peer for peer in peers if (bdk_peer := peer.to_bdk(v2_transport=True))],
            proxy_info=proxy_info,
            cbf_connections=cbf_connections,
            is_new_wallet=is_new_wallet,
        )

        client.build_node()
        time.sleep(0.1)  # this prevents an ifinite loop of getting info messages from cbf client
        return cls(client=client, proxy_info=proxy_info, electrum_config=None, loop_in_thread=loop_in_thread)

    def broadcast(self, tx: bdk.Transaction):
        """Broadcast."""
        if isinstance(self.client, bdk.ElectrumClient):
            return self.client.transaction_broadcast(tx)
        elif isinstance(self.client, bdk.EsploraClient):
            return self.client.broadcast(tx)
        elif isinstance(self.client, CbfSync):
            assert self.client.client, "Not initialized"
            try:
                return self.loop_in_thread.run_foreground(
                    asyncio.wait_for(self.client.client.broadcast(tx), timeout=self.BROADCAST_TIMEOUT)
                )
            except asyncio.TimeoutError:
                logger.error("Broadcast timed out after 3 seconds")
                raise
        else:
            raise NotImplementedError(f"Client is of type {type(self.client)}")

    def full_scan(self, full_request: bdk.FullScanRequest, stop_gap: int) -> None:
        """Full scan."""
        if isinstance(self.client, bdk.ElectrumClient):
            self.start_time = datetime.now()
            self.progress = 0
            self.status_msg = translate("Client", "Syncing via Electrum")
            self.set_sync_status(SyncStatus.syncing)
            update = self.client.full_scan(
                request=full_request,
                stop_gap=stop_gap,
                batch_size=100,
                fetch_prev_txouts=True,
            )
            update_info = UpdateInfo(update, UpdateInfo.UpdateType.full_sync)
            self.queue_update(update_info)
            return None
        elif isinstance(self.client, bdk.EsploraClient):
            self.start_time = datetime.now()
            self.progress = 0
            self.status_msg = translate("Client", "Syncing via Esplora")
            self.set_sync_status(SyncStatus.syncing)
            update = self.client.full_scan(
                request=full_request,
                stop_gap=stop_gap,
                parallel_requests=2,
            )
            update_info = UpdateInfo(update, UpdateInfo.UpdateType.full_sync)
            self.queue_update(update_info)
            return None
        elif isinstance(self.client, CbfSync):
            return None
        else:
            raise ValueError("Unknown blockchain client type.")

    def sync(self, request: bdk.SyncRequest) -> None:
        """Sync."""
        if isinstance(self.client, bdk.ElectrumClient):
            self.start_time = datetime.now()
            self.progress = 0
            self.status_msg = translate("Client", "Syncing via Electrum")
            self.set_sync_status(SyncStatus.syncing)
            update = self.client.sync(
                request=request,
                batch_size=100,
                fetch_prev_txouts=True,
            )
            update_info = UpdateInfo(update, UpdateInfo.UpdateType.full_sync)
            self.queue_update(update_info)
            return None

        elif isinstance(self.client, bdk.EsploraClient):
            self.start_time = datetime.now()
            self.progress = 0
            self.status_msg = translate("Client", "Syncing via Esplora")
            self.set_sync_status(SyncStatus.syncing)
            update = self.client.sync(
                request=request,
                parallel_requests=2,
            )
            update_info = UpdateInfo(update, UpdateInfo.UpdateType.full_sync)
            self.queue_update(update_info)
            return None
        elif isinstance(self.client, CbfSync):
            return None
        else:
            raise ValueError("Unknown blockchain client type.")

    async def _cbf_update_to_update_queue(self):
        "Put the updates from cbf into _update_queue"
        if not isinstance(self.client, CbfSync):
            return
        while True:
            update_info = await self.client.next_update_info()
            if not update_info:
                continue
            self.queue_update(update_info)

    async def update(self) -> UpdateInfo | None:
        """Update."""
        return await self._update_queue.get()

    async def next_info(self) -> bdk.Info | None:
        """Next info."""
        if isinstance(self.client, CbfSync):
            return await self.client.next_info()
        await self._stop_event.wait()
        return None

    async def next_warning(self) -> bdk.Warning | None:
        """Next warning."""
        if isinstance(self.client, CbfSync):
            return await self.client.next_warning()
        await self._stop_event.wait()
        return None

    def stop(self) -> None:
        """Stop background tasks."""
        self._stop_event.set()
        if self._cbf_update_task and not self._cbf_update_task.done():
            self._cbf_update_task.cancel()
        self._cbf_update_task = None

    def close(self):
        """Close."""
        self.stop()
        if isinstance(self.client, bdk.ElectrumClient):
            pass
        elif isinstance(self.client, bdk.EsploraClient):
            pass
        elif isinstance(self.client, CbfSync):
            self.client.shutdown_node()
        else:
            raise NotImplementedError(f"Client is of type {type(self.client)}")
