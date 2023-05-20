from .taglist import TagList
from typing import List

class CategoryList(TagList):
    def __init__(self, categories:List, parent=None, tag_name='category'):        
        super().__init__(parent, categories, tag_name)
        
        self.categories = categories
        
        self.list_widget.item_deleted.connect(self.on_delete)
        self.list_widget.item_added.connect(self.on_added)
        
    def on_added(self, item):
        if   item.text() not in self.categories:            
            self.categories.append(item.text())
        
    def on_delete(self, item):
        if item.text() in self.categories:
            idx = self.categories.index(item.text() )
            self.categories.pop(idx)
        
        