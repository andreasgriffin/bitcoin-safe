import logging

from numpy import spacing

logger = logging.getLogger(__name__)

from PySide2.QtWidgets import *
from PySide2.QtCore import *
from PySide2.QtGui import *
import json
import hashlib
from typing import List


def clean_tag(tag) -> str:
    return tag.strip().capitalize()


class AddressDragInfo:
    def __init__(self, tags, addresses) -> None:
        self.tags = tags
        self.addresses = addresses

    def __repr__(self) -> str:
        return f"AddressDragInfo({self.tags}, {self.addresses})"


def hash_string(text):
    return hashlib.sha256(text.encode()).hexdigest()


def rescale(value, old_min, old_max, new_min, new_max):
    return (value - old_min) / (old_max - old_min) * (new_max - new_min) + new_min


def hash_color(text):
    hash_value = int(hash_string(text), 16) & 0xFFFFFF
    r = (hash_value & 0xFF0000) >> 16
    g = (hash_value & 0x00FF00) >> 8
    b = hash_value & 0x0000FF

    r = int(rescale(r, 0, 255, 100, 255))
    g = int(rescale(g, 0, 255, 100, 255))
    b = int(rescale(b, 0, 255, 100, 255))

    return QColor(r, g, b)


class CustomListWidgetItem(QListWidgetItem):
    def __init__(self, item_text, sub_text=None, parent=None):
        super(CustomListWidgetItem, self).__init__(parent)
        self.setText(item_text)
        self.subtext = sub_text
        self.color = self.hash_color()
        self.setData(Qt.UserRole + 1, self.color)
        self.setData(Qt.UserRole + 2, self.subtext)  # UserRole for subtext

    def hash_color(self):
        return hash_color(self.text())

    def mimeData(self):
        mime_data = QMimeData()
        d = {
            "type": "drag_tag",
            "tag": self.text(),
        }

        json_string = json.dumps(d).encode()
        mime_data.setData("application/json", json_string)
        return mime_data


class CustomDelegate(QStyledItemDelegate):
    signal_tag_renamed = Signal(object, object)

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.currentlyEditingIndex = QModelIndex()

    def paint(self, painter: QPainter, option, index):
        color = QColor(index.data(Qt.UserRole + 1))
        painter.save()

        rect = option.rect

        # Draw as a button
        button_style = QStyleOptionButton()
        button_style.rect = rect
        button_style.palette.setColor(QPalette.Button, color)
        button_style.state = QStyle.State_Enabled

        if option.state & QStyle.State_Selected:
            # button_style.palette.setColor(QPalette.Button, color.darker(200))
            button_style.state |= QStyle.State_Sunken
        else:
            button_style.state |= QStyle.State_Raised

        QApplication.style().drawControl(QStyle.CE_PushButton, button_style, painter)

        # Draw the text and subtext
        text = index.data()
        subtext = index.data(Qt.UserRole + 2)

        height_split = 3.5 / 6 if subtext else 1
        rectText = QRect(
            rect.left(), rect.top(), rect.width(), rect.height() * height_split
        )
        rectSubtext = QRect(
            rect.left(),
            rect.top() + rect.height() * height_split,
            rect.width(),
            rect.height() * (1 - height_split),
        )

        if index != self.currentlyEditingIndex:
            if subtext:
                painter.drawText(rectText, Qt.AlignBottom | Qt.AlignHCenter, text)
                # Set a smaller font size for the subtext
                font = painter.font()
                font.setPointSize(
                    font.pointSize() * 0.8
                )  # Adjust this value to get the desired font size
                painter.setFont(font)
                painter.drawText(rectSubtext, Qt.AlignTop | Qt.AlignHCenter, subtext)
                painter.setFont(QFont())  # Reset to the default font
            else:
                painter.drawText(rectText, Qt.AlignCenter, text)

        painter.restore()

    # def sizeHint(self, option, index):
    #     # Increase the height by 5 to compensate for the reduced rectangle height in paint()
    #     size = super().sizeHint(option, index)
    #     size.setHeight(size.height() + 15)
    #     return size

    def createEditor(self, parent, option, index):
        self.currentlyEditingIndex = index
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignCenter)
        editor.setStyleSheet(
            """
            background: transparent;
            border: none;
        """
        )
        return editor

    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.EditRole)
        editor.setText(value)

    def setModelData(self, editor, model, index):
        old_value = index.model().data(index, Qt.EditRole)
        new_value = clean_tag(editor.text())

        model.setData(index, editor.text(), Qt.EditRole)
        self.currentlyEditingIndex = QModelIndex()

        self.signal_tag_renamed.emit(old_value, new_value)


