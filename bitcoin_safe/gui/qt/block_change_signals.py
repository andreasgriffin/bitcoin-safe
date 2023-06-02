
import logging
logger = logging.getLogger(__name__)

class BlockChangesSignals:
    def __init__(self, own_widgets=None, sub_instances=None):
        self.own_widgets = own_widgets if own_widgets else []
        self.sub_instances = sub_instances if sub_instances else []
        
        self.widgets = self.own_widgets
        for sub_change_signal in self.sub_instances:
            self.widgets += sub_change_signal.widgets

    def __enter__(self):
        for widget in self.widgets:
            widget.blockSignals(True)

    def __exit__(self, exc_type, exc_value, traceback):
        for widget in self.widgets:
            widget.blockSignals(False)
        