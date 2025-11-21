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
from pathlib import Path
from typing import cast

import bdkpython as bdk
from bitcoin_usb.address_types import DescriptorInfo

from bitcoin_safe.client_helpers import UpdateInfo
from bitcoin_safe.descriptors import get_recovery_point
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
        wallet: bdk.Wallet,
        peers: list[bdk.Peer],
        data_dir: Path,
        proxy_info: ProxyInfo | None,
        cbf_connections: int,
        is_new_wallet=False,
        gap: int = 20,
    ):
        """Initialize instance."""
        self.client: bdk.CbfClient | None = None
        self._height: int = 0
        self.wallet_id = wallet_id
        self.gap = gap
        self.wallet = wallet
        self.peers = peers
        self.data_dir = data_dir
        self.proxy_info = proxy_info
        self.cbf_connections = cbf_connections
        self.is_new_wallet = is_new_wallet

    def _handle_log_info(self, info: bdk.Info):
        """Handle log info."""
        if isinstance(info, bdk.Info.PROGRESS):
            self._height = info.chain_height

        logger.info(f"{self.wallet_id} - {info}")

    def _handle_log_str(self, log: str):
        # there are a lot of logs and it can block the UI to log them all
        """Handle log str."""
        if "Chain updated" in log:
            # this is so fast, that it can freeze the UI
            return
        logger.info(f"{self.wallet_id} - {log}")

    def _handle_log_warning(self, warning: bdk.Warning):
        """Handle log warning."""
        logger.info(f"{self.wallet_id} - {warning}")

    def _handle_update(self, update: UpdateInfo):
        """Handle update."""
        logger.info(f"{self.wallet_id} - {update}")

    def get_height(self) -> int:
        """Get height."""
        return self._height

    async def attempt_restart_node(self):
        """Attempt restart node."""
        if not self.node_running():
            logger.info("CBF node was shutdown. Rebuilding")
            await asyncio.sleep(1)
            try:
                if self.client:
                    self.client.shutdown()
            except bdk.CbfError.NodeStopped:
                pass
            except Exception:
                pass
            self.build_node()

    async def next_info(self) -> bdk.Info | None:
        """Next info."""
        if not self.client:
            logger.error("Client not available; cannot fetch info message.")
            return None
        if not self.client.is_running():
            logger.error("Client not running")
            await self.attempt_restart_node()
            return None

        try:
            info = await self.client.next_info()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Failed to fetch info message: {exc}")
            return None
        if info is not None:
            self._handle_log_info(info)
        return info

    async def next_warning(self) -> bdk.Warning | None:
        """Next warning."""
        if not self.client:
            logger.error("Client not available; cannot fetch warning message.")
            return None
        if not self.client.is_running():
            logger.error("Client not running")
            await self.attempt_restart_node()
            return None

        try:
            warning = await self.client.next_warning()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Failed to fetch warning message: {exc}")
            return None
        if warning is not None:
            self._handle_log_warning(warning)
        return warning

    async def next_update_info(self) -> UpdateInfo | None:
        """Next update info."""
        if not self.client:
            logger.error("Client not available; cannot fetch update.")
            return None
        if not self.client.is_running():
            logger.error("Client not running")
            await self.attempt_restart_node()
            return None

        try:
            update = await self.client.update()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Failed to fetch update: {exc}")
            return None
        update_info = UpdateInfo(update=update, update_type=UpdateInfo.UpdateType.full_sync)
        self._handle_update(update_info)
        return update_info

    def build_node(
        self,
    ):
        """Build node."""
        derivation_index = max(
            self.gap,
            self.wallet.derivation_index(keychain=bdk.KeychainKind.EXTERNAL) or 0,
            self.wallet.derivation_index(keychain=bdk.KeychainKind.INTERNAL) or 0,
        )
        if self.is_new_wallet and self.wallet.latest_checkpoint().height == 0:
            scan_type = cast(
                bdk.ScanType,
                bdk.ScanType.RECOVERY(
                    used_script_index=derivation_index, checkpoint=bdk.RecoveryPoint.TAPROOT_ACTIVATION
                ),
            )
        else:
            if self.wallet.latest_checkpoint().height == 0:
                recovery_point = get_recovery_point(
                    DescriptorInfo.from_str(
                        str(self.wallet.public_descriptor(keychain=bdk.KeychainKind.EXTERNAL))
                    ).address_type,
                    network=self.wallet.network(),
                )
                scan_type = cast(
                    bdk.ScanType,
                    bdk.ScanType.RECOVERY(used_script_index=derivation_index, checkpoint=recovery_point),
                )
            else:
                scan_type = cast(bdk.ScanType, bdk.ScanType.SYNC())
        builder = bdk.CbfBuilder().scan_type(scan_type=scan_type).data_dir(data_dir=str(self.data_dir))
        if self.proxy_info:
            builder = builder.socks5_proxy(proxy=self.proxy_info.to_bdk())
        if self.peers:
            builder = builder.peers(self.peers)
        builder = builder.connections(self.cbf_connections)

        # timeout, new release
        # info messages, height, fork

        components = builder.build(self.wallet)
        self.client = components.client
        node = components.node
        node.run()
        logger.info("Started node")

    def shutdown_node(self):
        """Shutdown node."""
        if self.client:
            try:
                self.client.shutdown()
            except Exception as e:
                logger.error(f"shutdown_node {e}")

    def node_running(self) -> bool:
        """Node running."""
        if not self.client:
            return False
        return self.client.is_running()

    def close(self):
        """Close."""
        self.shutdown_node()
