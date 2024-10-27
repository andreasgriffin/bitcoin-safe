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

from ....i18n import translate
from ....util import qbytearray_to_str, register_cache, str_to_qbytearray

logger = logging.getLogger(__name__)

import hashlib
import json
from typing import Dict, Generator, Iterable, List, Optional, Tuple

from PyQt6.QtCore import QMimeData, QModelIndex, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPalette,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)


def clean_tag(tag: str) -> str:
    return tag.strip()


class AddressDragInfo:
    def __init__(self, tags: Iterable[Optional[str]], addresses: List[str]) -> None:
        self.tags = tags
        self.addresses = addresses

    def __repr__(self) -> str:
        return f"AddressDragInfo({self.tags}, {self.addresses})"


def hash_string(text: str) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()


def rescale(value: float, old_min: float, old_max: float, new_min: float, new_max: float):
    return (value - old_min) / (old_max - old_min) * (new_max - new_min) + new_min


@register_cache(always_keep=True)
def hash_color(text) -> QColor:
    hash_value = int(hash_string(text), 16) & 0xFFFFFF
    r = (hash_value & 0xFF0000) >> 16
    g = (hash_value & 0x00FF00) >> 8
    b = hash_value & 0x0000FF

    r = int(rescale(r, 0, 255, 100, 255))
    g = int(rescale(g, 0, 255, 100, 255))
    b = int(rescale(b, 0, 255, 100, 255))

    return QColor(r, g, b)


class CustomListWidgetItem(QListWidgetItem):
    def __init__(self, item_text: str, sub_text: str | None = None, parent=None):
        super(CustomListWidgetItem, self).__init__(parent)
        self.setText(item_text)
        self.subtext = sub_text
        self.color = self.hash_color()
        self.setData(Qt.ItemDataRole.UserRole + 1, self.color)
        self.setData(Qt.ItemDataRole.UserRole + 2, self.subtext)  # UserRole for subtext

    def hash_color(self):
        return hash_color(self.text())

    def mimeData(self):
        mime_data = QMimeData()
        d = {
            "type": "drag_tag",
            "tag": self.text(),
        }

        mime_data.setData("application/json", str_to_qbytearray(json.dumps(d)))
        return mime_data


class CustomDelegate(QStyledItemDelegate):
    signal_tag_renamed = pyqtSignal(str, str)

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.currentlyEditingIndex = QModelIndex()
        self.imageCache: Dict[Tuple[QModelIndex, QStyle.StateFlag, str, str, int, int], QImage] = (
            {}
        )  # Cache for storing pre-rendered images
        self.cache_size = 100

    def _remove_first_cache_item(self):
        key = None
        for key in self.imageCache.keys():
            break
        if key in self.imageCache:
            del self.imageCache[key]

    def add_to_cache(self, key, value):
        # logger.debug(f"Cache size {self.__class__.__name__}: {len(self.imageCache)}")
        if len(self.imageCache) + 1 > self.cache_size:
            self._remove_first_cache_item()

        self.imageCache[key] = value

    def renderHtmlToImage(self, index: QModelIndex, option: QStyleOptionViewItem, text: str, subtext: str):
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
        buttion_option.rect = QRect(0, 0, rectSize.width(), rectSize.height())
        buttion_option.state = QStyle.StateFlag.State_Enabled

        if option.state & QStyle.StateFlag.State_Selected:
            buttion_option.state |= QStyle.StateFlag.State_Sunken
        else:
            buttion_option.state |= QStyle.StateFlag.State_Raised

        color = QColor(index.data(Qt.ItemDataRole.UserRole + 1))  # Assuming color is stored in UserRole + 1
        buttion_option.palette.setColor(QPalette.ColorRole.Button, color)

        # Draw button-like background
        (QApplication.style() or QStyle()).drawControl(
            QStyle.ControlElement.CE_PushButton, buttion_option, painter
        )

        # Render HTML text
        self.draw_html_text(painter, text, subtext, buttion_option.rect, scale=1)

        painter.end()
        return image

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
        textHeightRatio = 0.6  # Allocate 60% of the rect height to the main text
        subtextHeightRatio = 0.4  # Remaining 40% for the subtext

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

        key = (
            index,
            option.state,
            text,
            subtext,
            option.rect.width(),
            option.rect.height(),
        )
        # Ensure there's an image rendered for this index
        if key not in self.imageCache:
            # Render and cache the item appearance
            self.add_to_cache(key, self.renderHtmlToImage(index, option, text, subtext))

        # Draw the cached image
        image = self.imageCache[key]
        if image:
            painter.drawImage(option.rect.topLeft(), image)

    def clearCache(self):
        """
        Clears the cached images. Call this method if you need to refresh the items.
        """
        self.imageCache.clear()

    def createEditor(self, parent, option: QStyleOptionViewItem, index: QModelIndex):
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


