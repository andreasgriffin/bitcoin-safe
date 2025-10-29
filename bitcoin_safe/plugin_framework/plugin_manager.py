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

import logging
from typing import Any, Dict, List, Type, cast

import bdkpython as bdk
from packaging import version
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugins.chat_sync.client import SyncClient
from bitcoin_safe.plugin_framework.plugins.chat_sync.server import SyncServer
from bitcoin_safe.plugin_framework.plugins.walletgraph.client import WalletGraphClient
from bitcoin_safe.plugin_framework.plugins.walletgraph.server import WalletGraphServer
from bitcoin_safe.signals import Signals, T
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.typestubs import TypedPyQtSignal

logger = logging.getLogger(__name__)


class PluginManager(BaseSaveableClass):
    known_classes = {
        **BaseSaveableClass.known_classes,
        SyncClient.__name__: SyncClient,
        SyncServer.__name__: SyncServer,
        PluginClient.__name__: PluginClient,
        WalletGraphClient.__name__: WalletGraphClient,
        WalletGraphServer.__name__: WalletGraphServer,
    }
    VERSION = "0.0.1"

    signal_client_action = cast(TypedPyQtSignal[PluginClient], pyqtSignal(PluginClient))
    client_classes: List[Type[PluginClient]] = [SyncClient, WalletGraphClient]

    def __init__(
        self,
        network: bdk.Network,
        signals: Signals,
        config: UserConfig,
        fx: FX,
        clients: List[PluginClient] | None = None,
        parent: QWidget | None = None,
        **kwargs,
    ) -> None:
        super().__init__()
        self.network = network
        self.parent = parent
        self.signals = signals
        self.config = config
        self.fx = fx
        self.clients = [client for client in clients if isinstance(client, PluginClient)] if clients else []
        for client in self.clients:
            self._register_client(client=client)

    def get_instance(self, cls: Type[T], clients: List[PluginClient] | None = None) -> T | None:
        clients = clients if clients else self.clients
        for client in clients:
            if isinstance(client, cls):
                return client
        return None

    def _register_client(
        self,
        client: PluginClient,
    ):
        if client not in self.clients:
            self.clients.append(client)

    def _register_all_clients(
        self,
        descriptor: bdk.Descriptor,
    ):
        existing_clients = self.clients.copy()
        self.clients.clear()
        for cls in self.client_classes:
            if client := self.get_instance(cls, clients=existing_clients):
                self.clients.append(client)
            elif cls.plugin_conditions.descriptor_allowed(str(descriptor)):
                if cls == SyncClient:
                    self._register_client(
                        SyncClient.from_descriptor(
                            signals=self.signals,
                            network=self.network,
                            multipath_descriptor=descriptor,
                        )
                    )
                elif cls == WalletGraphClient:
                    self._register_client(
                        WalletGraphClient(
                            network=self.network,
                            signals=self.signals,
                        )
                    )

    def _create_and_connect_ChatSyncClient(
        self,
        client: SyncClient,
        wallet_id: str,
    ):
        server = SyncServer(
            wallet_id=wallet_id,
            signals=self.signals,
            network=self.network,
        )
        client.save_connection_details(server=server)

    def create_and_connect_clients(
        self, descriptor: bdk.Descriptor, wallet_id: str, category_core: CategoryCore
    ):
        self._register_all_clients(
            descriptor=descriptor,
        )

        for client in self.clients:
            if isinstance(client, SyncClient):
                self._create_and_connect_ChatSyncClient(
                    client=client,
                    wallet_id=wallet_id,
                )
            elif isinstance(client, WalletGraphClient):
                self._create_and_connect_wallet_graph_client(
                    client=client,
                    wallet_id=wallet_id,
                )

    def _create_and_connect_wallet_graph_client(self, client: WalletGraphClient, wallet_id: str) -> None:
        server = WalletGraphServer(
            wallet_id=wallet_id,
            network=self.network,
            signals=self.signals,
        )
        client.save_connection_details(server=server)

    def load_all_enabled(self):
        for client in self.clients:
            if client.enabled:
                client.load()

    def disconnect_all(self):
        for client in self.clients:
            client.unload()

    def dump(self) -> Dict[str, Any]:
        d = super().dump()
        d["clients"] = self.clients
        return d

    @classmethod
    def from_dump(cls, dct: Dict[str, Any], class_kwargs: Dict | None = None):
        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        # now the version is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    def close(self):
        for client in self.clients:
            client.close()

    def updateUi(self):
        for client in self.clients:
            client.updateUi()
