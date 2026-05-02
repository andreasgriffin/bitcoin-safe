#
# Bitcoin Safe
# Copyright (C) 2025-2026 Andreas Griffin
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

import logging
from enum import Enum, auto
from typing import TYPE_CHECKING

import bdkpython as bdk

from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.i18n import translate
from bitcoin_safe.labels import Labels
from bitcoin_safe.signals import Signals, WalletFunctions, WalletSignals
from bitcoin_safe.wallet import Wallet

if TYPE_CHECKING:
    from bitcoin_safe.gui.qt.qt_wallet import QTWallet


logger = logging.getLogger(__name__)


class PluginPermission(Enum):
    """Capabilities a plugin client can request from the PluginServer."""

    LABELS = auto()
    SIGNALS = auto()
    WALLET_SIGNALS = auto()
    MN_TUPLE = auto()
    ADDRESS = auto()
    DESCRIPTOR = auto()
    WALLET = auto()
    QTWallet = auto()
    CATEGORY_CORE = auto()

    @property
    def description(self) -> str:
        """Human-readable description of what the permission grants."""
        d = {
            PluginPermission.LABELS: translate(
                "plugins", "Read and update your wallet's labels and categories."
            ),
            PluginPermission.SIGNALS: translate(
                "plugins",
                "Subscribe to wallet activity events such as new transactions or blockchain sync. Also enables opening of transactions and PSBTs.",
            ),
            PluginPermission.WALLET_SIGNALS: translate(
                "plugins",
                "Subscribe to wallet activity events such as new transactions or blockchain sync.",
            ),
            PluginPermission.MN_TUPLE: translate(
                "plugins", "View the wallet's multisig threshold (m-of-n) configuration."
            ),
            PluginPermission.ADDRESS: translate(
                "plugins", "Create new receiving addresses from your wallet."
            ),
            PluginPermission.DESCRIPTOR: translate(
                "plugins", "Read the wallet's descriptor (public key structure, paths)."
            ),
            PluginPermission.WALLET: translate(
                "plugins",
                "Full read and write access to this wallet, including balances, transactions, and UTXOs.",
            ),
            PluginPermission.CATEGORY_CORE: translate(
                "plugins",
                "Full read and write access to this wallet and categories.",
            ),
        }
        return d.get(self, translate("plugins", "Unknown description"))


