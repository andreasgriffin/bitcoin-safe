import logging
logger = logging.getLogger(__name__)
from PySide2.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QApplication

class PasswordQuestion(QDialog):
    def __init__(self, parent=None):
        super(PasswordQuestion, self).__init__(parent)

        self.setWindowTitle("Password Input")

        self.layout = QVBoxLayout(self)

        self.label = QLabel("Please enter your password:")
        self.layout.addWidget(self.label)

        self.password_input = QLineEdit(self)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.layout.addWidget(self.password_input)

        self.submit_button = QPushButton("Submit", self)
        self.submit_button.clicked.connect(self.accept)
        self.layout.addWidget(self.submit_button)

    def ask_for_password(self):
        if self.exec_() == QDialog.Accepted:
            return self.password_input.text()
        else:
            return None

if __name__ == "__main__":
    app = QApplication([])

    password_question = PasswordQuestion()
    password = password_question.ask_for_password()
    print(f"Entered password: {password}")
