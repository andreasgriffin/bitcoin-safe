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

import json
import logging
from functools import lru_cache, partial
from typing import Callable, Generator, Iterable, List, Optional, Tuple

from PyQt6.QtCore import (
    QMimeData,
    QModelIndex,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QWidget,
)

from bitcoin_safe.category_info import CategoryInfo, SubtextType
from bitcoin_safe.typestubs import TypedPyQtSignal, TypedPyQtSignalNo

from ....util import qbytearray_to_str, register_cache, str_to_qbytearray
from ..util import category_color

logger = logging.getLogger(__name__)


def clean_tag(tag: str) -> str:
    return tag.strip()


class AddressDragInfo:
    def __init__(self, tags: Iterable[Optional[str]], addresses: List[str]) -> None:
        self.tags = tags
        self.addresses = addresses

    def __repr__(self) -> str:
        return f"AddressDragInfo({self.tags}, {self.addresses})"


@register_cache(always_keep=True)
def cached_category_color(text: str) -> QColor:
    return category_color(text)


class CustomListWidgetItem(QListWidgetItem):
    def __init__(self, item_text: str, sub_text: str | None = None, parent=None):
        super(CustomListWidgetItem, self).__init__(parent)
        self.setText(item_text)
        self.subtext = sub_text
        self.color = self.category_color()
        self.setData(Qt.ItemDataRole.UserRole + 1, self.color)
        self.setData(Qt.ItemDataRole.UserRole + 2, self.subtext)  # UserRole for subtext

    def category_color(self):
        return cached_category_color(self.text())

    def mimeData(self):
        mime_data = QMimeData()
        d = {
            "type": "drag_tag",
            "tag": self.text(),
        }

        mime_data.setData("application/json", str_to_qbytearray(json.dumps(d)))
        return mime_data


