import logging

logger = logging.getLogger(__name__)

import sys
from datetime import datetime, timezone

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDateTimeEdit,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class DateTimePicker(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.dateTimeEdit = QDateTimeEdit(self)
        self.dateTimeEdit.setCalendarPopup(True)

        # Set the QDateTimeEdit to the current date and time
        self.dateTimeEdit.setDateTime(QDateTime.currentDateTime())

        layout = QVBoxLayout()
        layout.addWidget(self.dateTimeEdit)
        self.setLayout(layout)

    def print_time(self):
        # Convert QDateTime to Python datetime object
        local_datetime = self.get_datetime()

        # Assuming the local_datetime is naive (no timezone information),
        # Convert it to UTC
        utc_datetime = local_datetime.astimezone(timezone.utc)
        print("UTC Time:", utc_datetime)

    def get_datetime(self) -> datetime:
        return self.dateTimeEdit.dateTime().toPython()


class CheckBoxGroupBox(QWidget):
    def __init__(self, enabled=True):
        super().__init__()
        # Create the checkbox
        self.checkbox = QCheckBox()
        self.checkbox.stateChanged.connect(self.toggleGroupBox)
        self.checkbox.setStyleSheet("margin-bottom: 0px;")  # Adjust margin as needed

        # Create the group box
        self.groupBox = QGroupBox()
        groupBoxLayout = QVBoxLayout()

        self.groupBox.setLayout(groupBoxLayout)

        # Arrange the checkbox and group box in a layout
        layout = QVBoxLayout()
        layout.addWidget(self.checkbox)
        layout.addWidget(self.groupBox)
        self.setLayout(layout)
        self.toggleGroupBox(self.checkbox.checkState())

    def toggleGroupBox(self, state: Qt.CheckState):
        # Enable or disable the group box based on the checkbox state
        self.groupBox.setEnabled(state == Qt.CheckState.Checked)


class nLocktimePicker(CheckBoxGroupBox):
    def __init__(self) -> None:
        super().__init__()

        self.checkbox.setText("Set nLockTime")

        label = QLabel(
            'Set the minimum time (<a href="https://learn.saylor.org/mod/book/view.php?id=36369&chapterid=19000">Median-Time-Past</a>) the transaction can be included in a block. See: <a href="https://learn.saylor.org/mod/book/view.php?id=36369&chapterid=18994">nLocktime</a>'
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)  # Enable opening links
        label.setWordWrap(True)
        self.groupBox.layout().addWidget(label)

        self.nlocktime_picker = DateTimePicker()
        self.groupBox.layout().addWidget(self.nlocktime_picker)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = nLocktimePicker()
    window.show()
    sys.exit(app.exec())