class DeleteButton(QPushButton):
    signal_delete_item = pyqtSignal(str)
    signal_addresses_dropped = pyqtSignal(AddressDragInfo)

    def __init__(self, *args, **kwargs):
        super(DeleteButton, self).__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        self.setIcon(icon)

    def dragEnterEvent(self, event: QDragEnterEvent | None):
        if not event:
            super().dragEnterEvent(event)
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            json_string = qbytearray_to_str(mime_data.data("application/json"))

            d = json.loads(json_string)
            logger.debug(f"dragEnterEvent: Got {d}")
            if d.get("type") == "drag_tag" or d.get("type") == "drag_addresses":
                event.acceptProposedAction()
                return

        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent | None):
        "this is just to hide/undide the button"
        logger.debug("Drag has left the delete button")

    def dropEvent(self, event: QDropEvent | None):
        super().dropEvent(event)
        if not event or event.isAccepted():
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            json_string = qbytearray_to_str(mime_data.data("application/json"))

            d = json.loads(json_string)
            logger.debug(f"dropEvent: Got {d}")
            if d.get("type") == "drag_tag":
                self.signal_delete_item.emit(d.get("tag"))
                event.acceptProposedAction()
                return
            if d.get("type") == "drag_addresses":
                drag_info = AddressDragInfo([None], d.get("addresses"))
                logger.debug(f"dropEvent: {drag_info}")
                self.signal_addresses_dropped.emit(drag_info)
                event.accept()
                return

        event.ignore()


class CustomListWidget(QListWidget):
    signal_tag_added = pyqtSignal(str)
    signal_tag_clicked = pyqtSignal(str)
    signal_tag_deleted = pyqtSignal(str)
    signal_tag_renamed = pyqtSignal(str, str)
    signal_addresses_dropped = pyqtSignal(AddressDragInfo)
    signal_start_drag = pyqtSignal(object)
    signal_stop_drag = pyqtSignal(object)

    def __init__(self, parent=None, enable_drag=True, immediate_release=True):
        super().__init__(parent)

        self.immediate_release = immediate_release

        delegate = CustomDelegate(self)
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
        self._drag_start_position = None

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

        item.color = item.hash_color()
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

    def setAllSelection(self, selected=True):
        for i in range(self.count()):
            item = self.item(i)
            if item:
                item.setSelected(selected)

    def mousePressEvent(self, event: QMouseEvent | None):
        if not event:
            super().mousePressEvent(event)
            return

        item = self.itemAt(event.pos())
        if item and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_position = event.pos()
            if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
                if item.isSelected():
                    self.setAllSelection(False)
                    return

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None):
        if event and event.button() == Qt.MouseButton.LeftButton:
            pass

        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None):
        if event and event.button() == Qt.MouseButton.LeftButton:
            # Perform actions that should happen after the mouse button is released
            # This could be updating the state of the widget, triggering signals, etc.

            item = self.itemAt(event.pos())
            if item is not None and item.isSelected():
                self.on_item_clicked(item)
                if self.immediate_release:
                    if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
                        self.setAllSelection(False)
                        return

        super().mouseReleaseEvent(event)

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

        self.signal_start_drag.emit(action)

        drag.exec(action)

        self.signal_stop_drag.emit(action)

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
        logger.debug("drop")
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

    def recreate(self, tags: List[str], sub_texts: Iterable[str | None] | None = None):
        # Store the texts of selected items
        selected_texts = [item.text() for item in self.selectedItems()]

        # Delete all items
        for i in reversed(range(self.count())):
            self.takeItem(i)

        # Add all items back
        cleaned_sub_texts = sub_texts if sub_texts else [None] * len(tags)
        for sub_text, tag in zip(cleaned_sub_texts, tags):
            self.add(tag, sub_text=sub_text)  # Assuming `self.add` correctly adds items

        # Re-select items based on stored texts
        for i in range(self.count()):
            item = self.item(i)
            if item and item.text() in selected_texts:
                item.setSelected(True)


