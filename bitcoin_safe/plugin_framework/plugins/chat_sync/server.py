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
from typing import Dict, Optional, Tuple

import bdkpython as bdk

from bitcoin_safe.labels import Labels
from bitcoin_safe.plugin_framework.plugin_server import PluginServer
from bitcoin_safe.signals import WalletFunctions, WalletSignals
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


class SyncServer(PluginServer):
    def __init__(self, wallet_id: str, network: bdk.Network, wallet_functions: WalletFunctions) -> None:
        super().__init__()
        self.wallet_id = wallet_id
        self.network = network
        self._wallet_functions = wallet_functions
        self.signals_min = wallet_functions.signals

    def get_labels(self) -> Labels | None:
        wallets: Dict[str, Wallet] = self._wallet_functions.get_wallets()
        wallet = wallets.get(self.wallet_id)
        return wallet.labels if wallet else None

    def get_wallet_signals(self) -> WalletSignals | None:
        return self._wallet_functions.wallet_signals.get(self.wallet_id)

    def get_mn_tuple(self) -> Optional[Tuple[int, int]]:
        wallets: Dict[str, Wallet] = self._wallet_functions.get_wallets()
        wallet = wallets.get(self.wallet_id)
        return wallet.get_mn_tuple() if wallet else None

    def get_address(self) -> Optional[bdk.AddressInfo]:
        wallets: Dict[str, Wallet] = self._wallet_functions.get_wallets()
        wallet = wallets.get(self.wallet_id)
        return wallet.get_address() if wallet else None

    def get_descriptor(self) -> Optional[bdk.Descriptor]:
        wallets: Dict[str, Wallet] = self._wallet_functions.get_wallets()
        wallet = wallets.get(self.wallet_id)
        return wallet.multipath_descriptor if wallet else None

    def start(self):
        # a function hook dosnt need to be started
        pass

    def stop(self):
        # a function hook dosnt need to be stopped
        pass
