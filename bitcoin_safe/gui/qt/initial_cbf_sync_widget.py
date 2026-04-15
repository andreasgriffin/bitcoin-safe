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

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from bitcoin_safe_lib.gui.qt.util import age
from PyQt6.QtCore import QLocale, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from bitcoin_safe.client import ProgressInfo
from bitcoin_safe.config import UserConfig
from bitcoin_safe.geoip_rough import RoughGeoIpDatabase
from bitcoin_safe.network_config import Peer
from bitcoin_safe.util import resource_path

from .cbf_progress_bar import CBFProgressBar
from .icon_label import IconLabel

logger = logging.getLogger(__name__)


class PeerSource(Enum):
    p2p_listener = "p2p_listener"
    cbf = "cbf"
    node = "node"


@dataclass(frozen=True)
class PeerMapPoint:
    latitude: float
    longitude: float
    host: str
    source: PeerSource
    country_code: str | None = None


class WorldPeerMapWidget(QWidget):
    """Map card that renders land polygons and peer points."""

    _LAND_POLYGONS_CACHE: list[list[tuple[float, float]]] | None = None
    _LAND_FILE = Path(resource_path("data", "world_land_110m_simplified_v1.json"))
    _LONGITUDE_SPAN = 360.0
    _ANTARCTICA_MAX_LATITUDE = -60.0
    _MAP_MAX_LATITUDE = 85.0
    _MAP_MIN_LATITUDE = -58.0

    _OCEAN_TOP = QColor(18, 27, 46, 0)
    _OCEAN_BOTTOM = QColor(13, 19, 34, 0)
    _OCEAN_GLOW = QColor(82, 120, 182, 0)
    _LAND_FILL = QColor(150, 150, 150, 220)
    _LAND_OUTLINE = QColor(209, 220, 236, 0)
    _LAND_SHADOW = QColor(8, 14, 24, 0)
    _GRID_LINE = QColor(157, 182, 220, 0)
    _P2P_COLOR = QColor("#50C2FF")
    _CBF_COLOR = QColor("#F4A259")
    _NODE_COLOR = QColor("#458500")
    _TRANSPARENT = QColor(0, 0, 0, 0)
    _LAND_SHADOW_FILL = QColor(0, 0, 0, 50)
    _POINT_RING_COLOR = QColor(255, 255, 255, 220)

    _MAP_BORDER = QColor(92, 115, 155, 0)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._points: list[PeerMapPoint] = []
        self._hovered_point_index: int | None = None
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)

    @staticmethod
    def _is_visible(color: QColor) -> bool:
        return color.alpha() > 0

    @classmethod
    def _is_antarctica_polygon(cls, points: list[tuple[float, float]]) -> bool:
        return max(latitude for _, latitude in points) <= cls._ANTARCTICA_MAX_LATITUDE

    @classmethod
    def _latitude_span(cls) -> float:
        return max(1e-9, cls._MAP_MAX_LATITUDE - cls._MAP_MIN_LATITUDE)

    @classmethod
    def _map_aspect_ratio(cls) -> float:
        # Preserve equirectangular scale when map latitude bounds are clipped.
        return cls._LONGITUDE_SPAN / cls._latitude_span()

    @classmethod
    def _load_land_polygons(cls) -> list[list[tuple[float, float]]]:
        if cls._LAND_POLYGONS_CACHE is not None:
            return cls._LAND_POLYGONS_CACHE

        try:
            payload = json.loads(cls._LAND_FILE.read_text(encoding="utf-8"))
            polygons_payload = payload.get("polygons", [])
            polygons: list[list[tuple[float, float]]] = []
            for polygon in polygons_payload:
                if not isinstance(polygon, list) or len(polygon) < 4:
                    continue

                points: list[tuple[float, float]] = []
                for point in polygon:
                    if not isinstance(point, list) or len(point) < 2:
                        continue
                    try:
                        lon = float(point[0])
                        lat = float(point[1])
                    except Exception:
                        continue
                    points.append((lon, lat))

                if len(points) >= 4 and not cls._is_antarctica_polygon(points):
                    polygons.append(points)

            cls._LAND_POLYGONS_CACHE = polygons
        except Exception:
            logger.exception("Could not load world land polygons from %s", cls._LAND_FILE)
            cls._LAND_POLYGONS_CACHE = []

        return cls._LAND_POLYGONS_CACHE

    def set_points(self, points: list[PeerMapPoint]) -> None:
        self._points = points
        self.update()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, a0: int) -> int:
        return max(180, int(a0 / self._map_aspect_ratio()))

    def _to_widget(self, longitude: float, latitude: float, rect: QRectF) -> QPointF:
        x = rect.left() + ((longitude + 180.0) / self._LONGITUDE_SPAN) * rect.width()
        clamped_latitude = max(self._MAP_MIN_LATITUDE, min(self._MAP_MAX_LATITUDE, latitude))
        y = rect.top() + ((self._MAP_MAX_LATITUDE - clamped_latitude) / self._latitude_span()) * rect.height()
        return QPointF(x, y)

    def _land_path(self, map_rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        for polygon in self._load_land_polygons():
            if not polygon:
                continue

            start = self._to_widget(polygon[0][0], polygon[0][1], map_rect)
            path.moveTo(start)
            for longitude, latitude in polygon[1:]:
                path.lineTo(self._to_widget(longitude, latitude, map_rect))
            path.closeSubpath()
        return path

    def _draw_background(self, painter: QPainter, map_rect: QRectF) -> None:
        if not (
            self._is_visible(self._OCEAN_TOP)
            or self._is_visible(self._OCEAN_BOTTOM)
            or self._is_visible(self._OCEAN_GLOW)
        ):
            return

        ocean_gradient = QLinearGradient(map_rect.left(), map_rect.top(), map_rect.left(), map_rect.bottom())
        ocean_gradient.setColorAt(0.0, self._OCEAN_TOP)
        ocean_gradient.setColorAt(1.0, self._OCEAN_BOTTOM)
        painter.fillRect(map_rect, ocean_gradient)

        glow_gradient = QRadialGradient(
            QPointF(map_rect.center().x(), map_rect.top() + map_rect.height() * 0.28),
            map_rect.width() * 0.52,
        )
        glow_gradient.setColorAt(0.0, self._OCEAN_GLOW)
        glow_gradient.setColorAt(1.0, self._TRANSPARENT)
        painter.fillRect(map_rect, glow_gradient)

    def _draw_grid(self, painter: QPainter, map_rect: QRectF) -> None:
        if not self._is_visible(self._GRID_LINE):
            return
        grid_pen = QPen(self._GRID_LINE, 1)
        painter.setPen(grid_pen)
        for lat in (-60, -30, 0, 30, 60):
            y = self._to_widget(0, lat, map_rect).y()
            painter.drawLine(QPointF(map_rect.left(), y), QPointF(map_rect.right(), y))
        for lon in (-120, -60, 0, 60, 120):
            x = self._to_widget(lon, 0, map_rect).x()
            painter.drawLine(QPointF(x, map_rect.top()), QPointF(x, map_rect.bottom()))

    def _draw_land(self, painter: QPainter, map_rect: QRectF) -> None:
        if not (
            self._is_visible(self._LAND_FILL)
            or self._is_visible(self._LAND_OUTLINE)
            or self._is_visible(self._LAND_SHADOW)
        ):
            return

        land = self._land_path(map_rect)

        if self._is_visible(self._LAND_SHADOW):
            shadow_pen = QPen(self._LAND_SHADOW, 1.6)
            painter.setPen(shadow_pen)
            painter.setBrush(self._LAND_SHADOW_FILL)
            painter.save()
            painter.translate(0.0, 1.4)
            painter.drawPath(land)
            painter.restore()

        if self._is_visible(self._LAND_OUTLINE):
            painter.setPen(QPen(self._LAND_OUTLINE, 1.0))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._LAND_FILL)
        painter.drawPath(land)

    def _point_color(self, source: PeerSource) -> QColor:
        if source == PeerSource.p2p_listener:
            return self._P2P_COLOR
        if source == PeerSource.cbf:
            return self._CBF_COLOR
        return self._NODE_COLOR

    def _point_radius(self, point: PeerMapPoint) -> float:
        return 8.0

    def _hover_radius(self, point: PeerMapPoint) -> float:
        return self._point_radius(point) + 4.0

    def _point_center(self, point: PeerMapPoint, map_rect: QRectF) -> QPointF:
        return self._to_widget(point.longitude, point.latitude, map_rect)

    def _tooltip_for_point(self, point: PeerMapPoint) -> str:
        source_label = ""
        if point.source == PeerSource.p2p_listener:
            source_label = self.tr("P2P listener peer")
        if point.source == PeerSource.node:
            source_label = self.tr("Bitcoin node")
        if point.source == PeerSource.cbf:
            source_label = self.tr("CBF peer")

        country = self._country_name(point.country_code)
        return self.tr("{source}\nIP: {ip}\nCountry: {country}").format(
            source=source_label,
            ip=point.host,
            country=country,
        )

    def _country_name(self, country_code: str | None) -> str:
        if not country_code:
            return self.tr("Unknown")

        normalized = country_code.strip().upper()
        country = QLocale.codeToCountry(normalized)
        if country == QLocale.Country.AnyCountry:
            return normalized

        country_name = QLocale.territoryToString(country)
        return country_name if country_name else normalized

    def _point_index_at_position(self, position: QPointF, map_rect: QRectF) -> int | None:
        for index in range(len(self._points) - 1, -1, -1):
            point = self._points[index]
            center = self._point_center(point, map_rect)
            hover_radius = self._hover_radius(point)
            dx = position.x() - center.x()
            dy = position.y() - center.y()
            if dx * dx + dy * dy <= hover_radius * hover_radius:
                return index
        return None

    def _draw_points(self, painter: QPainter, map_rect: QRectF) -> None:
        for point in self._points:
            center = self._point_center(point, map_rect)
            color = self._point_color(point.source)

            if point.source == PeerSource.node:
                # Node points: smaller, no glow, no outer ring
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(center, 2.5, 2.5)
            else:
                # Other points: glow + outer ring
                glow = QColor(color)
                glow.setAlpha(88)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                radius = self._point_radius(point)
                painter.drawEllipse(center, radius, radius)

                painter.setPen(QPen(self._POINT_RING_COLOR, 1.2))
                painter.setBrush(color)
                painter.drawEllipse(center, 3.8, 3.8)

    def _fit_map_rect(self, frame_rect: QRectF) -> QRectF:
        aspect_ratio = self._map_aspect_ratio()
        available_ratio = frame_rect.width() / frame_rect.height()
        if available_ratio >= aspect_ratio:
            map_height = frame_rect.height()
            map_width = map_height * aspect_ratio
        else:
            map_width = frame_rect.width()
            map_height = map_width / aspect_ratio

        left = frame_rect.center().x() - map_width / 2.0
        top = frame_rect.center().y() - map_height / 2.0
        return QRectF(left, top, map_width, map_height)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        frame_rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
        map_rect = self._fit_map_rect(frame_rect)
        rounded = QPainterPath()
        rounded.addRoundedRect(map_rect, 14.0, 14.0)

        painter.save()
        painter.setClipPath(rounded)
        self._draw_background(painter, map_rect)
        self._draw_grid(painter, map_rect)
        self._draw_land(painter, map_rect)
        self._draw_points(painter, map_rect)
        painter.restore()

        if self._is_visible(self._MAP_BORDER):
            painter.setPen(QPen(self._MAP_BORDER, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(map_rect, 14.0, 14.0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            super().mouseMoveEvent(a0)
            return

        frame_rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
        map_rect = self._fit_map_rect(frame_rect)
        position = a0.position()
        if not map_rect.contains(position):
            self._hovered_point_index = None
            self.setToolTip("")
            QToolTip.hideText()
            super().mouseMoveEvent(a0)
            return

        point_index = self._point_index_at_position(position, map_rect)
        if point_index is None:
            self._hovered_point_index = None
            self.setToolTip("")
            QToolTip.hideText()
            super().mouseMoveEvent(a0)
            return

        if point_index != self._hovered_point_index:
            self._hovered_point_index = point_index
            tooltip_text = self._tooltip_for_point(self._points[point_index])
            self.setToolTip(tooltip_text)
            QToolTip.showText(a0.globalPosition().toPoint(), tooltip_text, self)

        super().mouseMoveEvent(a0)


class InitialCbfSyncWidget(QWidget):
    """Shown while CBF sync is running and history list is still empty."""

    _PRIVACY_INFO_URL = "https://bitcoin-safe.org/knowledge/compact-block-filters/"

    def __init__(self, config: UserConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.config = config

        self.geoip = RoughGeoIpDatabase()
        self._p2p_connections: list[Peer] = []
        self._nodes: set[Peer] = set()
        self._cbf_peer_hosts: list[str] = []
        self._cbf_peer_count: int = 0
        self._last_progress_info: ProgressInfo | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(12)

        self.title_label = QLabel(self)
        title_font = QFont(self.title_label.font())
        title_font.setPointSize(max(15, title_font.pointSize() + 3))
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.subtitle_label = QLabel(self)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.privacy_help_label = IconLabel(parent=self)
        self.privacy_help_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.privacy_help_label.textLabel.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.privacy_help_label.textLabel.setWordWrap(False)

        self.map_widget = WorldPeerMapWidget(parent=self)

        self.progress_label = QLabel(self)
        progress_font = QFont(self.progress_label.font())
        progress_font.setPointSize(max(12, progress_font.pointSize() + 1))
        progress_font.setBold(True)
        self.progress_label.setFont(progress_font)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.progress_bar = CBFProgressBar(config=self.config, show_rich_infos=False, parent=self)

        self.timings_label = QLabel(self)
        self.timings_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        legend_layout = QHBoxLayout()
        self.peer_legend_label = IconLabel(parent=self)
        self.cbf_legend_label = IconLabel(parent=self)
        self.node_legend_label = IconLabel(parent=self)
        legend_layout.addStretch()
        legend_layout.addWidget(self.peer_legend_label)
        legend_layout.addWidget(self.cbf_legend_label)
        legend_layout.addWidget(self.node_legend_label)
        legend_layout.addStretch()

        layout.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.privacy_help_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.map_widget)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.timings_label)
        layout.addLayout(legend_layout)
        layout.addStretch(1)

        self.updateUi()
        self._refresh_points_and_legend()

    def set_progress_info(self, progress_info: ProgressInfo) -> None:
        self._last_progress_info = progress_info
        percent = int(progress_info.progress * 100)
        if progress_info.status_msg:
            progress_message = progress_info.status_msg
        else:
            progress_message = self.tr("Sync progress: {percent}%").format(percent=percent)
        self.progress_label.setText(progress_message)
        self.progress_bar._set_progress_info(progress_info)

        self.timings_label.setText(
            self.tr("Elapsed {elapsed} | Estimated remaining {remaining}").format(
                elapsed=age(from_date=progress_info.passed_time),
                remaining=age(from_date=progress_info.remaining_time),
            )
        )

    def set_p2p_listener_peers(self, connections: list[Peer]) -> None:
        self._p2p_connections = list(connections)
        self._refresh_points_and_legend()

    def set_nodes(self, nodes: set[Peer]) -> None:
        self._nodes = set(nodes)
        self._refresh_points_and_legend()

    def set_cbf_peer_hosts(self, peer_hosts: list[str]) -> None:
        self._cbf_peer_hosts = list(peer_hosts)
        self._refresh_points_and_legend()

    def set_cbf_peer_count(self, count: int) -> None:
        self._cbf_peer_count = max(0, count)
        self._refresh_points_and_legend()

    def updateUi(self) -> None:
        """Update translated labels."""
        self.title_label.setText(self.tr("Scanning Bitcoin blockchain"))
        self.subtitle_label.setText(
            self.tr(
                "During first sync, Bitcoin Safe fetches compact block summaries from multiple Bitcoin nodes. "
                "This is a private way to download block data."
            )
        )
        self.privacy_help_label.set_icon_as_help(
            tooltip=self.tr(
                "Compact Block Filters (BIP157/BIP158) let wallets discover relevant transactions "
                "while keeping your addresses private."
            ),
            click_url=self._PRIVACY_INFO_URL,
        )
        self.privacy_help_label.setText(self.tr("Why this protects privacy (learn more)"))
        if self._last_progress_info:
            self.set_progress_info(self._last_progress_info)
        else:
            self.progress_label.setText(self.tr("Preparing private sync…"))
            self.progress_bar.setValue(0)
            self.timings_label.setText("")
        self._refresh_points_and_legend()

    def _build_mapped_points(self, hosts: list[str], source: PeerSource) -> list[PeerMapPoint]:
        points: list[PeerMapPoint] = []
        for host in hosts:
            location = self.geoip.lookup_host(host)
            if not location:
                continue
            points.append(
                PeerMapPoint(
                    latitude=location.latitude,
                    longitude=location.longitude,
                    host=host,
                    source=source,
                    country_code=location.country_code,
                )
            )
        return points

    def _refresh_points_and_legend(self) -> None:
        p2p_connections = tuple(self._p2p_connections)
        nodes = tuple(self._nodes)
        cbf_peer_hosts = tuple(self._cbf_peer_hosts)
        cbf_peer_count = self._cbf_peer_count

        p2p_hosts = [peer.host for peer in p2p_connections]
        p2p_host_set = set(p2p_hosts)
        node_hosts = [peer.host for peer in nodes if peer.host not in p2p_host_set]

        node_points = self._build_mapped_points(node_hosts, PeerSource.node)
        p2p_points = self._build_mapped_points(p2p_hosts, PeerSource.p2p_listener)
        cbf_points = self._build_mapped_points(list(cbf_peer_hosts), PeerSource.cbf)

        self.map_widget.set_points(node_points + p2p_points + cbf_points)

        gray = self.map_widget._LAND_FILL.name()
        self.peer_legend_label.setText(
            self.tr(
                "<span style='color:{color}'>●</span> P2P listener peers: {total} "
                "<span style='color:{gray}'>(mapped: {mapped})</span> &nbsp;&nbsp; "
            ).format(
                total=len(p2p_connections),
                mapped=len(p2p_points),
                color=self.map_widget._P2P_COLOR.name(),
                gray=gray,
            )
        )
        self.peer_legend_label.set_icon_as_help(
            tooltip=self.tr(
                "Recently broadcasted messages are received\nfrom these peers via the bitcoin network."
            )
        )

        self.cbf_legend_label.setText(
            self.tr(
                "<span style='color:{color}'>●</span> CBF peers: {total} "
                "<span style='color:{gray}'>(mapped: {mapped})</span>"
            ).format(
                total=max(cbf_peer_count, len(cbf_peer_hosts)),
                mapped=len(cbf_points),
                color=self.map_widget._CBF_COLOR.name(),
                gray=gray,
            )
        )
        self.cbf_legend_label.set_icon_as_help(
            tooltip=self.tr(
                "Short summaries (Compact Block Filters) and bitcoin blocks are"
                "\nreceived from these peers via the bitcoin network."
            )
        )

        self.node_legend_label.setText(
            self.tr(
                "<span style='color:{color}'>●</span> Bitcoin nodes: {total} "
                "<span style='color:{gray}'>(mapped: {mapped})</span>"
            ).format(
                total=len(nodes),
                mapped=len(node_points),
                color=self.map_widget._NODE_COLOR.name(),
                gray=gray,
            )
        )
        self.node_legend_label.set_icon_as_help(tooltip=self.tr("Discovered bitcoin nodes."))
