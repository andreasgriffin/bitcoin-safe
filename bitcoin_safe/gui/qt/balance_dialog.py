#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2013 ecdsa@github
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
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
import logging

logger = logging.getLogger(__name__)


from PySide2.QtCore import QRect, Qt
from PySide2.QtGui import QPainter, QPalette, QPen
from PySide2.QtWidgets import (
    QToolButton,
    QWidget,
)

from .util import (
    ColorScheme,
    font_height,
)

# Todo:
#  show lightning funds that are not usable
#  pie chart mouse interactive, to prepare a swap

COLOR_CONFIRMED = Qt.green
COLOR_UNCONFIRMED = Qt.red
COLOR_UNMATURED = Qt.magenta
COLOR_FROZEN = ColorScheme.BLUE.as_color(True)
COLOR_LIGHTNING = Qt.yellow
COLOR_FROZEN_LIGHTNING = Qt.cyan


class PieChartObject:
    def paintEvent(self, event):
        self.palette().color(QPalette.Background)
        pen = QPen(Qt.gray, 1, Qt.SolidLine)
        qp = QPainter()
        qp.begin(self)
        qp.setPen(pen)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setBrush(Qt.gray)
        total = sum([x[2] for x in self._list])
        if total == 0:
            return
        alpha = 0
        for name, color, amount in self._list:
            delta = int(16 * 360 * amount / total)
            qp.setBrush(color)
            qp.drawPie(self.R, alpha, delta)
            alpha += delta
        qp.end()


class PieChartWidget(QWidget, PieChartObject):
    def __init__(self, size, l):
        QWidget.__init__(self)
        self.size = size
        self.R = QRect(0, 0, self.size, self.size)
        self.setGeometry(self.R)
        self.setMinimumWidth(self.size)
        self.setMaximumWidth(self.size)
        self.setMinimumHeight(self.size)
        self.setMaximumHeight(self.size)
        self._list = l  # list[ (name, color, amount)]
        self.update()

    def update_list(self, l):
        self._list = l
        self.update()


class BalanceToolButton(QToolButton, PieChartObject):
    def __init__(self):
        QToolButton.__init__(self)
        self.size = max(18, font_height())
        self._list = []
        self.R = QRect(6, 3, self.size, self.size)

    def update_list(self, l):
        self._list = l
        self.update()

    def setText(self, text):
        # this is a hack
        QToolButton.setText(self, "       " + text)

    def paintEvent(self, event):
        QToolButton.paintEvent(self, event)
        PieChartObject.paintEvent(self, event)


class LegendWidget(QWidget):
    size = 20

    def __init__(self, color):
        QWidget.__init__(self)
        self.color = color
        self.R = QRect(0, 0, self.size, int(self.size * 0.75))
        self.setGeometry(self.R)
        self.setMinimumWidth(self.size)
        self.setMaximumWidth(self.size)
        self.setMinimumHeight(self.size)
        self.setMaximumHeight(self.size)

    def paintEvent(self, event):
        self.palette().color(QPalette.Background)
        pen = QPen(Qt.gray, 1, Qt.SolidLine)
        qp = QPainter()
        qp.begin(self)
        qp.setPen(pen)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setBrush(self.color)
        qp.drawRect(self.R)
        qp.end()
