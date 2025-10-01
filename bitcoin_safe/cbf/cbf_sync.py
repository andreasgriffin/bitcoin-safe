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
from concurrent import futures
from pathlib import Path
from typing import Any, Callable, Coroutine, List, Optional, TypeVar, cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.signals import TypedPyQtSignal

logger = logging.getLogger(__name__)

PERSISTENCE_FILES = [
    Path("./data/bdk_persistence.sqlite"),
    Path("./data/signet/headers.db"),
    Path("./data/signet/peers.db"),
]


T = TypeVar("T")


class CbfSync(QObject):
    """
    Encapsulates Bitcoin CBF synchronization logic, exposing PyQt signals for UI.
    """

    log_str = cast(TypedPyQtSignal[str], pyqtSignal(str))
    log_info = cast(TypedPyQtSignal[bdk.Info], pyqtSignal(bdk.Info))
    log_warning = cast(TypedPyQtSignal[bdk.Warning], pyqtSignal(bdk.Warning))
    signal_update = cast(TypedPyQtSignal[bdk.Update], pyqtSignal(bdk.Update))

    def __init__(
        self,
        wallet_id: str,
    ):
        super().__init__()
        self.client: Optional[bdk.CbfClient] = None
        self.tasks: List[futures._base.Future] = []
        self.loop_in_thread = LoopInThread()
        self._height: int = 0
        self.wallet_id = wallet_id

        self.log_info.connect(self.on_log_info)
        self.log_str.connect(self.on_log_str)
        self.log_warning.connect(self.on_log_warning)
        self.signal_update.connect(self.on_signal_update)

    def on_log_info(self, info: bdk.Info):
        if isinstance(info, bdk.Info.NEW_CHAIN_HEIGHT):
            self._height = info.height

        if isinstance(info, bdk.Info.NEW_FORK):
            self._height = info.height

        logger.info(f"{self.wallet_id} - {info}")

    def on_log_str(self, log: str):
        # there are a lot of logs and it can block the UI to log them all
        if "Chain updated" in log:
            # this is so fast, that it can freeze the UI
            return
        logger.info(f"{self.wallet_id} - {log}")

    def on_log_warning(self, warning: bdk.Warning):
        logger.info(f"{self.wallet_id} - {warning}")

    def on_signal_update(self, update: bdk.Update):
        logger.info(f"{self.wallet_id} - {update}")

    def get_height(self) -> int:
        return self._height

    async def _monitor_log(self):
        if not self.client:
            return
        await self._convert_to_signal(coro=self.client.next_log, signal=self.log_str)

    async def _monitor_info(self):
        if not self.client:
            return
        await self._convert_to_signal(coro=self.client.next_info, signal=self.log_info)

    async def _monitor_warning(self):
        if not self.client:
            return
        await self._convert_to_signal(coro=self.client.next_warning, signal=self.log_warning)

    async def _monitor_updates(self):
        if not self.client:
            return
        await self._convert_to_signal(coro=self.client.update, signal=self.signal_update)

    async def _convert_to_signal(
        self, coro: Callable[[], Coroutine[Any, Any, T]], signal: TypedPyQtSignal[T]
    ):
        if not self.client:
            logger.error(f"{self.client=} cannot start {coro=}")
            return
        try:
            while True:
                res = await coro()
                if res is None:
                    continue  # type: ignore

                signal.emit(res)
        except asyncio.CancelledError:
            logger.error(f"Cancelled {coro=}")
            return

    def build_node(
        self,
        wallet: bdk.Wallet,
        peers: List[bdk.Peer],
        data_dir: Path,
        proxy_info: ProxyInfo | None,
        cbf_connections: int,
        recovery_height: int = 0,
        is_new_wallet=False,
    ):
        if is_new_wallet and wallet.latest_checkpoint().height == 0:
            scan_type = cast(bdk.ScanType, bdk.ScanType.NEW())
        else:
            if wallet.latest_checkpoint().height == 0:
                scan_type = cast(bdk.ScanType, bdk.ScanType.RECOVERY(from_height=recovery_height))
            else:
                scan_type = cast(bdk.ScanType, bdk.ScanType.SYNC())
        builder = bdk.CbfBuilder().scan_type(scan_type=scan_type).data_dir(data_dir=str(data_dir))
        if proxy_info:
            builder = builder.socks5_proxy(proxy=proxy_info.to_bdk())
        if peers:
            builder = builder.peers(peers)
        builder = builder.connections(cbf_connections)

        # timeout, new release
        # info messages, height, fork

        components = builder.build(wallet)
        self.client = components.client
        self.node = components.node

        self.tasks.append(self.loop_in_thread.run_background(self._monitor_log()))
        self.tasks.append(self.loop_in_thread.run_background(self._monitor_info()))
        self.tasks.append(self.loop_in_thread.run_background(self._monitor_warning()))
        self.tasks.append(
            self.loop_in_thread.run_background(
                self._monitor_updates(),
            )
        )
        self.node.run()
        logger.info(f"Started node")

    def shutdown_node(self):
        if self.client:
            self.client.shutdown()

        for task in self.tasks:
            if task and not task.done():
                task.cancel()

    def node_running(self) -> bool:
        if not self.client:
            return False
        if not self.tasks:
            return False
        return not all([t.done() for t in self.tasks])

    def close(self):
        self.shutdown_node()
        self.loop_in_thread.stop()
