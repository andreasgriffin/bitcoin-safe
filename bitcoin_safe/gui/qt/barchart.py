import logging
logger = logging.getLogger(__name__)

from PySide2.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QGraphicsView, QGraphicsScene, QGraphicsRectItem, QToolTip
from PySide2.QtCore import Qt, QRectF
from PySide2.QtGui import QBrush, QColor, QPainter
from PySide2.QtCore import QPointF
from PySide2.QtCore import Qt, QRectF
from PySide2.QtGui import QColor, QBrush, QFont
from PySide2.QtWidgets import QGraphicsLineItem, QGraphicsItem
from PySide2.QtGui import QPen
from PySide2.QtCore import Qt
import numpy as np
from ...mempool import get_block_min_fees, chartColors, bin_data, feeLevels, fetch_mempool_histogram, index_of_sum_until_including
from ...signals import Signal
from PySide2.QtGui import QCursor

class BarSegment(QGraphicsRectItem):
    def __init__(self, y, fee, height, color, parent=None):
        self.x = 0  # x remains constant as we stack vertically
        self.y = y
        self.height = height
        self.color = color
        super().__init__(self.x, self.y, 1, self.height, parent)
        self.setBrush(QBrush(QColor(color)))
        self.setPen(Qt.NoPen)
        self.fee = fee
        self.setAcceptHoverEvents(True)
        # self.text_item = QGraphicsTextItem(f"{self.fee} vByte/Sat: {self.height} vMB", parent=self)
        # self.text_item.setFont(QFont("Arial", 0.04)) # Adjust font size to fit the bar
        # self.text_item.setPos(self.x + 5 - self.text_item.boundingRect().width() / 2, self.y + self.height - self.text_item.boundingRect().height())

    def hoverEnterEvent(self, event):
        QToolTip.showText(event.screenPos(), f"{self.fee} sat/vB: {round(self.height/1e6,2)} MvB")
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        QToolTip.hideText()
        super().hoverLeaveEvent(event)



class Line(QGraphicsLineItem):
    def __init__(self, y: float, fee, hover_text, parent= None) -> None:
        self.y = y
        self.fee = fee
        super().__init__(0, self.y, 1, self.y, parent)
        self.hover_text = hover_text
        
        self.setAcceptHoverEvents(True)  # Ensures the item can respond to hover events

    def hoverEnterEvent(self, event):
        QToolTip.showText(event.screenPos(), self.hover_text)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        QToolTip.hideText()
        super().hoverLeaveEvent(event)


class SingleBarChart(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.total_height = 0
        self.signal_click = Signal('signal_click')
        self.current_fee = None

        # Set the cursor to a hand cursor
        self.setCursor(QCursor(Qt.PointingHandCursor))
        
    def resizeEvent(self, event):
        self.fitInView(self.sceneRect(), Qt.IgnoreAspectRatio)
        super().resizeEvent(event)

    def mousePressEvent(self, event):
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

    def add_horizontal_line(self, y, fee, hover_text, color='gray') -> QGraphicsItem:
        pen = QPen(QColor(color))
        pen.setWidth(self.total_height/100) 
        line = Line(y, fee, hover_text)
        line.setPen(pen)
        line.setZValue(1)  # Ensure that lines are drawn on top of bars        
        self.scene().addItem(line)        
        return line

    def set_current_fee(self, y, fee, color='black'):
        if self.current_fee:
            self.scene().removeItem(self.current_fee)
            self.current_fee = None 
            
        self.current_fee = self.add_horizontal_line(y, fee, hover_text=f'Current transaction fee = {round(fee,1)} Sat/vB', color=color)
        


class MempoolBarChart:
    def __init__(self) -> None:
        self.data = None
        self.plotting_histogram = None
        
        self.signal_data_updated = Signal("signal_data_updated")
        self.signal_click = Signal("signal_data_updated")
        
        self.scene = QGraphicsScene()
        self.chart = SingleBarChart(self.scene)
        self.chart.signal_click.connect(self._on_bar_chart_click)
        self.chart.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chart.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chart.setRenderHint(QPainter.Antialiasing)
        
        self.signal_data_updated.connect(self._calculate_plotting_histogram)

    def _on_bar_chart_click(self, y):
        index = index_of_sum_until_including(self.data[:,1], y)
        fee = self.data[index, 0]
        self.signal_click(fee)

    def _calculate_plotting_histogram(self):
        self.data = self._cutoff_data(self.raw_data)
        self.plotting_histogram = bin_data(feeLevels, data=self.data)        
        self.update_mempool_chart()
    
    def set_data_from_file(self, datafile=None):
        self.raw_data = np.loadtxt(datafile, delimiter=",")
        self.signal_data_updated()
        
    def set_data(self, data):
        self.raw_data = data
        self.signal_data_updated()

    def set_data_from_mempoolspace(self):
        self.raw_data = fetch_mempool_histogram()
        self.signal_data_updated()

    def _cutoff_data(self, data):
        # cutoff all below low prio
        cutoff_filter = data[:,0] >  min(get_block_min_fees(data)[:,1])
        data = data[cutoff_filter]
        return data

    def update_mempool_chart(self):
        self.scene.clear()

        for color, (lower_fee, vbytes) in reversed(list(zip(chartColors, self.plotting_histogram))):
            if vbytes == 0: continue
            self.chart.add_segment(lower_fee, vbytes, color=color)

        # draw lines
        for block, fee in get_block_min_fees(self.data):
            y_block = block +1
            self.chart.add_horizontal_line(y_block*1e6, fee, f"Limit of {round(block+1)}-th predicted block ({round(fee,1)} sat/vB)")


        self.scene.setSceneRect(0, 0, 1, self.chart.total_height)  # set height of the scene based on total bar heights


        return self.chart 