class PluginServer:
    def __init__(
        self,
        wallet_id: str,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        plugin_permissions: dict[str, set[PluginPermission]],
    ) -> None:
        """Initialize instance."""

        self._enabled = False
        self.wallet_id = wallet_id
        self.network = network
        self._wallet_functions = wallet_functions
        self.plugin_permissions = plugin_permissions

    def is_enabled(self) -> bool:
        """Return whether the server is currently enabled."""

        return self._enabled

    def set_enabled(self, enabled: bool):
        """Enable or disable the server."""

        self._enabled = enabled

    def start(self):
        """Start the local server."""

        logger.debug("PluginServer.start() called")

    def stop(self):
        """Stop the local server."""

        logger.debug("PluginServer.stop() called")

    def request_access(self, plugin_id: str, requested_permissions: set[PluginPermission]) -> bool:
        """Return True if all requested permissions are allowed for this plugin."""

        allowed = self.plugin_permissions.get(plugin_id, set())
        missing = requested_permissions.difference(allowed)
        if missing:
            logger.warning("Denying plugin %s access to %s", plugin_id, ", ".join(p.name for p in missing))
            return False
        return True

    def view_for(self, plugin_id: str) -> PluginServerView:
        """Return a plugin-scoped view enforcing per-plugin permissions."""
        return PluginServerView(server=self, plugin_id=plugin_id)

    def _get_wallet(self) -> Wallet | None:
        wallets: dict[str, Wallet] = self._wallet_functions.get_wallets()
        return wallets.get(self.wallet_id)

    def _has_permission(self, permission: PluginPermission, plugin_id: str) -> bool:
        allowed = self.plugin_permissions.get(plugin_id, set())
        if permission not in allowed:
            logger.debug(f"Permission {permission.name} denied for {self.wallet_id=} {plugin_id=}")
            return False
        return True

    def get_labels(self, plugin_id: str) -> Labels | None:
        """Return labels if the permission is granted."""
        permission = PluginPermission.LABELS
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        wallet = self._get_wallet()
        return wallet.labels if wallet else None

    def get_wallet_signals(self, plugin_id: str) -> WalletSignals | None:
        """Return wallet signals if the permission is granted."""
        permission = PluginPermission.WALLET_SIGNALS
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        return self._wallet_functions.wallet_signals.get(self.wallet_id)

    def get_signals(self, plugin_id: str) -> Signals | None:
        """Return wallet signals if the permission is granted."""
        permission = PluginPermission.SIGNALS
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        return self._wallet_functions.signals

    def get_mn_tuple(self, plugin_id: str) -> tuple[int, int] | None:
        """Return the wallet's (m, n) tuple if the permission is granted."""
        permission = PluginPermission.MN_TUPLE
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        wallet = self._get_wallet()
        return wallet.get_mn_tuple() if wallet else None

    def get_address(self, plugin_id: str) -> bdk.AddressInfo | None:
        """Return a new address if the permission is granted."""
        permission = PluginPermission.ADDRESS
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        wallet = self._get_wallet()
        return wallet.get_address() if wallet else None

    def get_descriptor(self, plugin_id: str) -> bdk.Descriptor | None:
        """Return the multipath descriptor if the permission is granted."""
        permission = PluginPermission.DESCRIPTOR
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        wallet = self._get_wallet()
        return wallet.multipath_descriptor if wallet else None

    def get_wallet(self, plugin_id: str) -> Wallet | None:
        """Return the wallet if the permission is granted."""
        permission = PluginPermission.WALLET
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        return self._get_wallet()

    def get_qt_wallet(self, plugin_id: str) -> QTWallet | None:
        permission = PluginPermission.QTWallet
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        wallets: dict[str, QTWallet] = self._wallet_functions.get_qt_wallets()
        return wallets.get(self.wallet_id)

    def get_category_core(self, plugin_id: str) -> CategoryCore | None:
        permission = PluginPermission.CATEGORY_CORE
        if not self._has_permission(permission, plugin_id=plugin_id):
            logger.error(f"{plugin_id} was denied {permission}")
            return None

        qt_wallet = self.get_qt_wallet(plugin_id)
        if not qt_wallet:
            return None

        return qt_wallet.category_core


class PluginServerView:
    def __init__(self, server: PluginServer, plugin_id: str) -> None:
        """Initialize plugin-scoped server wrapper."""

        self._server = server
        self.plugin_id = plugin_id

    def request_access(self, requested_permissions: set[PluginPermission]) -> bool:
        """Proxy access requests to the underlying server for this plugin."""

        return self._server.request_access(self.plugin_id, requested_permissions)

    def get_labels(self) -> Labels | None:
        return self._server.get_labels(plugin_id=self.plugin_id)

    def get_wallet_signals(self) -> WalletSignals | None:
        return self._server.get_wallet_signals(plugin_id=self.plugin_id)

    @property
    def wallet_signals(self) -> WalletSignals | None:
        return self._server.get_wallet_signals(plugin_id=self.plugin_id)

    @property
    def signals(self) -> Signals | None:
        return self._server.get_signals(plugin_id=self.plugin_id)

    def get_mn_tuple(self) -> tuple[int, int] | None:
        return self._server.get_mn_tuple(plugin_id=self.plugin_id)

    def get_address(self) -> bdk.AddressInfo | None:
        return self._server.get_address(plugin_id=self.plugin_id)

    def get_descriptor(self) -> bdk.Descriptor | None:
        return self._server.get_descriptor(plugin_id=self.plugin_id)

    def get_wallet(self) -> Wallet | None:
        return self._server.get_wallet(plugin_id=self.plugin_id)

    def get_category_core(self) -> CategoryCore | None:
        if not (category_core := self._server.get_category_core(plugin_id=self.plugin_id)):
            return None
        return category_core

    def get_qt_wallet(self) -> QTWallet | None:
        if not (qt_wallet := self._server.get_qt_wallet(plugin_id=self.plugin_id)):
            return None
        return qt_wallet

    @property
    def wallet_id(self) -> str:
        return self._server.wallet_id
