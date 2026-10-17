#
# Bitcoin-Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import enum
import logging
import math
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFontMetricsF,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
    QShowEvent,
    QStaticText,
)
from PyQt6.QtSvg import QSvgGenerator
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QTabWidget,
    QToolTip,
    QWidget,
)

from bitcoin_safe.constants import APP_NAME
from bitcoin_safe.gui.qt.util import ColorScheme, svg_tools

logger = logging.getLogger(__name__)


class FlowType(enum.Enum):
    InFlow = enum.auto()
    OutFlow = enum.auto()


@dataclass
class FlowIndex:
    flow_type: FlowType
    i: int

    def __hash__(self) -> int:
        """Return hash value."""
        return hash((self.flow_type, self.i))


class SankeyWidget(QWidget):
    signal_on_label_click = cast(SignalProtocol[[FlowIndex]], pyqtSignal(FlowIndex))
    signal_data_changed = pyqtSignal()

    center_color = ColorScheme.Purple.as_color()
    border_color = ColorScheme.Purple.as_color()

    def __init__(self, show_tooltips=True, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.show_tooltips = show_tooltips
        self._has_data = False

        self.colors: dict[FlowIndex, QColor] = {}
        self.labels: dict[FlowIndex, str] | None = None
        self.text_outline = True
        self.text_rects: list[tuple[QRectF, FlowIndex]] = []
        self._label_texts: dict[FlowIndex, QStaticText] = {}
        self._label_positions: dict[FlowIndex, QPointF] = {}
        self._labels_need_update = False

        self.node_width: float = 0
        self.x_offset: float = 0
        self.setMouseTracking(True)  # Enable mouse tracking

        # self.signal_on_label_click.connect(lambda flow_index: print(flow_index))

        self.gradient_dict: dict[str, tuple[QColor, QColor]] = {}
        self.signal_data_changed.connect(self._on_data_changed)

    def _on_data_changed(self) -> None:
        """Schedule repainting on the GUI thread after worker-thread updates."""
        self.update()

    @property
    def image_width(self) -> float:
        """Image width."""
        return self.width()

    @property
    def xscaling(self) -> float:
        """Xscaling."""
        return self.image_width / 1000

    @property
    def image_height(self) -> float:
        """Image height."""
        return min(self.height(), self.width() * 0.8)

    @property
    def yscaling(self) -> float:
        """Yscaling."""
        available_space_raw = max(self.sum_in_flows_raw / (1 - self.space_fraction), 1)

        return self.image_height / available_space_raw

    @property
    def flow_thickness(self) -> float:
        """Flow thickness."""
        return self.sum_in_flows_raw * self.yscaling

    @property
    def in_flows(self) -> list[float]:
        """In flows."""
        return [width * self.yscaling for width in self.in_flows_raw]

    @property
    def out_flows(self) -> list[float]:
        """Out flows."""
        return [width * self.yscaling for width in self.out_flows_raw]

    @property
    def end_in_y_positions(self) -> list[float]:
        """End in y positions."""
        return self.find_best_positions(
            self.in_flows, self.flow_thickness, offset=(self.image_height - self.flow_thickness) / 2
        )

    @property
    def end_out_y_positions(self) -> list[float]:
        """End out y positions."""
        return self.find_best_positions(
            self.out_flows, self.flow_thickness, offset=(self.image_height - self.flow_thickness) / 2
        )

    @property
    def in_flow_y_positions(self) -> list[float]:
        """In flow y positions."""
        return self.find_best_positions(self.in_flows, self.image_height)

    @property
    def out_flow_y_positions(self) -> list[float]:
        """Out flow y positions."""
        return self.find_best_positions(self.out_flows, self.image_height)

    def set(
        self,
        in_flows: Iterable[float],
        out_flows: Iterable[float],
        colors: dict[FlowIndex, QColor] | None = None,
        labels: dict[FlowIndex, str] | None = None,
        tooltips: dict[FlowIndex, str] | None = None,
        center_color=None,
        space_fraction=0.5,
        text_outline=True,
    ):
        """Set."""
        self.center_color = center_color if center_color else self.center_color
        self.labels = labels if labels else {}
        self.tooltips = tooltips if tooltips else {}
        self.colors = colors if colors else {}
        self.text_outline = text_outline
        self.space_fraction = max(min(space_fraction, 0.95), 0)

        self.in_flows_raw = list(in_flows)
        self.out_flows_raw = list(out_flows)
        self.sum_in_flows_raw = sum(self.in_flows_raw)
        self.sum_out_flows_raw = sum(self.out_flows_raw)

        assert self.sum_in_flows_raw == self.sum_out_flows_raw, (
            f"Inflows {self.sum_in_flows_raw} dont match outflows {self.sum_out_flows_raw}"
        )

        self.node_width = 0
        self.x_offset = 0
        # set_tx() can run on the asyncio worker thread.  Do not touch Qt GUI
        # objects here; labels are prepared by draw_content() on the GUI thread.
        self._has_data = True
        self._labels_need_update = True
        self.signal_data_changed.emit()

    def _create_label_texts(self) -> None:
        """Prepare multiline labels without creating child widgets."""
        self._label_texts = {}
        for flow_index, text in (self.labels or {}).items():
            if not text:
                continue
            static_text = QStaticText(text)
            static_text.setTextFormat(Qt.TextFormat.PlainText)
            self._label_texts[flow_index] = static_text

    def _update_label_positions(self) -> None:
        """Position label overlays according to the current diagram geometry."""
        self.text_rects.clear()
        self._label_positions.clear()
        if not self._label_texts or self.width() <= 0 or self.height() <= 0:
            self._labels_need_update = False
            return

        # QStaticText.size() crashes in some Flatpak Qt builds, so measure the
        # (already ascii-only) text with QFontMetricsF instead.
        font_metrics = QFontMetricsF(self.font())
        positions = (
            (FlowType.InFlow, self.in_flow_y_positions, False),
            (FlowType.OutFlow, self.out_flow_y_positions, True),
        )
        for flow_type, y_positions, reverse in positions:
            image_left = self.x_offset if not reverse else self.image_width + self.x_offset
            direction = -1 if reverse else 1
            for index, y_position in enumerate(y_positions):
                flow_index = FlowIndex(flow_type, index)
                static_text = self._label_texts.get(flow_index)
                if static_text is None:
                    continue

                text_size = font_metrics.boundingRect(
                    QRectF(), int(Qt.TextFlag.TextExpandTabs), static_text.text()
                )
                x_position = image_left + 5 * direction
                if reverse:
                    x_position -= text_size.width()
                y_position -= text_size.height()
                position = QPointF(x_position, y_position)
                self._label_positions[flow_index] = position
                self.text_rects.append((QRectF(position, text_size.size()), flow_index))

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._labels_need_update = True

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self._labels_need_update = True

    def changeEvent(self, a0: QEvent | None) -> None:
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.FontChange:
            self._labels_need_update = True

    @staticmethod
    def _find_best_positions(thicknesses: list[float], available_space: float) -> list[float]:
        """Find best positions."""
        total_space = available_space - sum(thicknesses)
        space = total_space / max(len(thicknesses), 1)

        positions = []
        cursor = -space / 2
        for thickness in thicknesses:
            cursor += space + thickness / 2
            positions.append(cursor)
            # move the cursor further
            cursor += thickness / 2
        return positions

    @classmethod
    def find_best_positions(
        cls, thicknesses: list[float], available_space: float, offset: float = 0
    ) -> list[float]:
        """Find best positions."""
        positions = cls._find_best_positions(thicknesses, available_space=available_space)
        return [pos + offset for pos in positions]

    def _paint_one_side(
        self,
        painter: QPainter,
        flows: Iterable[float],
        y_start_positions: list[float],
        end_y_positions: list[float],
        flow_type: FlowType,
        reverse=False,
        workaround_for_svg=False,
    ):
        """Paint one side."""
        image_left = (
            self.x_offset if not reverse else self.image_width + self.x_offset
        )  # Starting x position, adjusted if reversed
        image_right = self.image_width // 2  # End position of the bezier curve, depends on direction
        direction = (
            1 if not reverse else -1
        )  # Direction of bezier control points, reversed if flow is reversed

        # Draw flows
        for i, (start_y, end_y, width) in enumerate(
            zip(y_start_positions, end_y_positions, flows, strict=False)
        ):
            flow_index = FlowIndex(flow_type, i)
            start_x = image_left + (self.node_width + width // 2) * direction  # compensat for brush width
            end_x = image_right - width / 2 * direction  # compensat for brush width

            self.draw_path(
                painter,
                width,
                start_x,
                start_y,
                end_x,
                end_y,
                direction,
                self.colors.get(flow_index, self.border_color),
                self.center_color,
                workaround_for_svg=workaround_for_svg,
            )

    def draw_path(
        self,
        painter: QPainter,
        width,
        start_x,
        start_y,
        end_x,
        end_y,
        direction: int,
        start_color: QColor,
        end_color: QColor,
        workaround_for_svg=False,
    ):
        """Draw path."""
        path = QPainterPath()
        path.moveTo(start_x, start_y)
        path.cubicTo(
            math.ceil(start_x + 100 * self.xscaling * direction),
            math.ceil(start_y),
            math.ceil(end_x - 100 * self.xscaling * direction),
            math.ceil(end_y),
            math.ceil(end_x) + direction,  # the +-1  is to close any gaps that might occur
            math.ceil(end_y),
        )

        pen = QPen()
        if workaround_for_svg:
            color_name = QColor(len(self.gradient_dict)).name()
            self.gradient_dict[color_name] = (
                (start_color, end_color) if direction == 1 else (end_color, start_color)
            )
            pen.setBrush(QColor(color_name))
        else:
            gradient = QLinearGradient(QPointF(start_x, start_y), QPointF(end_x, end_y))
            gradient.setColorAt(0, start_color)
            gradient.setColorAt(1, end_color)
            pen.setBrush(gradient)
        pen.setWidth(math.ceil(width))
        painter.setPen(pen)
        painter.drawPath(path)

    def draw_content(self, painter: QPainter, workaround_for_svg=False):
        """Draw content."""
        if not painter.isActive() or self.width() <= 0 or self.height() <= 0:
            return

        if self._labels_need_update:
            self._create_label_texts()
            self._update_label_positions()

        self.gradient_dict.clear()
        self._paint_one_side(
            painter,
            self.in_flows,
            y_start_positions=self.in_flow_y_positions,
            end_y_positions=self.end_in_y_positions,
            flow_type=FlowType.InFlow,
            workaround_for_svg=workaround_for_svg,
        )
        self._paint_one_side(
            painter,
            self.out_flows,
            y_start_positions=self.out_flow_y_positions,
            end_y_positions=self.end_out_y_positions,
            reverse=True,
            flow_type=FlowType.OutFlow,
            workaround_for_svg=workaround_for_svg,
        )
        painter.save()
        painter.setClipRect(self.rect())
        for flow_index, position in self._label_positions.items():
            static_text = self._label_texts.get(flow_index)
            if static_text is not None:
                self._draw_label(painter, position, static_text)
        painter.restore()

    def _draw_label(self, painter: QPainter, position: QPointF, text: QStaticText) -> None:
        """Draw a label and its outline without using Qt's point text overload."""
        text_color = self.palette().color(QPalette.ColorRole.Text)
        if self.text_outline:
            painter.setPen(self.palette().color(QPalette.ColorRole.Base))
            for x_offset, y_offset in (
                (1, 0),
                (-1, 0),
                (0, 1),
                (0, -1),
                (1, 1),
                (-1, -1),
                (1, -1),
                (-1, 1),
            ):
                painter.drawStaticText(position + QPointF(x_offset, y_offset), text)
        painter.setPen(text_color)
        painter.drawStaticText(position, text)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """PaintEvent."""
        if not self._has_data or self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        try:
            self.draw_content(painter)
        finally:
            painter.end()

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        """MouseMoveEvent."""
        if not a0:
            return
        if not self.show_tooltips:
            return
        for rect, flow_index in self.text_rects:
            if flow_index not in self.tooltips:
                continue
            if rect.contains(a0.position()):
                # Convert widget-relative position to global position for the tooltip
                globalPos = self.mapToGlobal(a0.position().toPoint())
                QToolTip.showText(globalPos, self.tooltips[flow_index], None, msecShowTime=5000)
                return  # Exit after showing one tooltip
        # QToolTip.hideText()  # Hide tooltip if no text is hovered, this leads to flickering
        super().mouseMoveEvent(a0)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        """MousePressEvent."""
        if not a0:
            return

        if a0.button() == Qt.MouseButton.RightButton:
            # Right-click detected, show context menu
            menu = QMenu(self)
            export_action = QAction(self.tr("Export to SVG"), self)
            export_action.setIcon(svg_tools.get_QIcon("bi--filetype-svg.svg"))
            menu.addAction(export_action)
            # Connect the action to the export method
            export_action.triggered.connect(self.export_to_svg)
            # Show the menu at the cursor position
            menu.exec(a0.globalPosition().toPoint())
        else:
            # Handle other mouse events (e.g., left-click)
            for rect, flow_index in self.text_rects:
                if rect.contains(a0.position()):
                    self.signal_on_label_click.emit(flow_index)
                    break

    def export_to_svg(
        self,
    ) -> None:
        """Export to svg."""
        default_filename = "diagram.svg"
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export svg"), default_filename, self.tr("All Files (*);;Text Files (*.svg)")
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return
        self._export_to_svg(Path(file_path))

    def _export_to_svg(self, filename: Path) -> None:
        """Export to svg."""
        self.workaround_for_svg = True
        width, height = self.width(), self.height()
        generator = QSvgGenerator()
        generator.setFileName(str(filename))
        generator.setSize(QSize(width, height))
        generator.setViewBox(QRect(0, 0, width, height))

        generator.setTitle(f"SVG Export by {APP_NAME}")
        generator.setDescription(f"SVG Export by {APP_NAME}")

        painter = QPainter(generator)
        try:
            self.draw_content(painter, workaround_for_svg=True)
        finally:
            painter.end()

        with open(str(filename), encoding="utf-8") as file:
            contents = file.read()
        with open(str(filename), "w", encoding="utf-8") as file:
            defs = ""
            for color_name, (start_color, end_color) in self.gradient_dict.items():
                gradient_name = f"linear{color_name.lstrip('#')}"
                defs += f"""
    <linearGradient id="{gradient_name}" x1="0%" y1="0%" x2="100%" y2="0%">
    <stop offset="0%" stop-color="{start_color.name()}"/>
    <stop offset="100%" stop-color="{end_color.name()}"/>
    </linearGradient>
    """

                contents = contents.replace(f'stroke="{color_name}"', f'stroke="url(#{gradient_name})"')
            contents = contents.replace("<defs>\n</defs>", f"<defs>\n{defs}\n</defs>")

            file.write(contents)
        self.workaround_for_svg = False


if __name__ == "__main__":
    colors = {
        FlowIndex(FlowType.OutFlow, 1): QColor("#8af296"),
        FlowIndex(FlowType.OutFlow, 0): QColor("#f3f71b"),
        FlowIndex(FlowType.InFlow, 0): QColor("#8af296"),
    }
    # in_flows = [("apple", 50.0), ("banana", 30), ("orange", 20), ("lime", 10), ("blueberry", 40)]

    # out_flows = [
    #     ("fruit", 100.0),
    #     ("juice", 50.0),
    # ]

    in_flows = [
        70.0,
        30.0,
    ]

    out_flows = [
        65.0,
        30.0,
        5.0,
    ]
    labels: dict[FlowIndex, str] = {
        # FlowIndex(FlowType.InFlow, 0): "1\n1",
        # FlowIndex(FlowType.InFlow, 1): "2",
        # FlowIndex(FlowType.OutFlow, 0): "4",
        # FlowIndex(FlowType.OutFlow, 1): "4",
        # FlowIndex(FlowType.OutFlow, 2): "5",
    }

    app = QApplication(sys.argv)
    tabs = QTabWidget()

    sankey = SankeyWidget()
    sankey.set(
        in_flows=in_flows,
        out_flows=out_flows,
        colors=colors,
        text_outline=True,
        labels=labels,
        space_fraction=0.3,
    )
    tabs.addTab(sankey, "sankey")
    tabs.show()
    sys.exit(app.exec())