class DeleteButton(QPushButton):
    signal_delete_item = Signal(str)
    signal_addresses_dropped = Signal(AddressDragInfo)

    def __init__(self, *args, **kwargs):
        super(DeleteButton, self).__init__(*args, **kwargs)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/json"):
            data_bytes = event.mimeData().data("application/json")
            json_string = bytes(data_bytes).decode()  # convert bytes to string

            d = json.loads(json_string)
            logger.debug(f"dragEnterEvent: Got {d}")
            if d.get("type") == "drag_tag" or d.get("type") == "drag_addresses":
                event.acceptProposedAction()
                return

        event.ignore()

    def dragLeaveEvent(self, event):
        "this is just to hide/undide the button"
        logger.debug("Drag has left the delete button")

    def dropEvent(self, event):
        super().dropEvent(event)
        if event.isAccepted():
            return

        if event.mimeData().hasFormat("application/json"):
            data_bytes = event.mimeData().data("application/json")
            json_string = bytes(data_bytes).decode()  # convert bytes to string

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
    signal_tag_added = Signal(str)
    signal_tag_clicked = Signal(str)
    signal_tag_deleted = Signal(str)
    signal_tag_renamed = Signal(object, object)
    signal_addresses_dropped = Signal(AddressDragInfo)
    signal_start_drag = Signal(object)
    signal_stop_drag = Signal(object)

    def __init__(self, parent=None, enable_drag=True, immediate_release=True):
        super().__init__(parent)

        self.immediate_release = immediate_release

        delegate = CustomDelegate(self)
        delegate.signal_tag_renamed.connect(self.signal_tag_renamed)
        self.setItemDelegate(delegate)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
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

    def add(self, item_text, sub_text=None) -> CustomListWidgetItem:
        item = CustomListWidgetItem(item_text, sub_text=sub_text)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.addItem(item)
        self.signal_tag_added.emit(item_text)
        return item

    def on_item_clicked(self, item):
        self.signal_tag_clicked.emit(item.text())
        # print( [item.text() for item in self.selectedItems()])

    def on_item_changed(self, item):  # new

        item.color = item.hash_color()
        item.setData(Qt.UserRole + 1, item.color)

        # Here you can handle the renaming event
        # For now, we will just print the new item text
        # print(f"Item text has been changed to {item.text()}")

    def get_selected(self) -> List[str]:
        return [item.text() for item in self.selectedItems()]

    def rename_selected(self, new_text):
        for item in self.selectedItems():
            old_text = item.text()
            item.setText(new_text)
            item.setBackground()

    def setAllSelection(self, selected=True):
        for i in range(self.count()):
            item = self.item(i)
            item.setSelected(selected)

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item is None:
            # Click is on empty space, do nothing
            return
        else:
            if event.button() == Qt.LeftButton:
                self._drag_start_position = event.pos()
                if not (QApplication.keyboardModifiers() & Qt.ControlModifier):
                    if item.isSelected():
                        self.setAllSelection(False)
                        return

            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            pass

        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Perform actions that should happen after the mouse button is released
            # This could be updating the state of the widget, triggering signals, etc.

            item = self.itemAt(event.pos())
            if item is not None and item.isSelected():
                self.on_item_clicked(item)
                if self.immediate_release:
                    if not (QApplication.keyboardModifiers() & Qt.ControlModifier):
                        self.setAllSelection(False)
                        return

        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (
            event.pos() - self._drag_start_position
        ).manhattanLength() < QApplication.startDragDistance():
            return
        if self.dragEnabled():
            self.startDrag(Qt.MoveAction)

    def startDrag(self, action):
        item = self.currentItem()
        rect = self.visualItemRect(item)

        drag = QDrag(self)
        drag.setMimeData(item.mimeData())

        pixmap = self.viewport().grab(rect)
        cursor_pos = self.mapFromGlobal(QCursor.pos())
        drag.setPixmap(pixmap)
        drag.setHotSpot(cursor_pos - rect.topLeft())
        self.signal_start_drag.emit(action)

        result = drag.exec_(action)

        self.signal_stop_drag.emit(action)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/json"):
            # print('accept')
            # tag = self.itemAt(event.pos())

            data_bytes = event.mimeData().data("application/json")
            json_string = bytes(data_bytes).decode()  # convert bytes to string
            # dropped_addresses = json.loads(json_string)
            # print(f'drag enter {dropped_addresses,   tag.text()}')
            logger.debug(f"dragEnterEvent: {json_string}")

            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        logger.debug("drop")
        super().dropEvent(event)
        if event.isAccepted():
            return

        if event.mimeData().hasFormat("application/json"):
            tag = self.itemAt(event.pos())

            data_bytes = event.mimeData().data("application/json")
            json_string = bytes(data_bytes).decode()  # convert bytes to string

            d = json.loads(json_string)
            if d.get("type") == "drag_addresses":
                if tag is not None:
                    drag_info = AddressDragInfo([tag.text()], d.get("addresses"))
                    logger.debug(f"dropEvent: {drag_info}")
                    self.signal_addresses_dropped.emit(drag_info)
                event.accept()
                return

        event.ignore()

    def delete_item(self, item_text):
        for i in range(self.count()):
            item = self.item(i)
            if item.text() == item_text:
                self.takeItem(i)
                self.signal_tag_deleted.emit(item_text)
                break

    def get_items(self) -> CustomListWidgetItem:
        for i in range(self.count()):
            yield self.item(i)

    def get_item_texts(self) -> str:
        for item in self.get_items():
            yield item.text()

    def recreate(self, tags, sub_texts=None):
        # Store the texts of selected items
        selected_texts = [item.text() for item in self.selectedItems()]

        # Delete all items
        for i in reversed(range(self.count())):
            self.takeItem(i)

        # Add all items back
        sub_texts = sub_texts if sub_texts else [None] * len(tags)
        for sub_text, tag in zip(sub_texts, tags):
            self.add(tag, sub_text=sub_text)  # Assuming `self.add` correctly adds items

        # Re-select items based on stored texts
        for i in range(self.count()):
            item = self.item(i)
            if item.text() in selected_texts:
                item.setSelected(True)


