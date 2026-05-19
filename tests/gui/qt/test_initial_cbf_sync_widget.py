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

import inspect
import ipaddress
import json
from datetime import timedelta
from typing import Any

from PyQt6.QtCore import QRectF
from pytestqt.qtbot import QtBot

from bitcoin_safe.client import ProgressInfo, SyncStatus
from bitcoin_safe.geoip_rough import RoughGeoIpDatabase
from bitcoin_safe.gui.qt.initial_cbf_sync_widget import NetworkMapWidget, NetworkMapWidgetMode
from bitcoin_safe.network_config import Peer
from bitcoin_safe.pythonbdk_types import BlockchainType

from .helpers import Shutter


def write_geoip_fixture(db_path) -> None:
    """Write a tiny rough-GeoIP fixture DB used by this rendering test."""
    ipv4_prefix = 12
    ipv6_prefix = 32

    key_google = int(ipaddress.ip_address("8.8.8.8")) >> (32 - ipv4_prefix)
    key_cloudflare = int(ipaddress.ip_address("1.1.1.1")) >> (32 - ipv4_prefix)
    key_ipv6 = int(ipaddress.ip_address("2606:4700:4700::1111")) >> (128 - ipv6_prefix)

    payload = {
        "version": 1,
        "prefix_lengths": {"ipv4": ipv4_prefix, "ipv6": ipv6_prefix},
        "ipv4": {
            str(key_google): [37.422, -122.084, "US"],
            str(key_cloudflare): [48.857, 2.352, "FR"],
        },
        "ipv6": {
            str(key_ipv6): [35.689, 139.692, "JP"],
        },
    }
    db_path.write_text(json.dumps(payload), encoding="utf-8")