class TagEditor(QWidget):
    def __init__(
        self,
        parent=None,
        tags: List[str] | None = None,
        sub_texts: Iterable[str | None] | None = None,
        tag_name="tag",
    ):
        super(TagEditor, self).__init__(parent)
        self.tag_name = tag_name
        self._layout = QVBoxLayout(self)

        self.input_field = QLineEdit()
        self.input_field.setClearButtonEnabled(True)
        self.input_field.returnPressed.connect(self.add_new_tag_from_input_field)

        self.delete_button = DeleteButton()
        self.delete_button.hide()

        self.list_widget = CustomListWidget(parent=self)
        self._layout.addWidget(self.input_field)
        self._layout.addWidget(self.delete_button)
        self._layout.addWidget(self.list_widget)
        self.list_widget.signal_start_drag.connect(self.show_delete_button)
        self.list_widget.signal_stop_drag.connect(self.hide_delete_button)
        self.list_widget.signal_addresses_dropped.connect(self.hide_delete_button)
        self.delete_button.signal_delete_item.connect(self.list_widget.delete_item)
        self.delete_button.signal_addresses_dropped.connect(self.hide_delete_button)

        self.setAcceptDrops(True)
        # TagEditor.updateUi  ensure that this is not overwritten in a child class
        TagEditor.updateUi(self)

        if tags:
            self.list_widget.recreate(tags, sub_texts=sub_texts)

    def updateUi(self):
        self.input_field.setPlaceholderText(self.default_placeholder_text())
        self.delete_button.setText(translate("tageditor", "Delete {name}").format(name=self.tag_name))

    def default_placeholder_text(self):
        return translate("tageditor", "Add new {name}").format(name=self.tag_name)

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

            logger.debug(f"show_delete_button")
            self.show_delete_button()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent | None):
        "this is just to hide/undide the button"
        if not event:
            super().dragLeaveEvent(event)
            return

        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            logger.debug("Drag operation left the TagEditor")
            self.hide_delete_button()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent | None):
        super().dropEvent(event)

        if not event or event.isAccepted():
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasFormat("application/json"):
            self.hide_delete_button()
            event.accept()
        else:
            event.ignore()

    def show_delete_button(self, *args):
        self.input_field.hide()
        self.delete_button.show()

    def hide_delete_button(self, *args):
        self.input_field.show()
        self.delete_button.hide()

    def add(self, new_tag: str, sub_text: str | None = None) -> Optional[CustomListWidgetItem]:
        if not self.tag_exists(new_tag):
            return self.list_widget.add(new_tag, sub_text=sub_text)
        return None

    def add_new_tag_from_input_field(self):
        new_tag = clean_tag(self.input_field.text())
        item = self.add(new_tag)
        if item:
            self.input_field.setPlaceholderText(self.default_placeholder_text())
        else:
            self.input_field.setPlaceholderText(
                translate("tageditor", "This {name} exists already.").format(name=self.tag_name)
            )
        self.input_field.clear()

    def tag_exists(self, tag: str):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.text() == tag:
                return True
        return False
