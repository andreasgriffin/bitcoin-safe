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


import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_usb.address_types import DescriptorInfo

from bitcoin_safe.cbf.cbf_sync import CbfSync
from bitcoin_safe.client_helpers import ProgressInfo, SyncStatus, UpdateInfo
from bitcoin_safe.descriptors import min_blockheight
from bitcoin_safe.i18n import translate
from bitcoin_safe.network_config import ElectrumConfig, Peer
from bitcoin_safe.network_utils import ProxyInfo, clean_electrum_url
from bitcoin_safe.p2p.peer_discovery import CBF_REQUIRED_SERVICE_FLAGS, PeerDiscovery

logger = logging.getLogger(__name__)


class Client:
    def __init__(
        self,
        client: Union[bdk.ElectrumClient, bdk.EsploraClient, CbfSync],
        electrum_config: ElectrumConfig | None,
        proxy_info: ProxyInfo | None,
        loop_in_thread: LoopInThread,
    ) -> None:
        self.client = client
        self.proxy_info = proxy_info
        self.electrum_config = electrum_config
        self.loop_in_thread = loop_in_thread

        self.start_time = datetime.now()
        self.progress: float = 0  # a number   "Between 0 and 1"
        self.status_msg = ""
        self._sync_status: SyncStatus = SyncStatus.unknown
        self._update_queue: asyncio.Queue[UpdateInfo] = asyncio.Queue()

        if isinstance(client, CbfSync):
            self.status_msg = translate("Client", "Connecting to nodes")
            self._sync_status = SyncStatus.syncing
            self.loop_in_thread.run_background(self._cbf_update_to_update_queue())

    @property
    def sync_status(self) -> SyncStatus:
        return self._sync_status

    def _set_sync_status(self, status: SyncStatus) -> None:
        self._sync_status = status

    def handle_log_warning(self, warning: bdk.Warning):
        if isinstance(warning, (bdk.Warning.NEED_CONNECTIONS, bdk.Warning.COULD_NOT_CONNECT)):
            self.status_msg = translate("Client", "Connecting to nodes")
        elif isinstance(warning, bdk.Warning.EMPTY_PEER_DATABASE):
            self.status_msg = translate("Client", "Discovering nodes")
        else:
            self.status_msg = warning.__class__.__name__

    def should_update_progress(self):
        if isinstance(self.client, CbfSync):
            # kyoto update is the only reliable way to know it is fully synced.
            # any warning or info message dies not reflect the sync status
            # therefore, once synced (an update was received) i do not go back to syncing
            # TODO: this should be enhanced with detection of internet connectivity
            # or once synced with connections_met, need_connections change.
            # The problem is connections_met does not imply it is synced
            return self.sync_status != SyncStatus.synced
        # for electrum/esplora I should always update the status
        return True

    def handle_log_info(self, info: bdk.Info):
        if isinstance(info, bdk.Info.NEW_CHAIN_HEIGHT):
            self.progress = 0.05
            self.status_msg = translate("Client", "New chain height {height}").format(height=info.height)
        elif isinstance(info, bdk.Info.PROGRESS):
            self.progress = info.progress / 100
        elif isinstance(info, bdk.Info.STATE_UPDATE):
            if info.node_state == bdk.NodeState.BEHIND:
                self.status_msg = translate("Client", "Syncing")
            elif info.node_state == bdk.NodeState.FILTER_HEADERS_SYNCED:
                self.status_msg = translate("Client", "Synced the filter headers")
            elif info.node_state == bdk.NodeState.FILTERS_SYNCED:
                self.status_msg = translate("Client", "Filters synced")
            elif info.node_state == bdk.NodeState.TRANSACTIONS_SYNCED:
                self.status_msg = translate("Client", "Transactions synced")
            elif info.node_state == bdk.NodeState.HEADERS_SYNCED:
                self.status_msg = translate("Client", "Headers synced")
            else:
                self.status_msg = ""

    @property
    def passed_time(self):
        return datetime.now() - self.start_time

    @property
    def remaining_time(
        self,
    ):
        if self.progress == 0:
            return self.passed_time
        return timedelta(
            seconds=self.passed_time.total_seconds() / max(0.001, self.progress) * (1 - self.progress)
        )

    @property
    def progress_info(self):
        return ProgressInfo(
            progress=self.progress,
            passed_time=self.passed_time,
            remaining_time=self.remaining_time,
            status_msg=self.status_msg,
        )

    def on_update(self, update_info: UpdateInfo) -> None:
        self.progress = 1
        self.status_msg = ""
        self._set_sync_status(SyncStatus.synced)

    def queue_update(self, update_info: UpdateInfo) -> None:
        self._update_queue.put_nowait(update_info)
        self.on_update(update_info)

    def needs_progress_bar(
        self,
    ) -> bool:
        return isinstance(self.client, CbfSync)

    @classmethod
    def from_electrum(
        cls, url: str, use_ssl: bool, proxy_info: ProxyInfo | None, loop_in_thread: LoopInThread
    ) -> "Client":
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
    def from_esplora(cls, url: str, proxy_info: ProxyInfo | None, loop_in_thread: LoopInThread) -> "Client":
        client = bdk.EsploraClient(url=url, proxy=(proxy_info.get_url_no_h() if proxy_info else None))
        return cls(client=client, electrum_config=None, proxy_info=proxy_info, loop_in_thread=loop_in_thread)

    @classmethod
    def from_cbf(
        cls,
        initial_peer: Peer | None,
        bdkwallet: bdk.Wallet,
        multipath_descriptor: bdk.Descriptor,
        proxy_info: ProxyInfo | None,
        data_dir: Path,
        cbf_connections: int,
        wallet_id: str,
        loop_in_thread: LoopInThread,
        is_new_wallet=False,
    ):
        client = CbfSync(wallet_id=wallet_id)
        peers: set[Peer] = set()

        if initial_peer:
            peers.add(initial_peer)

        discovered_peers = PeerDiscovery(network=bdkwallet.network()).get_bitcoin_peers(
            required_services=CBF_REQUIRED_SERVICE_FLAGS, lower_bound=200
        )
        peers = peers.union(discovered_peers)

        client.build_node(
            data_dir=data_dir,
            wallet=bdkwallet,
            peers=[bdk_peer for peer in peers if (bdk_peer := peer.to_bdk(v2_transport=True))],
            proxy_info=proxy_info,
            recovery_height=min_blockheight(
                DescriptorInfo.from_str(str(multipath_descriptor)).address_type, network=bdkwallet.network()
            ),
            cbf_connections=cbf_connections,
            is_new_wallet=is_new_wallet,
        )
        return cls(client=client, proxy_info=proxy_info, electrum_config=None, loop_in_thread=loop_in_thread)

    def broadcast(self, tx: bdk.Transaction):
        if isinstance(self.client, bdk.ElectrumClient):
            return self.client.transaction_broadcast(tx)
        elif isinstance(self.client, bdk.EsploraClient):
            return self.client.broadcast(tx)
        elif isinstance(self.client, CbfSync):
            assert self.client.client, "Not initialized"
            return self.client.client.broadcast(tx)
        else:
            raise NotImplementedError(f"Client is of type {type(self.client)}")

    def full_scan(self, full_request: bdk.FullScanRequest, stop_gap: int) -> None:
        if isinstance(self.client, bdk.ElectrumClient):
            self.start_time = datetime.now()
            self.progress = 0
            self.status_msg = translate("Client", "Syncing via Electrum")
            self._set_sync_status(SyncStatus.syncing)
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
            self._set_sync_status(SyncStatus.syncing)
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
        if isinstance(self.client, bdk.ElectrumClient):
            self.start_time = datetime.now()
            self.progress = 0
            self.status_msg = translate("Client", "Syncing via Electrum")
            self._set_sync_status(SyncStatus.syncing)
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
            self._set_sync_status(SyncStatus.syncing)
            update = self.client.sync(
                request=request,
                parallel_requests=2,
            )
            update_info = UpdateInfo(update, UpdateInfo.UpdateType.full_sync)
            self.queue_update(update_info)
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
        return await self._update_queue.get()

    async def next_log(self) -> str | None:
        if isinstance(self.client, CbfSync):
            return await self.client.next_log()
        await asyncio.get_running_loop().create_future()  # waits until cancelled
        return None

    async def next_info(self) -> bdk.Info | None:
        if isinstance(self.client, CbfSync):
            return await self.client.next_info()
        await asyncio.get_running_loop().create_future()  # waits until cancelled
        return None

    async def next_warning(self) -> bdk.Warning | None:
        if isinstance(self.client, CbfSync):
            return await self.client.next_warning()
        await asyncio.get_running_loop().create_future()  # waits until cancelled
        return None

    def close(self):

        if isinstance(self.client, bdk.ElectrumClient):
            pass
        elif isinstance(self.client, bdk.EsploraClient):
            pass
        elif isinstance(self.client, CbfSync):
            self.client.shutdown_node()
        else:
            raise NotImplementedError(f"Client is of type {type(self.client)}")
