import logging
logger = logging.getLogger(__name__)

from .taglist import TagEditor, CustomListWidget
from typing import List
from ...signals import Signals, Signal
from .taglist import hash_color
from PySide2.QtGui import QBrush, QColor, QPainterPath, QMouseEvent




class CategoryList(CustomListWidget):
    def __init__(self, categories:List, signals:Signals, get_sub_texts=None, parent=None, tag_name='category'):   
        super().__init__(parent, enable_drag=False)
        
        self.categories = categories
        self.get_sub_texts = get_sub_texts
        self.signals = signals
        self.signals.category_updated.connect(self.refresh)
        
        self.refresh()
            
    def refresh(self):
        self.recreate(self.categories, sub_texts=self.get_sub_texts())
        
    @classmethod
    def color(cls, category):
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)
    
    
    
  
  
  
class CategoryEditor(TagEditor):
    def __init__(self, categories:List, signals:Signals, get_sub_texts=None, parent=None, tag_name='category'):   
        sub_texts = get_sub_texts() if get_sub_texts else None
        super().__init__(parent, categories, tag_name=tag_name, sub_texts=sub_texts)
        
        self.categories = categories
        self.get_sub_texts = get_sub_texts
        self.signals = signals
        self.signals.category_updated.connect(self.refresh)
        
        self.list_widget.item_deleted.connect(self.on_delete)
        self.list_widget.item_added.connect(self.on_added)
    

    def on_added(self, item):
        if  item.text()  in self.categories:            
            return
        self.categories.append(item.text())
        self.signals.category_updated()
        
    def on_delete(self, item):
        if item.text() not in self.categories:
            return
        idx = self.categories.index(item.text() )
        self.categories.pop(idx)
        self.signals.category_updated()
                
    def refresh(self):
        self.list_widget.recreate(self.categories, sub_texts=self.get_sub_texts())
        
    @classmethod
    def color(cls, category):
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)
    
    
    
    