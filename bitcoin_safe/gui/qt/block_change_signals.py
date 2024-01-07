import logging
from typing import List, Union
from PySide2.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QGridLayout,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


class BlockChangesSignals:
    def __init__(self, widgets: List[QWidget]) -> None:
        self.widgets: List[QWidget] = widgets

    def _collect_widgets_in_layout(self, layout: Union[QHBoxLayout, QVBoxLayout, QGridLayout]):
        """Recursively collect all widgets in a given layout."""
        widgets = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget():
                widgets.append(item.widget())
                # Check if the widget has a layout with more widgets
                if item.widget().layout():
                    widgets.extend(self._collect_widgets_in_layout(item.widget().layout()))
        return widgets

    def all_widgets(self) -> List[QWidget]:
        l = []
        for widget in self.widgets:
            l += self._collect_widgets_in_layout(widget.layout())
        return l

    def __enter__(self):
        for widget in self.all_widgets():
            widget.blockSignals(True)

    def __exit__(self, exc_type, exc_value, traceback):
        for widget in self.all_widgets():
            widget.blockSignals(False)
