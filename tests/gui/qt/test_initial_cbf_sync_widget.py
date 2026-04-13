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

from PyQt6.QtCore import QRectF
from pytestqt.qtbot import QtBot

from bitcoin_safe.client import ProgressInfo, SyncStatus
from bitcoin_safe.geoip_rough import RoughGeoIpDatabase
from bitcoin_safe.gui.qt.initial_cbf_sync_widget import InitialCbfSyncWidget
from bitcoin_safe.network_config import Peer

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

    widget = InitialCbfSyncWidget(config=test_config)
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
    assert "CBF peers: 2" in widget.cbf_legend_label.textLabel.text()
    assert widget.progress_bar.value() == 41

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
    widget = InitialCbfSyncWidget(config=test_config)
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
    assert "CBF peers: 1" in widget.cbf_legend_label.textLabel.text()
    assert "Bitcoin nodes: 1" in widget.node_legend_label.textLabel.text()
