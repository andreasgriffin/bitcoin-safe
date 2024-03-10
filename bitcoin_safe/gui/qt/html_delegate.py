import logging

logger = logging.getLogger(__name__)

from PyQt6.QtCore import QModelIndex, QPoint, QSize
from PyQt6.QtGui import QHelpEvent, QPainter, QTextDocument
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem


class HTMLDelegate:
    def __init__(self) -> None:
        pass

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        logger.debug("HTMLDelegate.paint")
        text = index.model().data(index)

        painter.save()

        option.widget.style().drawControl(
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

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        text = index.model().data(index)

        doc = QTextDocument()
        doc.setHtml(text)
        doc.setTextWidth(200)  # Set a fixed width for the calculation

        return QSize(doc.idealWidth(), doc.size().height() - 10)

    def show_tooltip(self, evt: QHelpEvent) -> bool:
        # QToolTip.showText(evt.globalPosition(), ', '.join(self.categories))
        return True