class CustomDelegate(QStyledItemDelegate):
    signal_tag_renamed: TypedPyQtSignal[str, str] = pyqtSignal(str, str)  # type: ignore

    def __init__(self, editable=True, parent=None) -> None:
        super().__init__(parent)
        self.editable = editable
        self.currentlyEditingIndex = QModelIndex()
        self.cached_renderHtmlToImage: Callable[
            [QModelIndex, QStyleOptionViewItem, str, str, Tuple], QImage
        ] = lru_cache(maxsize=128)(self.renderHtmlToImage)

    @classmethod
    def expand_qobject(cls, obj) -> Tuple:
        d = {}
        for key in dir(obj):
            try:
                d[key] = str(getattr(obj, key))
            except:
                pass
        return tuple(d.items())

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex):
        if not painter:
            super().paint(painter=painter, option=option, index=index)
            return

        # Check if the editor is open for this index
        if self.currentlyEditingIndex.isValid() and self.currentlyEditingIndex == index:
            text = ""  # Set text to empty if editor is open
            subtext = ""
        else:
            text = index.data(Qt.ItemDataRole.DisplayRole)
            subtext = index.data(Qt.ItemDataRole.UserRole + 2)  # Assuming subtext is stored in UserRole + 2

        image = self.cached_renderHtmlToImage(index, option, text, subtext, self.expand_qobject(option))

        # Draw the cached image
        # image = self.imageCache[key]
        if image:
            painter.drawImage(option.rect.topLeft(), image)

    def renderHtmlToImage(
        self,
        index: QModelIndex,
        option: QStyleOptionViewItem,
        text: str,
        subtext: str,
        additional_keys: Tuple,
    ):
        """
        Renders the item appearance to an image, including button-like background and HTML text.
        """
        rectSize = QSize(option.rect.width(), option.rect.height())

        # Create an off-screen image for rendering
        image = QImage(rectSize, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)  # Fill with transparency for proper rendering
        painter = QPainter(image)

        # Mock-up style option for button rendering
        buttion_option = QStyleOptionButton()
        buttion_option.features = QStyleOptionButton.ButtonFeature.DefaultButton
        buttion_option.rect = QRect(0, 0, rectSize.width(), rectSize.height())
        buttion_option.state = QStyle.StateFlag.State_Raised

        if option.state & QStyle.StateFlag.State_Selected:
            buttion_option.state |= QStyle.StateFlag.State_Active
            color = QColor(
                index.data(Qt.ItemDataRole.UserRole + 1)
            )  # Assuming color is stored in UserRole + 1
            buttion_option.palette.setColor(QPalette.ColorRole.Button, color)
        else:
            pass

        # Draw button-like background
        (QApplication.style() or QStyle()).drawControl(
            QStyle.ControlElement.CE_PushButton, buttion_option, painter
        )

        # Render HTML text
        self.draw_html_text(painter, text, subtext, buttion_option.rect, scale=1)

        painter.end()
        return image

    @classmethod
    def set_text_color(cls, doc: QTextDocument, color: QColor):

        # Use a QTextCursor to select and format the entire document
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)

        # set the color to default black (because the background can be bright)
        charFormat = QTextCharFormat()
        charFormat.setForeground(color)  # Set the text color explicitly
        cursor.mergeCharFormat(charFormat)

    def draw_html_text(self, painter: QPainter, text: str, subtext: str, rect: QRect, scale: float):
        # Base font size adjustments (these are scale factors, adjust as needed)
        baseFontSize = 1.0  # Adjust this factor to scale the default font size for main text
        subtextFontSize = 0.8  # Adjust this factor for subtext

        # Get the default system font
        defaultFont = QApplication.font()

        # Calculate text and subtext positions more accurately
        textPadding = 4  # Adjust padding as needed
        subtextPadding = 2  # Adjust subtext padding

        # Height allocation (tweak these ratios as needed)
        textHeightRatio = 0.55  # Allocate 55% of the rect height to the main text
        subtextHeightRatio = 0.45  # Remaining 45% for the subtext

        # Main text area
        rectText = QRect(
            rect.left() + textPadding,
            rect.top() + textPadding,
            rect.width() - 2 * textPadding,
            int(rect.height() * textHeightRatio) - textPadding,
        )

        # Subtext area
        rectSubtext = QRect(
            rect.left() + subtextPadding,
            rect.top() + int(rect.height() * textHeightRatio),
            rect.width() - 2 * subtextPadding,
            int(rect.height() * subtextHeightRatio) - subtextPadding,
        )

        # Draw main text
        if text:
            doc = QTextDocument()

            doc.setHtml(text)
            font = QFont(defaultFont)  # Use the default system font
            font.setPointSizeF(defaultFont.pointSizeF() * baseFontSize)  # Apply scaling factor
            doc.setDefaultFont(font)
            # self.set_text_color(doc,color= QColor("black"))
            textOption = QTextOption()
            textOption.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center text horizontally
            doc.setDefaultTextOption(textOption)
            painter.save()
            painter.translate(rectText.topLeft())
            doc.setTextWidth(rectText.width())
            # Optional: Adjust for vertical centering
            yOffset = (rectText.height() - doc.size().height()) / 2
            painter.translate(0, max(yOffset, 0))
            doc.drawContents(painter)
            painter.restore()

        # Draw subtext
        if subtext:
            doc = QTextDocument()
            doc.setHtml(subtext)
            font = QFont(defaultFont)  # Use the default system font for subtext
            font.setPointSizeF(defaultFont.pointSizeF() * subtextFontSize)  # Apply scaling factor for subtext
            doc.setDefaultFont(font)
            # self.set_text_color(doc,color= QColor("black"))
            textOption = QTextOption()
            textOption.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center text horizontally
            doc.setDefaultTextOption(textOption)
            painter.save()
            painter.translate(rectSubtext.topLeft())
            doc.setTextWidth(rectSubtext.width())
            # Optional: Adjust for vertical centering
            yOffset = (rectSubtext.height() - doc.size().height()) / 2
            painter.translate(0, max(yOffset, 0))
            painter.scale(scale, scale)  # Apply scaling if needed
            doc.drawContents(painter)
            painter.restore()

    def createEditor(self, parent, option: QStyleOptionViewItem, index: QModelIndex) -> Optional[QWidget]:
        if not self.editable:
            return None
        self.currentlyEditingIndex = index
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setStyleSheet(
            """
            background: transparent;
            border: none;
        """
        )
        return editor

    def setEditorData(self, editor: QLineEdit, index: QModelIndex):  # type: ignore[override]
        model = index.model()
        if not model:
            return
        value = model.data(index, Qt.ItemDataRole.EditRole)
        editor.setText(value)

    def setModelData(self, editor: QLineEdit, model, index: QModelIndex):  # type: ignore[override]
        model = index.model()
        if not model:
            return
        old_value = model.data(index, Qt.ItemDataRole.EditRole)
        new_value = clean_tag(editor.text())

        model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)
        self.currentlyEditingIndex = QModelIndex()
        self.signal_tag_renamed.emit(old_value, new_value)


