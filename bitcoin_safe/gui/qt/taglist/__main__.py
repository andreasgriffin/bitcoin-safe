from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from .main import CustomListWidget, TagEditor

if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    main = QWidget()
    main_layout = QVBoxLayout(main)

    widget = TagEditor()
    # widget = CustomListWidget(enable_drag=False)
    widget.add("jgud", sub_text="876349 Sats")
    widget.add("jgu3d", sub_text="876349 Sats")
    widget.add("jg235ud", sub_text="876349 Sats")
    widget.add("jgu346d", sub_text="876349 Sats")

    main_layout.addWidget(widget)

    l = CustomListWidget(main)
    l.add("jgud", sub_text="876349 Sats")
    l.add("jgu3d", sub_text="876349 Sats")
    l.add("jg235ud", sub_text="876349 Sats")
    l.add("jgu346d", sub_text="876349 Sats")
    main_layout.addWidget(l)

    main.show()
    sys.exit(app.exec())
