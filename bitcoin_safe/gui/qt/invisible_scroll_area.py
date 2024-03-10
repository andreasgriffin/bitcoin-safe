import uuid

from PyQt6.QtWidgets import QScrollArea, QWidget


class InvisibleScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.unique_id = uuid.uuid4()

        self.setObjectName(f"{self.unique_id}")
        self.setStyleSheet(f"#{self.unique_id}" + " { background: transparent; border: none; }")

        self.content_widget = QWidget()
        self.content_widget.setObjectName(f"{self.unique_id}_content")
        self.content_widget.setStyleSheet(
            f"#{self.unique_id}_content" + " { background: transparent; border: none; }"
        )

        self.setWidget(self.content_widget)
