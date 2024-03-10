import logging
from typing import List, Set

from PyQt6.QtWidgets import QTabWidget, QWidget

logger = logging.getLogger(__name__)


class BlockChangesSignals:
    def __init__(self, widgets: List[QWidget]) -> None:
        self.widgets: List[QWidget] = widgets

    def _collect_sub_widget(self, widget: QWidget):
        """Recursively collect all widgets in a given layout."""
        widgets = []
        if isinstance(widget, QTabWidget):
            widgets += self._collect_widgets_in_tab(widget)
        elif hasattr(widget, "layout") and widget.layout():
            layout = widget.layout()
            for i in range(layout.count()):
                item = layout.itemAt(i)
                # in pyqt6, it turns out that bool(QComboBox) == False, but True for other widgets
                if isinstance(item.widget(), QWidget):
                    widgets.append(item.widget())
                    widgets += self._collect_sub_widget(item.widget())
        return widgets

    def _collect_widgets_in_tab(self, tab_widget: QTabWidget):
        """Recursively collect all widgets in a QTabWidget."""
        widgets = []
        for index in range(tab_widget.count()):
            tab_page = tab_widget.widget(index)
            if tab_page.layout():
                widgets += self._collect_sub_widget(tab_page)
        return widgets

    def all_widgets(self) -> Set[QWidget]:
        l = []
        for widget in self.widgets:
            l += self._collect_sub_widget(widget)
            if isinstance(widget, QTabWidget):
                l += self._collect_widgets_in_tab(widget)
        return set(l)

    def __enter__(self):
        for widget in self.all_widgets():
            widget.blockSignals(True)

    def __exit__(self, exc_type, exc_value, traceback):
        for widget in self.all_widgets():
            widget.blockSignals(False)
