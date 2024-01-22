from PySide2.QtCore import QPoint, QSize
from PySide2.QtGui import QHelpEvent, QTextDocument
from PySide2.QtWidgets import QStyle


class HTMLDelegate:
    def __init__(self) -> None:
        pass

    def paint(self, painter, option, index):
        text = index.model().data(index)

        painter.save()

        option.widget.style().drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)

        x_shift = 0
        y_shift = -3

        painter.translate(option.rect.topLeft() + QPoint(x_shift, y_shift))

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

    def sizeHint(self, option, index):
        text = index.model().data(index)

        doc = QTextDocument()
        doc.setHtml(text)
        doc.setTextWidth(200)  # Set a fixed width for the calculation

        return QSize(doc.idealWidth(), doc.size().height() - 10)

    def show_tooltip(self, evt: QHelpEvent) -> bool:
        # QToolTip.showText(evt.globalPos(), ', '.join(self.categories))
        return True
