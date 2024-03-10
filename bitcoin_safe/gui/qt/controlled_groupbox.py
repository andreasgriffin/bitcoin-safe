from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QGroupBox, QVBoxLayout, QWidget


class ControlledGroupbox(QWidget):
    def __init__(self, checkbox_text="Enable GroupBox", groupbox_text="", enabled=True):
        super().__init__()

        self.setLayout(QVBoxLayout())

        # Create the checkbox and add it to the layout
        self.checkbox = QCheckBox(checkbox_text, self)
        self.checkbox.setChecked(enabled)  # Set the initial state based on the 'enabled' argument
        self.layout().addWidget(self.checkbox)

        # Create the groupbox
        self.groupbox = QGroupBox(groupbox_text, self)

        # Add the groupbox to the main widget's layout
        self.layout().addWidget(self.groupbox)

        # Set the initial enabled state of the groupbox
        self.groupbox.setEnabled(enabled)
        self.checkbox.stateChanged.connect(self.toggleGroupBox)

    def toggleGroupBox(self, value):
        """Toggle the enabled state of the groupbox based on the checkbox."""
        self.groupbox.setEnabled(value == Qt.CheckState.Checked.value)


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = ControlledGroupbox(enabled=False)  # Example with the groupbox initially disabled
    window.show()
    sys.exit(app.exec())
