from PySide2.QtWidgets import QApplication, QWidget, QVBoxLayout, QSlider, QLabel
from PySide2.QtCore import Qt, QRectF
from PySide2.QtGui import QPainter, QColor

class CustomSlider(QWidget):
    def __init__(self, min_val=0, max_val=100, tick_interval=10, unit="BTC", label_text='', parent=None):
        super(CustomSlider, self).__init__(parent)
        self._unit = unit
        self._color_ranges = []
        self._label_text = label_text

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        self.slider.setTickInterval(tick_interval)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.valueChanged.connect(self.update_label)

        self.label = QLabel(parent)

        self.layout = QVBoxLayout(parent)        
        self.layout.setAlignment(Qt.AlignVCenter)
        self.layout.addWidget(self.slider)
        self.layout.addWidget(self.label)
        self.setLayout(self.layout)

        self.update_label(self.slider.value())

    @property
    def value(self):
        return self.slider.value()

    @value.setter
    def unit(self, value):
        self.slider.setValue(value)

    @property
    def unit(self):
        return self._unit

    @unit.setter
    def unit(self, value):
        self._unit = value

    @property
    def label_text(self):
        return self._label_text

    @label_text.setter
    def label_text(self, value):
        self._label_text = value

    @property
    def color_ranges(self):
        return self._color_ranges

    @color_ranges.setter
    def color_ranges(self, value):
        self._color_ranges = value

    @property
    def min_val(self):
        return self.slider.minimum()

    @min_val.setter
    def min_val(self, value):
        self.slider.setMinimum(value)

    @property
    def max_val(self):
        return self.slider.maximum()

    @max_val.setter
    def max_val(self, value):
        self.slider.setMaximum(value)

    @property
    def tick_interval(self):
        return self.slider.tickInterval()

    @tick_interval.setter
    def tick_interval(self, value):
        self.slider.setTickInterval(value)

    def update_label(self, value):        
        for range in self.color_ranges:
            if range[0] <= value <= range[1]:
                self.label.setText(f"{self.label_text}<font color='{range[2]}'>{value}</font> {self.unit}")
                return
        self.label.setText(f"{self.label_text}{value} {self.unit}")

    def add_color_range(self, min_val, max_val, color):
        self._color_ranges.append((min_val, max_val, color))




def main():
    app = QApplication([])

    widget = CustomSlider(min_val=0, max_val=70, tick_interval=10, unit="BTC", label_text='Amount: ')
    widget.add_color_range(20, 30, "#FFFFFF")
    widget.add_color_range(30, 35, "#FF00FF")
    widget.add_color_range(40, 60, "#FFFF11")
    widget.show()

    app.exec_()

if __name__ == "__main__":
    main()
