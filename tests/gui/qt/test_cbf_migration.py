#
# Bitcoin Safe
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
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.network_config import P2pListenerType
from bitcoin_safe.pythonbdk_types import BlockchainType

from ...helpers import TestConfig
from .helpers import main_window_context


def test_main_window_enable_cbf_and_shutdown_updates_all_supported_networks(
    qtbot: QtBot, monkeypatch, test_config: TestConfig
) -> None:
    test_config.network = bdk.Network.TESTNET
    test_config.network_configs.configs[bdk.Network.BITCOIN.name].server_type = BlockchainType.Electrum
    test_config.network_configs.configs[bdk.Network.BITCOIN.name].p2p_listener_type = P2pListenerType.deactive
    test_config.network_configs.configs[bdk.Network.REGTEST.name].server_type = BlockchainType.Esplora
    test_config.network_configs.configs[bdk.Network.REGTEST.name].p2p_listener_type = P2pListenerType.deactive
    test_config.network_configs.configs[bdk.Network.SIGNET.name].server_type = BlockchainType.Electrum
    test_config.network_configs.configs[bdk.Network.TESTNET.name].server_type = BlockchainType.Electrum
    test_config.network_configs.configs[bdk.Network.TESTNET4.name].server_type = BlockchainType.Esplora

    restart_calls: list[bdk.Network | None] = []

    def fake_restart(new_startup_network: bdk.Network | None = None, restart_command=None) -> None:
        del restart_command
        restart_calls.append(new_startup_network)

    with main_window_context(test_config=test_config) as main_window:
        qtbot.addWidget(main_window)
        monkeypatch.setattr(main_window, "restart", fake_restart)

        main_window.enable_cbf_and_shutdown()
        QApplication.processEvents()

        assert restart_calls == [bdk.Network.TESTNET]

        assert (
            main_window.config.network_configs.configs[bdk.Network.BITCOIN.name].server_type
            == BlockchainType.CompactBlockFilter
        )
        assert (
            main_window.config.network_configs.configs[bdk.Network.BITCOIN.name].p2p_listener_type
            == P2pListenerType.automatic
        )
        assert (
            main_window.config.network_configs.configs[bdk.Network.REGTEST.name].server_type
            == BlockchainType.CompactBlockFilter
        )
        assert (
            main_window.config.network_configs.configs[bdk.Network.REGTEST.name].p2p_listener_type
            == P2pListenerType.automatic
        )
        assert (
            main_window.config.network_configs.configs[bdk.Network.SIGNET.name].server_type
            == BlockchainType.CompactBlockFilter
        )
        assert (
            main_window.config.network_configs.configs[bdk.Network.TESTNET.name].server_type
            == BlockchainType.Electrum
        )
        assert (
            main_window.config.network_configs.configs[bdk.Network.TESTNET4.name].server_type
            == BlockchainType.Esplora
        )
