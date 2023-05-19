from PySide2.QtWidgets import *
from PySide2.QtCore import *
from PySide2.QtGui import *

def rescale(value, old_min, old_max, new_min, new_max):
    return (value - old_min) / (old_max - old_min) * (new_max - new_min) + new_min

class CustomListWidgetItem(QListWidgetItem):
    def __init__(self, item_text, parent=None):
        super(CustomListWidgetItem, self).__init__(parent)
        self.setText(item_text)
        self.color = self.hash_color()
        self.setData(Qt.UserRole + 1, self.color)

    def hash_color(self):
        hash_value = hash(self.text()) & 0xffffff
        r = (hash_value & 0xff0000) >> 16
        g = (hash_value & 0x00ff00) >> 8
        b = hash_value & 0x0000ff

        r = int(rescale(r, 0, 255, 100, 255))
        g = int(rescale(g, 0, 255, 100, 255))
        b = int(rescale(b, 0, 255, 100, 255))

        return QColor(r, g, b)
    

class CustomDelegate(QStyledItemDelegate):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.currentlyEditingIndex = QModelIndex()        
    
    def paint(self, painter: QPainter, option, index):        
        color = QColor(index.data(Qt.UserRole + 1))
        painter.save()
        if option.state & QStyle.State_Selected:
            # If the item is selected, change its appearance
            painter.setPen(QPen(color.darker(200), 2))  # outline
            painter.setBrush(color)
        else:
            # If the item is not selected, use the original appearance
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)

        rect = option.rect.adjusted(0, 0, 0, -5)
        painter.drawRoundedRect(rect, 5, 5)
        painter.restore()

        if index != self.currentlyEditingIndex:
            # Draw the text separately, to prevent it from being overpainted by the brush
            painter.drawText(rect, Qt.AlignCenter, index.data())

        # Do not call the base class paint() method, since we've done all the painting


    def sizeHint(self, option, index):
        # Increase the height by 5 to compensate for the reduced rectangle height in paint()
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + 5)
        return size



    def createEditor(self, parent, option, index):
        self.currentlyEditingIndex = index
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignCenter)
        editor.setStyleSheet("""
            background: transparent;
            border: none;
        """)
        return editor

    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.EditRole)
        editor.setText(value)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)
        self.currentlyEditingIndex = QModelIndex()


class DeleteButton(QPushButton):
    delete_item = Signal(str)

    def __init__(self, *args, **kwargs):
        super(DeleteButton, self).__init__(*args, **kwargs)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().text():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.delete_item.emit(event.mimeData().text())
        event.acceptProposedAction()


class CustomListWidget(QListWidget):
    item_selected = Signal(object)
    item_deleted = Signal(object)
    item_renamed = Signal(object, object)

    def __init__(self, add_tag_field, delete_button, parent=None):
        super(CustomListWidget, self).__init__(parent)
        self.add_tag_field = add_tag_field
        self.delete_button = delete_button

        self.setItemDelegate(CustomDelegate(self))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.itemClicked.connect(self.on_item_clicked)
        self.itemChanged.connect(self.on_item_changed)  # new


        self.setMouseTracking(True)
        self._drag_start_position = None

        self.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
            }
            QListWidget::item {
                border-radius: 5px;
                margin: 3px;
            }
            QListWidget::item:selected {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #cccccc, stop:1 #b3b3b3);
                border: 1px solid black;
            }
            """)

    def add_item(self, item_text) -> CustomListWidgetItem:
        item = CustomListWidgetItem(item_text)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.addItem(item)
        return item

    def on_item_clicked(self, item):
        self.item_selected.emit(item)
        # print( [item.text() for item in self.selectedItems()])        

    def on_item_changed(self, item):  # new

        item.color = item.hash_color()
        item.setData(Qt.UserRole + 1, item.color)

        # Here you can handle the renaming event
        # For now, we will just print the new item text
        # print(f"Item text has been changed to {item.text()}")


    def rename_selected(self, new_text):
        for item in self.selectedItems():
            old_text = item.text()
            item.setText(new_text)
            item.setBackground()
            self.item_renamed.emit(old_text, new_text)



    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_position = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self._drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
        self.startDrag(Qt.MoveAction)
        
    def startDrag(self, action):
        item = self.currentItem()
        rect = self.visualItemRect(item)
        mime_data = QMimeData()
        mime_data.setText(item.text())
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        pixmap = self.viewport().grab(rect)
        cursor_pos = self.mapFromGlobal(QCursor.pos())
        drag.setPixmap(pixmap)
        drag.setHotSpot(cursor_pos - rect.topLeft())
        self.add_tag_field.hide()
        self.delete_button.show()
        drag.exec_(action)

        result = drag.exec_(action)
            
        self.handle_drag_end()

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.add_tag_field.show()
        self.delete_button.hide()


    def handle_drag_end(self):
        self.add_tag_field.show()
        self.delete_button.hide()
        
    def delete_item(self, item_text):
        for i in range(self.count()):
            item = self.item(i)
            if item.text() == item_text:
                self.takeItem(i)
                self.item_deleted.emit(item)
                break
        
    def get_items(self) -> CustomListWidgetItem:
        for i in range(self.count()):
            yield self.item(i)

    def get_item_texts(self) -> str:
        for item  in self.get_items():
            yield item.text()


class TagList(QWidget):
    default_placeholder_text = 'Add new tag'
    
    def __init__(self, parent=None, tags=None):
        super(TagList, self).__init__(parent)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(self.default_placeholder_text)
        self.input_field.returnPressed.connect(self.add_new_tag_from_input_field)

        self.delete_button = DeleteButton('Delete item', self)
        self.delete_button.hide()

        self.list_widget = CustomListWidget(self.input_field, self.delete_button)
        self.layout.addWidget(self.input_field)
        self.layout.addWidget(self.delete_button)
        self.layout.addWidget(self.list_widget)

        self.delete_button.delete_item.connect(self.list_widget.delete_item)
        
        if tags:
            for tag in tags:
                self.list_widget.add_item(tag) 
        
        
    def add(self, new_tag) -> CustomListWidgetItem:
        if not self.tag_exists(new_tag):
            return self.list_widget.add_item(new_tag) 
        
    
    def add_new_tag_from_input_field(self):
        new_tag = self.input_field.text()
        item = self.add(new_tag)
        if item:
            self.input_field.setPlaceholderText(self.default_placeholder_text)
        else:
            self.input_field.setPlaceholderText('This tag exists already.')
        self.input_field.clear()

    def tag_exists(self, tag):
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).text() == tag:
                return True
        return False
    
    
if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    widget = TagList()
    widget.show()
    sys.exit(app.exec_())