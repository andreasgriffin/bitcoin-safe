from .taglist import TagList
from typing import List
from ...signals import Signal
from .taglist import hash_color
from PySide2.QtGui import QBrush, QColor, QPainterPath, QMouseEvent


class CategoryList(TagList):
    def __init__(self, categories:List, parent=None, tag_name='category'):        
        super().__init__(parent, categories, tag_name)
        
        self.categories = categories
        
        self.list_widget.item_deleted.connect(self.on_delete)
        self.list_widget.item_added.connect(self.on_added)
        self.signal_addresses_dropped = Signal('signal_addresses_dropped')
        self.list_widget.signal_addresses_dropped.connect(self.signal_addresses_dropped)
        
    def on_added(self, item):
        if   item.text() not in self.categories:            
            self.categories.append(item.text())
        
    def on_delete(self, item):
        if item.text() in self.categories:
            idx = self.categories.index(item.text() )
            self.categories.pop(idx)
        
    def refresh(self):
        self.recreate(self.categories)

    @classmethod
    def color(cls, category):
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)