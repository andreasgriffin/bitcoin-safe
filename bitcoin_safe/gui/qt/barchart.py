import logging

logger = logging.getLogger(__name__)

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QHoverEvent,
    QMouseEvent,
    QPen,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsView,
    QToolTip,
)


class BarSegment(QGraphicsRectItem):
    def __init__(self, y, fee, height, color, parent=None):
        self.x = 0  # x remains constant as we stack vertically
        self.y = y
        self.height = height
        self.color = color
        super().__init__(self.x, self.y, 1, self.height, parent)
        self.setBrush(QBrush(QColor(color)))
        self.setPen(Qt.PenStyle.NoPen)
        self.fee = fee
        self.setAcceptHoverEvents(True)
        # self.text_item = QGraphicsTextItem(f"{self.fee} vByte/Sat: {self.height} vMB", parent=self)
        # self.text_item.setFont(QFont("Arial", 0.04)) # Adjust font size to fit the bar
        # self.text_item.setPos(self.x + 5 - self.text_item.boundingRect().width() / 2, self.y + self.height - self.text_item.boundingRect().height())

    def hoverEnterEvent(self, event: QHoverEvent):
        QToolTip.showText(
            event.scenePosition().toPoint(), f"{self.fee} Sat/vB: {round(self.height/1e6,2)} MvB"
        )
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QHoverEvent):
        QToolTip.hideText()
        super().hoverLeaveEvent(event)


class Line(QGraphicsLineItem):
    def __init__(self, y: float, fee, hover_text, parent=None) -> None:
        self.y = y
        self.fee = fee
        super().__init__(0, self.y, 1, self.y, parent)
        self.hover_text = hover_text

        self.setAcceptHoverEvents(True)  # Ensures the item can respond to hover events

    def hoverEnterEvent(self, event: QHoverEvent):
        QToolTip.showText(event.scenePosition().toPoint(), self.hover_text)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QHoverEvent):
        QToolTip.hideText()
        super().hoverLeaveEvent(event)


class SingleBarChart(QGraphicsView):
    signal_click = pyqtSignal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.total_height = 0
        self.current_fee = None

        # Set the cursor to a hand cursor
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def resizeEvent(self, event: QResizeEvent):
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.IgnoreAspectRatio)
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        # Convert the mouse event's position to the scene coordinates
        scene_point: QPointF = self.mapToScene(event.pos())
        # print(f"Clicked at y={scene_point.y()}")
        self.signal_click(scene_point.y())
        super().mousePressEvent(event)  # call the parent class's method

    def add_segment(self, fee, height, color) -> QGraphicsItem:
        segment = BarSegment(self.total_height, fee, height, color=color)
        self.scene().addItem(segment)
        self.total_height += height
        return segment

    def add_horizontal_line(self, y, fee, hover_text, color="gray") -> QGraphicsItem:
        pen = QPen(QColor(color))
        pen.setWidth(self.total_height / 100)
        line = Line(y, fee, hover_text)
        line.setPen(pen)
        line.setZValue(1)  # Ensure that lines are drawn on top of bars
        self.scene().addItem(line)
        return line

    def set_current_fee(self, y, fee, color="black"):
        if self.current_fee:
            self.scene().removeItem(self.current_fee)
            self.current_fee = None

        self.current_fee = self.add_horizontal_line(
            y,
            fee,
            hover_text=f"Current transaction fee = {round(fee,1)} Sat/vB",
            color=color,
        )