class TagEditor(QWidget):
    def __init__(self, parent=None, tags=None, sub_texts=None, tag_name="tag"):
        super(TagEditor, self).__init__(parent)
        self.tag_name = tag_name
        self.default_placeholder_text = f"Add new {self.tag_name}"
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.input_field = QLineEdit()
        self.input_field.setClearButtonEnabled(True)
        self.input_field.setPlaceholderText(self.default_placeholder_text)
        self.input_field.returnPressed.connect(self.add_new_tag_from_input_field)

        self.delete_button = DeleteButton(f"Delete {self.tag_name}", self)
        self.delete_button.hide()

        self.list_widget = CustomListWidget(parent=self)
        self.layout.addWidget(self.input_field)
        self.layout.addWidget(self.delete_button)
        self.layout.addWidget(self.list_widget)
        self.list_widget.signal_start_drag.connect(self.show_delete_button)
        self.list_widget.signal_stop_drag.connect(self.hide_delete_button)
        self.list_widget.signal_addresses_dropped.connect(self.hide_delete_button)
        self.delete_button.signal_delete_item.connect(self.list_widget.delete_item)
        self.delete_button.signal_addresses_dropped.connect(self.hide_delete_button)

        self.setAcceptDrops(True)

        if tags:
            self.list_widget.recreate(tags, sub_texts=sub_texts)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/json"):
            # print('accept')
            # tag = self.itemAt(event.pos())

            data_bytes = event.mimeData().data("application/json")
            json_string = bytes(data_bytes).decode()  # convert bytes to string
            # dropped_addresses = json.loads(json_string)
            # print(f'drag enter {dropped_addresses,   tag.text()}')
            logger.debug(f"dragEnterEvent: {json_string}")

            event.acceptProposedAction()

            logger.debug(f"show_delete_button")
            self.show_delete_button()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        "this is just to hide/undide the button"
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            logger.debug("Drag operation left the TagEditor")
            self.hide_delete_button()
        else:
            event.ignore()

    def dropEvent(self, event):
        super().dropEvent(event)
        if event.isAccepted():
            return

        if event.mimeData().hasFormat("application/json"):
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

    def add(self, new_tag, sub_text=None) -> CustomListWidgetItem:
        if not self.tag_exists(new_tag):
            return self.list_widget.add(new_tag, sub_text=sub_text)

    def add_new_tag_from_input_field(self):
        new_tag = clean_tag(self.input_field.text())
        item = self.add(new_tag)
        if item:
            self.input_field.setPlaceholderText(self.default_placeholder_text)
        else:
            self.input_field.setPlaceholderText(f"This {self.tag_name} exists already.")
        self.input_field.clear()

    def tag_exists(self, tag):
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).text() == tag:
                return True
        return False
