from PySide2.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ExtendedTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_top_right_widget()

        # Update QLineEdit position when the widget is resized
        self.resizeEvent = self.onResizeEvent

    def set_top_right_widget(self, top_right_widget: QWidget = None, target_width=150):
        self.top_right_widget = top_right_widget
        self.target_width = target_width

        # Adjust the size and position of the QLineEdit
        if self.top_right_widget:
            self.top_right_widget.setParent(self)
            self.top_right_widget.setFixedWidth(self.target_width)

    def showEvent(self, event):
        self.updateLineEditPosition()
        super(ExtendedTabWidget, self).showEvent(event)

    def updateLineEditPosition(self):
        tabBarRect = self.tabBar().geometry()
        availableWidth = self.width()

        line_width = availableWidth // 2 if availableWidth < 2 * self.target_width else self.target_width

        self.tabBar().setMaximumWidth(availableWidth - line_width - 3)

        # Update QLineEdit geometry
        lineEditX = self.width() - line_width - 2
        if self.top_right_widget:
            self.top_right_widget.setGeometry(lineEditX, tabBarRect.y(), line_width, tabBarRect.height() - 5)
            self.top_right_widget.setFixedWidth(line_width)  # Ensure fixed width is maintained

    def onResizeEvent(self, event):
        self.updateLineEditPosition()
        super().resizeEvent(event)


# Usage example
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    edit = QLineEdit(f"Ciiiiii")
    tabWidget = ExtendedTabWidget()

    # Add tabs with larger widgets
    for i in range(3):
        widget = QWidget()
        layout = QVBoxLayout()
        label = QLabel(f"Content for Tab {i+1}")
        textEdit = QTextEdit(f"This is a larger widget in Tab {i+1}.")
        layout.addWidget(label)
        layout.addWidget(textEdit)
        widget.setLayout(layout)
        tabWidget.addTab(widget, f"Tab {i+1}")

    tabWidget.show()
    sys.exit(app.exec_())