def test_initial_cbf_sync_widget_visual_smoke(
    qtbot: QtBot,
    tmp_path,
    mytest_start_time,
    test_config,
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    db_file = tmp_path / "geoip_rough_v1.json"
    write_geoip_fixture(db_file)

    widget = NetworkMapWidget(config=test_config, mode=NetworkMapWidgetMode.cbf_initial_sync)
    widget.geoip = RoughGeoIpDatabase(db_path=db_file)
    qtbot.addWidget(widget)
    widget.resize(1100, 660)

    widget.set_progress_info(
        ProgressInfo(
            progress=0.41,
            passed_time=timedelta(seconds=33),
            remaining_time=timedelta(minutes=2, seconds=11),
            status_msg="",
            sync_status=SyncStatus.syncing,
        )
    )

    widget.set_p2p_listener_peers(
        [
            Peer(host="8.8.8.8", port=8333),
            Peer(host="1.1.1.1", port=8333),
        ]
    )
    widget.set_cbf_peer_hosts(["2606:4700:4700::1111"])
    widget.set_cbf_peer_count(2)

    widget.show()
    qtbot.waitExposed(widget)
    qtbot.wait(250)

    assert "P2P listener peers" in widget.peer_legend_label.textLabel.text()
    if test_config.network_config.server_type == BlockchainType.CompactBlockFilter:
        assert "CBF peers: 2" in widget.cbf_legend_label.textLabel.text()
        assert widget.title_label.text() == "Scanning Bitcoin blockchain"
        assert widget.server_info_label.isHidden()
        assert widget.progress_bar.value() == 41
    else:
        assert widget.cbf_legend_label.isHidden()
        assert widget.title_label.text() == "Network Map"
        assert widget.local_progress_card.isHidden()
        assert widget.server_info_label.isHidden()

    # Hover marker for 8.8.8.8 and verify tooltip information.
    map_widget = widget.map_widget
    frame_rect = QRectF(map_widget.rect().adjusted(1, 1, -1, -1))
    map_rect = map_widget._fit_map_rect(frame_rect)
    marker_position = map_widget._to_widget(longitude=-122.084, latitude=37.422, rect=map_rect)
    point_index = map_widget._point_index_at_position(marker_position, map_rect)
    assert point_index is not None
    tooltip = map_widget._tooltip_for_point(map_widget._points[point_index])
    assert "8.8.8.8" in tooltip
    assert "United" in tooltip

    screenshot_path = shutter.save_screenshot(widget, qtbot, shutter.name)
    assert screenshot_path.exists()


def test_initial_cbf_sync_widget_copies_mutable_inputs(qtbot: QtBot, test_config) -> None:
    widget = NetworkMapWidget(config=test_config, mode=NetworkMapWidgetMode.cbf_initial_sync)
    qtbot.addWidget(widget)

    p2p_connections = [Peer(host="8.8.8.8", port=8333)]
    nodes = {Peer(host="1.1.1.1", port=8333)}
    cbf_peer_hosts = ["2606:4700:4700::1111"]

    widget.set_p2p_listener_peers(p2p_connections)
    widget.set_nodes(nodes)
    widget.set_cbf_peer_hosts(cbf_peer_hosts)
    widget.set_cbf_peer_count(1)

    p2p_connections.clear()
    nodes.clear()
    cbf_peer_hosts.clear()

    assert "P2P listener peers: 1" in widget.peer_legend_label.textLabel.text()
    if test_config.network_config.server_type == BlockchainType.CompactBlockFilter:
        assert "CBF peers: 1" in widget.cbf_legend_label.textLabel.text()
        assert not widget.cbf_legend_label.isHidden()
    else:
        assert widget.cbf_legend_label.isHidden()
        assert widget.cbf_legend_label.textLabel.text() == ""
    assert "Bitcoin nodes: 1" in widget.node_legend_label.textLabel.text()


def test_network_map_widget_visibility_depends_on_network_mode(
    qtbot: QtBot, tmp_path, monkeypatch, test_config
) -> None:
    db_file = tmp_path / "geoip_rough_v1.json"
    write_geoip_fixture(db_file)
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.initial_cbf_sync_widget.socket.getaddrinfo",
        lambda host, *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 0))],
    )

    cases: list[dict[str, Any]] = [
        {
            "server_type": BlockchainType.CompactBlockFilter,
            "mode": NetworkMapWidgetMode.cbf_initial_sync,
            "expected": {
                "privacy_help_hidden": False,
                "server_info_hidden": True,
                "local_progress_hidden": False,
                "wallet_progress_hidden": True,
                "cbf_legend_hidden": False,
                "server_legend_hidden": True,
            },
        },
        {
            "server_type": BlockchainType.CompactBlockFilter,
            "mode": NetworkMapWidgetMode.tools_tab,
            "expected": {
                "privacy_help_hidden": True,
                "server_info_hidden": True,
                "local_progress_hidden": True,
                "wallet_progress_hidden": True,
                "cbf_legend_hidden": False,
                "server_legend_hidden": True,
            },
        },
        {
            "server_type": BlockchainType.Electrum,
            "mode": NetworkMapWidgetMode.tools_tab,
            "server_name": "electrum.example:50002",
            "expected": {
                "privacy_help_hidden": True,
                "server_info_hidden": False,
                "local_progress_hidden": True,
                "wallet_progress_hidden": True,
                "cbf_legend_hidden": True,
                "server_legend_hidden": False,
            },
        },
        {
            "server_type": BlockchainType.Esplora,
            "mode": NetworkMapWidgetMode.tools_tab,
            "server_name": "https://esplora.example/api",
            "expected": {
                "privacy_help_hidden": True,
                "server_info_hidden": False,
                "local_progress_hidden": True,
                "wallet_progress_hidden": True,
                "cbf_legend_hidden": True,
                "server_legend_hidden": False,
            },
        },
    ]

    for case in cases:
        test_config.network_config.server_type = case["server_type"]
        test_config.network_config.electrum_url = ""
        test_config.network_config.esplora_url = ""
        if case["server_type"] == BlockchainType.Electrum:
            test_config.network_config.electrum_url = case["server_name"]
        if case["server_type"] == BlockchainType.Esplora:
            test_config.network_config.esplora_url = case["server_name"]

        widget = NetworkMapWidget(config=test_config, mode=case["mode"])
        widget.geoip = RoughGeoIpDatabase(db_path=db_file)
        qtbot.addWidget(widget)
        widget.set_network_config()
        widget.show()
        qtbot.waitExposed(widget)

        expected = case["expected"]
        assert widget.privacy_help_label.isHidden() == expected["privacy_help_hidden"]
        assert widget.server_info_label.isHidden() == expected["server_info_hidden"]
        assert widget.local_progress_card.isHidden() == expected["local_progress_hidden"]
        assert widget.wallet_progress_section.isHidden() == expected["wallet_progress_hidden"]
        assert widget.cbf_legend_label.isHidden() == expected["cbf_legend_hidden"]
        assert widget.server_legend_label.isHidden() == expected["server_legend_hidden"]


