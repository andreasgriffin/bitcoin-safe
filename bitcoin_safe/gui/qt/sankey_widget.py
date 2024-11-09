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

import enum
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
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

logger = logging.getLogger(__name__)


class FlowType(enum.Enum):
    InFlow = enum.auto()
    OutFlow = enum.auto()


@dataclass
class FlowIndex:
    flow_type: FlowType
    i: int

    def __hash__(self) -> int:
        return hash(tuple(self.__dict__.items()))


class SankeyWidget(QWidget):
    signal_on_label_click = pyqtSignal(FlowIndex)

    center_color = QColor("#7616ff")
    border_color = QColor("#7616ff")

    def __init__(self, show_tooltips=True, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.show_tooltips = show_tooltips

        self.colors: Dict[FlowIndex, QColor] = {}
        self.labels: Dict[FlowIndex, str] | None = None
        self.text_outline = True
        self.text_rects: List[Tuple[QRectF, FlowIndex]] = []

        self.node_width: float = 0
        self.x_offset: float = 0
        self.setMouseTracking(True)  # Enable mouse tracking

        # self.signal_on_label_click.connect(lambda flow_index: print(flow_index))

        self.gradient_dict: Dict[str, Tuple[QColor, QColor]] = {}

    @property
    def image_width(self) -> float:
        return self.width()

    @property
    def xscaling(self) -> float:
        return self.image_width / 1000

    @property
    def image_height(self) -> float:
        return min(self.height(), self.width() * 0.8)

    @property
    def yscaling(self) -> float:

        available_space_raw = max(self.sum_in_flows_raw / (1 - self.space_fraction), 1)

        return self.image_height / available_space_raw

    @property
    def flow_thickness(self) -> float:
        return self.sum_in_flows_raw * self.yscaling

    @property
    def in_flows(self) -> List[float]:
        return [width * self.yscaling for width in self.in_flows_raw]

    @property
    def out_flows(self) -> List[float]:
        return [width * self.yscaling for width in self.out_flows_raw]

    @property
    def end_in_y_positions(self) -> List[float]:
        return self.find_best_positions(
            self.in_flows, self.flow_thickness, offset=(self.image_height - self.flow_thickness) / 2
        )

    @property
    def end_out_y_positions(self) -> List[float]:
        return self.find_best_positions(
            self.out_flows, self.flow_thickness, offset=(self.image_height - self.flow_thickness) / 2
        )

    @property
    def in_flow_y_positions(self) -> List[float]:
        return self.find_best_positions(self.in_flows, self.image_height)

    @property
    def out_flow_y_positions(self) -> List[float]:
        return self.find_best_positions(self.out_flows, self.image_height)

    def set(
        self,
        in_flows: Iterable[float],
        out_flows: Iterable[float],
        colors: Dict[FlowIndex, QColor] | None = None,
        labels: Dict[FlowIndex, str] | None = None,
        tooltips: Dict[FlowIndex, str] | None = None,
        center_color=None,
        space_fraction=0.5,
        text_outline=True,
    ):
        self.center_color = center_color if center_color else self.center_color
        self.labels = labels if labels else {}
        self.tooltips = tooltips if tooltips else {}
        self.colors = colors if colors else {}
        self.text_outline = text_outline
        self.space_fraction = max(min(space_fraction, 0.95), 0)

        self.in_flows_raw = in_flows
        self.out_flows_raw = out_flows
        self.sum_in_flows_raw = sum(self.in_flows_raw)
        self.sum_out_flows_raw = sum(self.out_flows_raw)

        assert (
            self.sum_in_flows_raw == self.sum_out_flows_raw
        ), f"Inflows {self.sum_in_flows_raw} dont match outflows {self.sum_out_flows_raw}"

        self.node_width = 0
        self.x_offset = 0

    @staticmethod
    def _find_best_positions(thicknesses: List[float], available_space: float) -> List[float]:
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
        cls, thicknesses: List[float], available_space: float, offset: float = 0
    ) -> List[float]:
        positions = cls._find_best_positions(thicknesses, available_space=available_space)
        return [pos + offset for pos in positions]

    def _paint_one_side(
        self,
        painter: QPainter,
        flows: Iterable[float],
        y_start_positions: List[float],
        end_y_positions: List[float],
        flow_type: FlowType,
        reverse=False,
        workaround_for_svg=False,
    ):
        image_left = (
            self.x_offset if not reverse else self.image_width + self.x_offset
        )  # Starting x position, adjusted if reversed
        image_right = self.image_width // 2  # End position of the bezier curve, depends on direction
        direction = (
            1 if not reverse else -1
        )  # Direction of bezier control points, reversed if flow is reversed

        # Draw flows
        for i, (start_y, end_y, width) in enumerate(zip(y_start_positions, end_y_positions, flows)):
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

            # Draw text at the start point
            if self.labels and flow_index in self.labels:
                self.draw_multiline_text(
                    painter,
                    self.labels[flow_index],
                    QPointF(image_left, start_y),
                    direction,
                    flow_index=FlowIndex(flow_type=flow_type, i=i),
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

    def draw_multiline_text(
        self, painter: QPainter, text: str, position: QPointF, direction: int, flow_index: FlowIndex
    ):
        painter.setPen(QColor("black"))
        font_metrics = painter.fontMetrics()
        lines = text.split("\n")  # Split the text into lines
        x, y = position.x(), position.y()

        for i, line in enumerate(lines):
            text_width = font_metrics.horizontalAdvance(line)
            # Adjust x position based on direction and width of the text
            text_x = x + (5 * direction) - (text_width if direction == -1 else 0)
            sub_position = QPointF(text_x, y + i * font_metrics.height())
            # save the full-text (not just the line)  at the sub_position in text_positions
            self.text_rects.append(
                (
                    QRectF(
                        sub_position.x(),
                        sub_position.y() - font_metrics.height(),
                        text_width,
                        font_metrics.height(),
                    ),
                    flow_index,
                )
            )
            # Draw text line by line
            if self.text_outline:
                self.draw_text_with_outline(painter, line, sub_position)
            else:
                painter.drawText(sub_position, line)

    def draw_text_with_outline(self, painter: QPainter, text: str, position: QPointF):
        # Configuration for the outline
        outline_offset = 1  # How far the outline is from the text
        outline_color = QColor("white")
        text_color = QColor("black")  # Color of the main text

        # Create a list of positions for the outline around the original position
        offsets = [
            QPointF(outline_offset, 0),
            QPointF(-outline_offset, 0),
            QPointF(0, outline_offset),
            QPointF(0, -outline_offset),
            QPointF(outline_offset, outline_offset),
            QPointF(-outline_offset, -outline_offset),
            QPointF(outline_offset, -outline_offset),
            QPointF(-outline_offset, outline_offset),
        ]

        # Draw the outline by offsetting the text slightly in various directions
        painter.setPen(outline_color)
        for offset in offsets:
            painter.drawText(position + offset, text)

        # Draw the main text on top
        painter.setPen(text_color)
        painter.drawText(position, text)

    def draw_content(self, painter: QPainter, workaround_for_svg=False):
        self.gradient_dict.clear()
        self.text_rects.clear()

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
        painter.end()

    def paintEvent(self, event):
        painter = QPainter(self)
        self.draw_content(painter)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if not event:
            return
        if not self.show_tooltips:
            return
        for rect, flow_index in self.text_rects:
            if flow_index not in self.tooltips:
                continue
            if rect.contains(event.position()):
                # Convert widget-relative position to global position for the tooltip
                globalPos = self.mapToGlobal(event.position().toPoint())
                QToolTip.showText(globalPos, self.tooltips[flow_index], self)
                return  # Exit after showing one tooltip
        QToolTip.hideText()  # Hide tooltip if no text is hovered

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if not event:
            return

        if event.button() == Qt.MouseButton.RightButton:
            # Right-click detected, show context menu
            menu = QMenu(self)
            export_action = QAction("Export to svg", self)
            menu.addAction(export_action)
            # Connect the action to the export method
            export_action.triggered.connect(self.export_to_svg)
            # Show the menu at the cursor position
            menu.exec(event.globalPosition().toPoint())
        else:
            # Handle other mouse events (e.g., left-click)
            for rect, flow_index in self.text_rects:
                if rect.contains(event.position()):
                    self.signal_on_label_click.emit(flow_index)
                    break

    def export_to_svg(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export svg"), "", self.tr("All Files (*);;Text Files (*.svg)")
        )
        if not file_path:
            logger.info("No file selected")
            return
        self._export_to_svg(Path(file_path))

    def _export_to_svg(self, filename: Path) -> None:
        self.workaround_for_svg = True
        width, height = self.width(), self.height()
        generator = QSvgGenerator()
        generator.setFileName(str(filename))
        generator.setSize(QSize(width, height))
        generator.setViewBox(QRect(0, 0, width, height))

        generator.setTitle("SVG Export by Bitcoin Safe")
        generator.setDescription("SVG Export by Bitcoin Safe")

        self.draw_content(QPainter(generator), workaround_for_svg=True)

        with open(str(filename), "r") as file:
            contents = file.read()
        with open(str(filename), "w") as file:
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
    labels: Dict[FlowIndex, str] = {
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
