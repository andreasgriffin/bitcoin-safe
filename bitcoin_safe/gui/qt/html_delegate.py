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


import logging

logger = logging.getLogger(__name__)

from PyQt6.QtCore import QModelIndex, QPoint, QSize
from PyQt6.QtGui import QHelpEvent, QPainter, QTextDocument
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem


class HTMLDelegate:
    def __init__(self) -> None:
        pass

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if not painter:
            return
        model = index.model()
        if not model:
            return

        text = model.data(index)

        painter.save()

        (option.widget.style() or QStyle()).drawControl(
            QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget
        )

        x_shift = 0
        y_shift = -3

        painter.translate(option.rect.topLeft() + QPoint(int(x_shift), int(y_shift)))

        doc = QTextDocument()
        doc.setHtml(text)

        # Set the width to match the option.rect width
        doc.setTextWidth(option.rect.width())

        # Get the alignment from the model data
        # alignment = index.data(Qt.TextAlignmentRole)
        # if alignment is None:
        #     alignment = Qt.AlignLeft

        # Create a QTextOption and set its alignment
        # text_option = QTextOption()
        # text_option.setAlignment(option.widget.style().displayAlignment)
        # doc.setDefaultTextOption(text_option)

        doc.drawContents(painter)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        model = index.model()
        if not model:
            return QSize()
        text = model.data(index)

        doc = QTextDocument()
        doc.setHtml(text)
        doc.setTextWidth(200)  # Set a fixed width for the calculation

        return QSize(int(doc.idealWidth()), int(doc.size().height() - 10))

    def show_tooltip(self, evt: QHelpEvent) -> bool:
        # QToolTip.showText(evt.globalPosition(), ', '.join(self.categories))
        return True
