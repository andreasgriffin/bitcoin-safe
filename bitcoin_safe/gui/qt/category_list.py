import logging

logger = logging.getLogger(__name__)

from .taglist import TagEditor, CustomListWidget
from typing import List
from PySide2.QtCore import Signal
from ...signals import Signals, UpdateFilter
from .taglist import hash_color, AddressDragInfo
from PySide2.QtGui import QBrush, QColor, QPainterPath, QMouseEvent


class CategoryList(CustomListWidget):
    def __init__(
        self,
        categories: List,
        signals: Signals,
        get_sub_texts=None,
        parent=None,
        tag_name="category",
        immediate_release=True,
    ):
        super().__init__(parent, enable_drag=False, immediate_release=immediate_release)

        self.categories = categories
        self.get_sub_texts = get_sub_texts
        self.signals = signals
        self.signals.category_updated.connect(self.refresh)
        self.signals.utxos_updated.connect(self.refresh)
        self.refresh(UpdateFilter(refresh_all=True))

    def refresh(self, update_filter: UpdateFilter):
        self.recreate(self.categories, sub_texts=self.get_sub_texts())

    @classmethod
    def color(cls, category):
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)


class CategoryEditor(TagEditor):
    def __init__(
        self,
        categories: List,
        signals: Signals,
        get_sub_texts=None,
        parent=None,
        tag_name="category",
    ):
        sub_texts = get_sub_texts() if get_sub_texts else None
        super().__init__(parent, categories, tag_name=tag_name, sub_texts=sub_texts)

        self.categories = categories
        self.get_sub_texts = get_sub_texts
        self.signals = signals
        self.signals.category_updated.connect(self.refresh)
        self.signals.import_bip329_labels.connect(self.refresh)

        self.list_widget.signal_tag_deleted.connect(self.on_delete)
        self.list_widget.signal_tag_added.connect(self.on_added)

    def on_added(self, category):
        if not category or category in self.categories:
            return

        self.categories.append(category)
        self.signals.category_updated.emit(UpdateFilter(categories=[category]))

    def on_delete(self, category):
        if category not in self.categories:
            return
        idx = self.categories.index(category)
        self.categories.pop(idx)
        self.signals.category_updated.emit(UpdateFilter(categories=[category]))

    def refresh(self, update_filter: UpdateFilter):
        self.list_widget.recreate(self.categories, sub_texts=self.get_sub_texts())

    @classmethod
    def color(cls, category):
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)
