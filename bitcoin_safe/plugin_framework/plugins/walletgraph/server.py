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

import bdkpython as bdk

from bitcoin_safe.plugin_framework.plugin_server import PluginServer
from bitcoin_safe.signals import WalletFunctions
from bitcoin_safe.wallet import Wallet, get_wallet

logger = logging.getLogger(__name__)


class WalletGraphServer(PluginServer):
    def __init__(self, wallet_id: str, network: bdk.Network, wallet_functions: WalletFunctions) -> None:
        """Initialize instance."""
        super().__init__()
        self.wallet_id = wallet_id
        self.network = network
        self._wallet_functions = wallet_functions
        self.wallet_signals = wallet_functions.wallet_signals[wallet_id]

    def get_wallet(self) -> Wallet | None:
        """Get wallet."""
        return get_wallet(self.wallet_id, self._wallet_functions)

    def start(self) -> None:
        # A local server that only exposes helper methods does not need to be started.
        """Start."""
        logger.debug("WalletGraphServer.start() called")

    def stop(self) -> None:
        # A local server that only exposes helper methods does not need to be stopped.
        """Stop."""
        logger.debug("WalletGraphServer.stop() called")
