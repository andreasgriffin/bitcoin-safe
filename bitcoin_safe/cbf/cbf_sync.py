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
from concurrent.futures import Future
from pathlib import Path
from typing import Any, List, Optional, cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread

from bitcoin_safe.client_helpers import UpdateInfo
from bitcoin_safe.network_utils import ProxyInfo

logger = logging.getLogger(__name__)

PERSISTENCE_FILES = [
    Path("./data/bdk_persistence.sqlite"),
    Path("./data/signet/headers.db"),
    Path("./data/signet/peers.db"),
]


class CbfSync:
    """Encapsulates Bitcoin CBF synchronization logic using asyncio primitives."""

    def __init__(
        self,
        wallet_id: str,
    ):
        self.client: Optional[bdk.CbfClient] = None
        self.tasks: List[Future[Any]] = []
        self.loop_in_thread = LoopInThread()
        self._height: int = 0
        self.wallet_id = wallet_id

    def _handle_log_info(self, info: bdk.Info):
        if isinstance(info, bdk.Info.NEW_CHAIN_HEIGHT):
            self._height = info.height

        if isinstance(info, bdk.Info.NEW_FORK):
            self._height = info.height

        logger.info(f"{self.wallet_id} - {info}")

    def _handle_log_str(self, log: str):
        # there are a lot of logs and it can block the UI to log them all
        if "Chain updated" in log:
            # this is so fast, that it can freeze the UI
            return
        logger.info(f"{self.wallet_id} - {log}")

    def _handle_log_warning(self, warning: bdk.Warning):
        logger.info(f"{self.wallet_id} - {warning}")

    def _handle_update(self, update: UpdateInfo):
        logger.info(f"{self.wallet_id} - {update}")

    def get_height(self) -> int:
        return self._height

    async def next_log(self) -> str | None:
        if not self.client:
            logger.error("Client not available; cannot fetch log entry.")
            return None
        try:
            message = await self.client.next_log()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to fetch log entry: %s", exc)
            return None
        if message is not None:
            self._handle_log_str(message)
        return message

    async def next_info(self) -> bdk.Info | None:
        if not self.client:
            logger.error("Client not available; cannot fetch info message.")
            return None
        try:
            info = await self.client.next_info()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to fetch info message: %s", exc)
            return None
        if info is not None:
            self._handle_log_info(info)
        return info

    async def next_warning(self) -> bdk.Warning | None:
        if not self.client:
            logger.error("Client not available; cannot fetch warning message.")
            return None
        try:
            warning = await self.client.next_warning()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to fetch warning message: %s", exc)
            return None
        if warning is not None:
            self._handle_log_warning(warning)
        return warning

    async def next_update_info(self) -> UpdateInfo | None:
        if not self.client:
            logger.error("Client not available; cannot fetch update.")
            return None
        try:
            update = await self.client.update()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to fetch update: %s", exc)
            return None
        update_info = UpdateInfo(update=update, update_type=UpdateInfo.UpdateType.full_sync)
        self._handle_update(update_info)
        return update_info

    def register_task(self, task: Future[Any]) -> None:
        self.tasks.append(task)

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
        self.node.run()
        logger.info(f"Started node")

    def shutdown_node(self):
        if self.client:
            self.client.shutdown()

        for task in self.tasks:
            if task and not task.done():
                task.cancel()
        self.tasks.clear()

    def node_running(self) -> bool:
        if not self.client:
            return False
        if not self.tasks:
            return False
        return not all([t.done() for t in self.tasks])

    def close(self):
        self.shutdown_node()
        self.loop_in_thread.stop()