def test_network_map_widget_renders_multiple_wallet_progress_rows(qtbot: QtBot, test_config) -> None:
    widget = NetworkMapWidget(config=test_config, mode=NetworkMapWidgetMode.tools_tab)
    qtbot.addWidget(widget)

    widget.set_wallet_progress(
        wallet_id="wallet-a",
        wallet_title="Wallet A",
        progress_info=ProgressInfo(
            progress=0.25,
            passed_time=timedelta(seconds=30),
            remaining_time=timedelta(minutes=3),
            status_msg="",
            sync_status=SyncStatus.syncing,
        ),
    )
    widget.set_wallet_progress(
        wallet_id="wallet-b",
        wallet_title="Wallet B",
        progress_info=ProgressInfo(
            progress=0.75,
            passed_time=timedelta(minutes=1),
            remaining_time=timedelta(seconds=15),
            status_msg="Downloading blocks",
            sync_status=SyncStatus.syncing,
        ),
    )

    assert not widget.wallet_progress_section.isHidden()
    assert len(widget._wallet_progress_cards) == 2
    assert widget._wallet_progress_cards["wallet-a"].wallet_title_label.text() == "Wallet A"
    assert widget._wallet_progress_cards["wallet-b"].progress_label.text() == "Downloading blocks"


def test_network_map_widget_maps_electrum_server_hostnames(
    qtbot: QtBot, tmp_path, monkeypatch, test_config
) -> None:
    db_file = tmp_path / "geoip_rough_v1.json"
    write_geoip_fixture(db_file)
    test_config.network_config.server_type = BlockchainType.Electrum
    test_config.network_config.electrum_url = "electrum.example:50002"

    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.initial_cbf_sync_widget.socket.getaddrinfo",
        lambda host, *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 0))],
    )

    widget = NetworkMapWidget(config=test_config, mode=NetworkMapWidgetMode.tools_tab)
    widget.geoip = RoughGeoIpDatabase(db_path=db_file)
    qtbot.addWidget(widget)
    widget.set_network_config()

    assert not widget.server_legend_label.isHidden()
    assert "Electrum server: 1" in widget.server_legend_label.textLabel.text()
    assert any(point.host == "electrum.example:50002" for point in widget.map_widget._points)


def test_network_map_widget_skips_local_dns_resolution_for_remote_dns_proxy(
    qtbot: QtBot, monkeypatch, test_config
) -> None:
    test_config.network_config.server_type = BlockchainType.Electrum
    test_config.network_config.electrum_url = "electrum.example:50002"
    test_config.network_config.proxy_url = "socks5h://127.0.0.1:9050"

    calls: list[str] = []

    def fake_getaddrinfo(host, *args, **kwargs):
        calls.append(host)
        return []

    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.initial_cbf_sync_widget.socket.getaddrinfo",
        fake_getaddrinfo,
    )

    widget = NetworkMapWidget(config=test_config, mode=NetworkMapWidgetMode.tools_tab)
    qtbot.addWidget(widget)
    widget.set_network_config()

    assert calls == []
    assert not any(point.source.name == "server" for point in widget.map_widget._points)
