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

import logging
from functools import partial
from typing import Any, cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugin_server import PluginPermission, PluginServer
from bitcoin_safe.plugin_framework.plugins.chat_sync.client import SyncClient
from bitcoin_safe.plugin_framework.plugins.walletgraph.client import WalletGraphClient
from bitcoin_safe.signals import T, WalletFunctions
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.util import fast_version

logger = logging.getLogger(__name__)


class PluginManager(BaseSaveableClass):
    known_classes = {
        **BaseSaveableClass.known_classes,
        SyncClient.__name__: SyncClient,
        PluginClient.__name__: PluginClient,
        WalletGraphClient.__name__: WalletGraphClient,
        PluginPermission.__name__: PluginPermission,
    }
    VERSION = "0.0.4"

    signal_client_action = cast(SignalProtocol[[PluginClient]], pyqtSignal(PluginClient))
    client_classes: list[type[PluginClient]] = [SyncClient, WalletGraphClient]
    auto_allow_permissions: list[type[PluginClient]] = [SyncClient, WalletGraphClient]

    @staticmethod
    def cls_kwargs(
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
    ):
        return {
            "wallet_functions": wallet_functions,
            "config": config,
            "fx": fx,
            "loop_in_thread": loop_in_thread,
        }

    @classmethod
    def class_kwargs(
        cls,
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
    ):
        return {
            cls.__name__: cls.cls_kwargs(
                wallet_functions=wallet_functions, config=config, fx=fx, loop_in_thread=loop_in_thread
            ),
            SyncClient.__name__: SyncClient.cls_kwargs(
                signals=wallet_functions.signals,
                network=config.network,
                loop_in_thread=loop_in_thread,
            ),
            WalletGraphClient.__name__: WalletGraphClient.cls_kwargs(
                signals=wallet_functions.signals,
                network=config.network,
            ),
        }

    def __init__(
        self,
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        clients: list[PluginClient] | None = None,
        plugin_permissions: dict[str, set[PluginPermission]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.network = config.network
        self.parent = parent
        self.wallet_functions = wallet_functions
        self.config = config
        self.loop_in_thread = loop_in_thread
        self.fx = fx
        self.clients = [client for client in clients if isinstance(client, PluginClient)] if clients else []
        self.plugin_server: PluginServer | None = None
        self.plugin_permissions: dict[str, set[PluginPermission]] = (
            plugin_permissions if plugin_permissions else {}
        )
        self.signal_tracker = SignalTracker()
        for client in self.clients:
            self._register_client(client=client)

    def get_instance(self, cls: type[T], clients: list[PluginClient] | None = None) -> T | None:
        """Get instance."""
        clients = clients if clients else self.clients
        for client in clients:
            if isinstance(client, cls):
                return client
        return None

    def _register_client(
        self,
        client: PluginClient,
    ):
        """Register client and observe permission changes."""
        self.signal_tracker.connect(
            client.signal_request_enabled, partial(self._on_client_enabled_changed, client)
        )

        if client not in self.clients:
            self.clients.append(client)

    def _create_missing_clients(
        self,
        descriptor: bdk.Descriptor,
    ):
        existing_clients = self.clients.copy()
        # ensure correct ordering, by clearing list first
        self.clients.clear()
        for cls in self.client_classes:
            if client := self.get_instance(cls, clients=existing_clients):
                self.clients.append(client)
            elif cls.plugin_conditions.descriptor_allowed(str(descriptor)):
                if cls == SyncClient:
                    self._register_client(
                        SyncClient.from_descriptor(
                            signals=self.wallet_functions.signals,
                            network=self.network,
                            multipath_descriptor=descriptor,
                            loop_in_thread=self.loop_in_thread,
                        )
                    )
                elif cls == WalletGraphClient:
                    self._register_client(
                        WalletGraphClient(
                            network=self.network,
                            signals=self.wallet_functions.signals,
                        )
                    )

    def create_and_connect_clients(
        self, descriptor: bdk.Descriptor, wallet_id: str, category_core: CategoryCore
    ):
        """Create and connect clients."""
        self.plugin_server = PluginServer(
            wallet_id=wallet_id,
            network=self.network,
            wallet_functions=self.wallet_functions,
            plugin_permissions=self.plugin_permissions,
        )
        self._create_missing_clients(
            descriptor=descriptor,
        )

        for client in self.clients:
            plugin_id = self._plugin_id(client)
            if plugin_id not in self.plugin_permissions:
                self.plugin_permissions[plugin_id] = set()

            scoped_server = self.plugin_server.view_for(plugin_id)
            if not scoped_server.request_access(client.required_permissions):
                client.set_enabled(False)
            client.set_server_view(server=scoped_server)

    @staticmethod
    def _plugin_id(client: PluginClient) -> str:
        """Return a stable identifier for storing plugin permissions."""

        return client.__class__.__name__

    def _on_client_enabled_changed(self, client: PluginClient, enabled: bool) -> None:
        """Update stored permissions when a plugin is disabled or re-enabled."""

        plugin_id = self._plugin_id(client)
        if enabled:
            granted_permissions = self._request_permission(plugin_id, client)
            permissions_match = bool(granted_permissions)

            client.set_enabled(enabled and permissions_match)
        else:
            # set_enabled has to be done first, since it needs plugin_permissions to unload
            client.set_enabled(False)
            self.plugin_permissions[plugin_id] = set()

    def _request_permission(self, plugin_id: str, client: PluginClient) -> bool:
        """Ensure permissions are cached, prompting the user on first request."""

        not_yet_granted_permissions = set(client.required_permissions) - self.plugin_permissions.get(
            plugin_id, set()
        )
        if not not_yet_granted_permissions:
            # all granted
            return True

        permission_lines = "\n".join(
            f"- {permission.name}: {permission.description}"
            for permission in sorted(not_yet_granted_permissions, key=lambda p: p.name)
        )
        response = (client.__class__ in self.auto_allow_permissions) or question_dialog(
            text=(
                f"{client.title} requests access to:\n{permission_lines}\n\n"
                "Allow this plugin to access these features?"
            ),
            title="Plugin permission request",
            true_button="Allow",
            false_button="Deny",
        )

        if response:
            self.plugin_permissions[plugin_id].update(not_yet_granted_permissions)
            return True
        else:
            return False

    def load_all_enabled(self):
        """Load all enabled."""
        for client in self.clients:
            if client.enabled:
                client.load()

    def disconnect_all(self):
        """Disconnect all."""
        for client in self.clients:
            client.unload()

    def drop_wallet_specific_things(self) -> bool:
        for client in list(self.clients):
            if not client.drop_wallet_specific_things():
                self.clients.remove(client)
        return True

    def clone(self, class_kwargs: dict | None = None):
        class_kwargs = class_kwargs if class_kwargs else {}
        class_kwargs.update(
            self.class_kwargs(
                wallet_functions=self.wallet_functions,
                config=self.config,
                fx=self.fx,
                loop_in_thread=self.loop_in_thread,
            )
        )
        return super().clone(class_kwargs=class_kwargs)

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["clients"] = self.clients
        d["plugin_permissions"] = {
            plugin_id: list(permissions) for plugin_id, permissions in self.plugin_permissions.items()
        }
        return d

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)

        plugin_permissions: dict[str, set[PluginPermission]] = dct.get("plugin_permissions", {})
        for plugin_id in plugin_permissions.keys():
            # forward/backward compatibility
            # only allow correctly recognized PluginPermission
            plugin_permissions[plugin_id] = set(
                [entry for entry in plugin_permissions[plugin_id] if isinstance(entry, PluginPermission)]
            )

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            pass
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.1"):
            dct.setdefault("plugin_permissions", {})
            for client in dct.get("clients", []):
                if not isinstance(client, PluginClient):
                    continue

                plugin_id = client.__class__.__name__
                if plugin_id in dct["plugin_permissions"]:
                    continue

                required_permissions: set[PluginPermission] = set()
                if hasattr(client, "required_permissions"):
                    required_permissions = set(client.required_permissions)

                enabled = hasattr(client, "enabled") and bool(client.enabled)
                if enabled:
                    dct["plugin_permissions"][plugin_id] = set(required_permissions)
                else:
                    dct["plugin_permissions"].setdefault(plugin_id, set())

        if fast_version(str(dct["VERSION"])) < fast_version("0.0.4"):
            dct.setdefault("plugin_permissions", {})
            for client in dct.get("clients", []):
                if not isinstance(client, PluginClient):
                    continue

                plugin_id = client.__class__.__name__
                if not client.enabled:
                    continue

                dct["plugin_permissions"][plugin_id] = set(client.required_permissions)

        # now the version is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    def close(self):
        """Close."""
        self.signal_tracker.disconnect_all()
        for client in self.clients:
            client.close()

    def updateUi(self):
        """UpdateUi."""
        for client in self.clients:
            client.updateUi()
