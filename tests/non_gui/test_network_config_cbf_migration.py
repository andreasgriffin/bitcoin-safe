#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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

import bdkpython as bdk

from bitcoin_safe.network_config import NetworkConfigs, P2pListenerType
from bitcoin_safe.pythonbdk_types import BlockchainType


def test_enable_compact_block_filters_where_supported() -> None:
    network_configs = NetworkConfigs()

    network_configs.configs[bdk.Network.BITCOIN.name].server_type = BlockchainType.Electrum
    network_configs.configs[bdk.Network.BITCOIN.name].p2p_listener_type = P2pListenerType.deactive

    network_configs.configs[bdk.Network.REGTEST.name].server_type = BlockchainType.Esplora
    network_configs.configs[bdk.Network.REGTEST.name].p2p_listener_type = P2pListenerType.deactive

    network_configs.configs[bdk.Network.SIGNET.name].server_type = BlockchainType.Electrum
    network_configs.configs[bdk.Network.SIGNET.name].p2p_listener_type = P2pListenerType.automatic

    network_configs.configs[bdk.Network.TESTNET.name].server_type = BlockchainType.Electrum
    network_configs.configs[bdk.Network.TESTNET.name].p2p_listener_type = P2pListenerType.deactive

    network_configs.configs[bdk.Network.TESTNET4.name].server_type = BlockchainType.Esplora
    network_configs.configs[bdk.Network.TESTNET4.name].p2p_listener_type = P2pListenerType.deactive

    network_configs.enable_compact_block_filters_where_supported()

    assert network_configs.configs[bdk.Network.BITCOIN.name].server_type == BlockchainType.CompactBlockFilter
    assert network_configs.configs[bdk.Network.BITCOIN.name].p2p_listener_type == P2pListenerType.automatic

    assert network_configs.configs[bdk.Network.REGTEST.name].server_type == BlockchainType.CompactBlockFilter
    assert network_configs.configs[bdk.Network.REGTEST.name].p2p_listener_type == P2pListenerType.automatic

    assert network_configs.configs[bdk.Network.SIGNET.name].server_type == BlockchainType.CompactBlockFilter
    assert network_configs.configs[bdk.Network.SIGNET.name].p2p_listener_type == P2pListenerType.automatic

    assert network_configs.configs[bdk.Network.TESTNET.name].server_type == BlockchainType.Electrum
    assert network_configs.configs[bdk.Network.TESTNET.name].p2p_listener_type == P2pListenerType.deactive

    assert network_configs.configs[bdk.Network.TESTNET4.name].server_type == BlockchainType.Esplora
    assert network_configs.configs[bdk.Network.TESTNET4.name].p2p_listener_type == P2pListenerType.deactive
