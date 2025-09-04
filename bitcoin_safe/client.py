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


import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union, cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalTracker
from bitcoin_usb.address_types import DescriptorInfo
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.cbf.cbf_sync import CbfSync
from bitcoin_safe.descriptors import min_blockheight
from bitcoin_safe.network_config import ElectrumConfig, Peer
from bitcoin_safe.network_utils import ProxyInfo, clean_electrum_url
from bitcoin_safe.signals import TypedPyQtSignal

logger = logging.getLogger(__name__)


class SyncStatus(enum.Enum):
    unknown = enum.auto()
    unsynced = enum.auto()
    syncing = enum.auto()
    synced = enum.auto()
    error = enum.auto()


@dataclass
class ProgressInfo:
    progress: float = field(metadata={"description": "Between 0 and 1"})
    passed_time: timedelta
    remaining_time: timedelta
    status_msg: str


class Client(QObject):
    signal_update = cast(TypedPyQtSignal[bdk.Update], pyqtSignal(bdk.Update))
    signal_sync_status = cast(TypedPyQtSignal[SyncStatus], pyqtSignal(SyncStatus))
    signal_progress = cast(TypedPyQtSignal[ProgressInfo], pyqtSignal(ProgressInfo))

    def __init__(
        self,
        client: Union[bdk.ElectrumClient, bdk.EsploraClient, CbfSync],
        electrum_config: ElectrumConfig | None,
        proxy_info: ProxyInfo | None,
    ) -> None:
        super().__init__()
        self.client = client
        self.proxy_info = proxy_info
        self.electrum_config = electrum_config

        self.signal_tracker = SignalTracker()
        self.start_time = datetime.now()
        self.progress: float = 0  # a number   "Between 0 and 1"
        self.status_msg = ""

        if isinstance(client, CbfSync):
            self.signal_tracker.connect(client.signal_update, self.apply_update)
            self.signal_tracker.connect(client.log_info, self._on_cbf_log_info)
            self.signal_tracker.connect(client.log_warning, self._on_cbf_log_warning)

            self.status_msg = self.tr("Connecting to nodes")
            self.signal_sync_status.emit(SyncStatus.syncing)
            self.signal_progress.emit(
                ProgressInfo(
                    progress=0,
                    passed_time=timedelta(hours=0),
                    remaining_time=timedelta(hours=1),
                    status_msg=self.status_msg,
                )
            )

    def _on_cbf_log_warning(self, warning: bdk.Warning):
        if isinstance(warning, (bdk.Warning.NEED_CONNECTIONS, bdk.Warning.COULD_NOT_CONNECT)):
            self.status_msg = self.tr("Connecting to nodes")
        elif isinstance(warning, bdk.Warning.EMPTY_PEER_DATABASE):
            self.status_msg = self.tr("Discovering nodes")
        else:
            self.status_msg = warning.__class__.__name__

        # if isinstance(warning, bdk.Warning.NEED_CONNECTIONS):
        #     self.signal_sync_status.emit(SyncStatus.syncing)

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

    def _on_cbf_log_info(self, info: bdk.Info):
        if isinstance(info, bdk.Info.NEW_CHAIN_HEIGHT):
            self.progress = 0.05
            self.status_msg = self.tr("New chain height {height}").format(height=info.height)
            self.signal_progress.emit(self.progress_info)

        elif isinstance(info, bdk.Info.PROGRESS):
            self.progress = info.progress / 100
            self.signal_progress.emit(self.progress_info)

        elif isinstance(info, bdk.Info.CONNECTIONS_MET):
            pass
            # self.signal_sync_status.emit(SyncStatus.syncing)

        elif isinstance(info, bdk.Info.STATE_UPDATE):
            if info.node_state == bdk.NodeState.BEHIND:
                self.status_msg = self.tr("Syncing")
            elif info.node_state == bdk.NodeState.FILTER_HEADERS_SYNCED:
                self.status_msg = self.tr("Synced the filter headers")
            elif info.node_state == bdk.NodeState.FILTERS_SYNCED:
                self.status_msg = self.tr("Filters synced")
            elif info.node_state == bdk.NodeState.TRANSACTIONS_SYNCED:
                self.status_msg = self.tr("Transactions synced")
            elif info.node_state == bdk.NodeState.HEADERS_SYNCED:
                self.status_msg = self.tr("Headers synced")
            else:
                self.status_msg = ""

    def apply_update(self, update: bdk.Update):
        self.progress = 1
        self.status_msg = ""
        self.signal_update.emit(update)
        self.signal_progress.emit(self.progress_info)
        self.signal_sync_status.emit(SyncStatus.synced)

    def needs_progress_bar(
        self,
    ) -> bool:
        return isinstance(self.client, CbfSync)

    @classmethod
    def from_electrum(cls, url: str, use_ssl: bool, proxy_info: ProxyInfo | None) -> "Client":
        url = clean_electrum_url(url, use_ssl)
        client = bdk.ElectrumClient(
            url=url,
            socks5=(proxy_info.get_url_no_h() if proxy_info else None),
        )
        return cls(
            client=client, electrum_config=ElectrumConfig(url=url, use_ssl=use_ssl), proxy_info=proxy_info
        )

    @classmethod
    def from_esplora(cls, url: str, proxy_info: ProxyInfo | None) -> "Client":
        client = bdk.EsploraClient(url=url, proxy=(proxy_info.get_url_no_h() if proxy_info else None))
        return cls(client=client, electrum_config=None, proxy_info=proxy_info)

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
        is_new_wallet=False,
    ):
        client = CbfSync(wallet_id=wallet_id)
        client.build_node(
            data_dir=data_dir,
            wallet=bdkwallet,
            peers=[initial_peer.to_bdk()] if initial_peer else [],
            proxy_info=proxy_info,
            recovery_height=min_blockheight(
                DescriptorInfo.from_str(str(multipath_descriptor)).address_type, network=bdkwallet.network()
            ),
            cbf_connections=cbf_connections,
            is_new_wallet=is_new_wallet,
        )
        return cls(client=client, proxy_info=proxy_info, electrum_config=None)

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

    def full_scan(self, full_request: bdk.FullScanRequest, stop_gap: int):
        if isinstance(self.client, bdk.ElectrumClient):
            self.signal_sync_status.emit(SyncStatus.syncing)
            self.start_time = datetime.now()
            update = self.client.full_scan(
                request=full_request, stop_gap=stop_gap, batch_size=100, fetch_prev_txouts=True
            )
            self.apply_update(update)
        elif isinstance(self.client, bdk.EsploraClient):
            self.signal_sync_status.emit(SyncStatus.syncing)
            self.start_time = datetime.now()
            update = self.client.full_scan(request=full_request, stop_gap=stop_gap, parallel_requests=2)
            self.apply_update(update)
        elif isinstance(self.client, CbfSync):
            return
        else:
            raise ValueError("Unknown blockchain client type.")

    def close(self):
        self.signal_tracker.disconnect_all()
        if isinstance(self.client, bdk.ElectrumClient):
            pass
        elif isinstance(self.client, bdk.EsploraClient):
            pass
        elif isinstance(self.client, CbfSync):
            self.client.shutdown_node()
        else:
            raise NotImplementedError(f"Client is of type {type(self.client)}")