class CustomListWidget(QListWidget):
    signal_tag_added: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    signal_tag_clicked: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    signal_tag_deleted: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    signal_tag_renamed: TypedPyQtSignal[str, str] = pyqtSignal(str, str)  # type: ignore   # (old,new)
    signal_addresses_dropped: TypedPyQtSignal[AddressDragInfo] = pyqtSignal(AddressDragInfo)  # type: ignore
    signal_start_drag: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_stop_drag: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    def __init__(
        self,
        parent=None,
        editable=True,
        allow_no_selection=False,
        enable_drag=True,
        immediate_release=True,
        subtext_type: SubtextType = SubtextType.balance,
    ):
        super().__init__(parent)
        self.editable = editable
        self.subtext_type = subtext_type
        self.allow_no_selection = allow_no_selection
        self.immediate_release = immediate_release

        delegate = CustomDelegate(editable=editable, parent=self)
        delegate.signal_tag_renamed.connect(self.signal_tag_renamed)
        self.setItemDelegate(delegate)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QListWidget.SelectionBehavior.SelectItems)

        self.setAcceptDrops(True)
        if viewport := self.viewport():
            viewport.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragEnabled(enable_drag)  # this must be after the other drag toggles

        self.itemChanged.connect(self.on_item_changed)  # new

        self.setMouseTracking(True)
        self._drag_start_position: QPoint | None = None

        self.setStyleSheet(
            """
            QListWidget {
                background: transparent;
                border: none;
            }
            QListWidget::item {
                border-radius: 5px;
                margin: 15px;
            }
            QListWidget::item:selected {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #cccccc, stop:1 #b3b3b3);
                border: 1px solid black;
            }
            """
        )

    def add(self, item_text: str, sub_text=None) -> CustomListWidgetItem:
        item = CustomListWidgetItem(item_text, sub_text=sub_text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.addItem(item)
        self.signal_tag_added.emit(item_text)
        return item

    def on_item_clicked(self, item: QListWidgetItem):
        self.signal_tag_clicked.emit(item.text())
        # print( [item.text() for item in self.selectedItems()])

    def on_item_changed(self, item: CustomListWidgetItem):  # new

        item.color = item.category_color()
        item.setData(Qt.ItemDataRole.UserRole + 1, item.color)

        # Here you can handle the renaming event
        # For now, we will just print the new item text
        # print(f"Item text has been changed to {item.text()}")

    def get_selected(self) -> List[str]:
        return [item.text() for item in self.selectedItems()]

    def rename_selected(self, new_text: str):
        for item in self.selectedItems():
            item.text()
            item.setText(new_text)
            # item.setBackground()

    def mouseReleaseEvent(self, event: QMouseEvent | None):
        if event and event.button() == Qt.MouseButton.LeftButton:
            # Perform actions that should happen after the mouse button is released
            # This could be updating the state of the widget, triggering signals, etc.

            item = self.itemAt(event.pos())
            if item is not None and item.isSelected():
                self.on_item_clicked(item)
                if self.immediate_release:
                    if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
                        self.clearSelection()
                        return
        if event and event.button() == Qt.MouseButton.RightButton:
            # Get the item at the mouse position
            item = self.itemAt(event.pos())
            if item:
                self.show_context_menu(event.globalPosition(), item=item)
        else:
            super().mouseReleaseEvent(event)

    def show_context_menu(self, position: QPointF, item: QListWidgetItem):
        context_menu = QMenu(self)
        context_menu.addAction(self.tr("Delete Category"), partial(self.delete_item, item.text()))
        context_menu.exec(position.toPoint())

    def mouseMoveEvent(self, event: QMouseEvent | None):
        if not event:
            super().mouseMoveEvent(event)
            return

        if self._drag_start_position is None:
            self._drag_start_position = event.pos()
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.pos() - self._drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
        if self.dragEnabled():
            self.startDrag(Qt.DropAction.MoveAction)

        else:
            super().mouseMoveEvent(event)

    def startDrag(self, action: Qt.DropAction | None):
        item = self.currentItem()
        if not action or not isinstance(item, CustomListWidgetItem):
            return
        rect = self.visualItemRect(item)

        drag = QDrag(self)
        drag.setMimeData(item.mimeData())

        viewport = self.viewport()
        if not viewport:
            return
        pixmap = viewport.grab(rect)
        hotspot_pos = QPoint(0, 0)
        drag.setPixmap(pixmap)
        drag.setHotSpot(hotspot_pos)

        self.signal_start_drag.emit()

        drag.exec(action)

        self.signal_stop_drag.emit()
        self.clearSelection()

    def dragEnterEvent(self, event: QDragEnterEvent | None):
        if not event:
            super().dragEnterEvent(event)
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            # print('accept')
            # tag = self.itemAt(event.pos())

            json_string = qbytearray_to_str(mime_data.data("application/json"))
            # dropped_addresses = json.loads(json_string)
            # print(f'drag enter {dropped_addresses,   tag.text()}')
            logger.debug(f"dragEnterEvent: {json_string}")

            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent | None):
        super().dropEvent(event)
        if not event or event.isAccepted():
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            tag = self.itemAt(event.position().toPoint())

            json_string = qbytearray_to_str(mime_data.data("application/json"))

            d = json.loads(json_string)
            if d.get("type") == "drag_addresses":
                if tag is not None:
                    drag_info = AddressDragInfo([tag.text()], d.get("addresses"))
                    logger.debug(f"dropEvent: {drag_info}")
                    self.signal_addresses_dropped.emit(drag_info)
                event.accept()
                return

        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent | None):
        "do nothing"
        super().dragLeaveEvent(event)

    def delete_item(self, item_text: str):
        for i in range(self.count()):
            item = self.item(i)
            if item and item.text() == item_text:
                self.takeItem(i)
                self.signal_tag_deleted.emit(item_text)
                break

    def get_items(self) -> Generator[QListWidgetItem, None, None]:
        for i in range(self.count()):
            item = self.item(i)
            if item:
                yield item

    def get_item_texts(self) -> Generator[str, None, None]:
        for item in self.get_items():
            yield item.text()

    def recreate(self, category_infos: list[CategoryInfo]):
        # Store the texts of selected items
        selected_texts = [item.text() for item in self.selectedItems()]

        # Delete all items
        for i in reversed(range(self.count())):
            self.takeItem(i)

        # Add all items back
        for category_info in category_infos:
            subtext: str | None = None
            if self.subtext_type == SubtextType.hide:
                subtext = None
            if self.subtext_type == SubtextType.balance:
                subtext = category_info.text_balance
            elif self.subtext_type == SubtextType.click_new_address:
                subtext = category_info.text_click_new_address

            self.add(category_info.category, sub_text=subtext)  # Assuming `self.add` correctly adds items

        # Re-select items based on stored texts
        for i in range(self.count()):
            item = self.item(i)
            if item and item.text() in selected_texts:
                item.setSelected(True)
