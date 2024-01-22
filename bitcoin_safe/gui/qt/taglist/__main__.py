from PySide2.QtWidgets import QApplication, QVBoxLayout, QWidget

from .main import TagEditor

if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    main = QWidget()
    main_layout = QVBoxLayout(main)

    widget = TagEditor()
    # widget = CustomListWidget(enable_drag=False)
    widget.add("jgud", sub_text="876349 Sats")
    widget.add("jgu3d")
    widget.add("jg235ud")
    widget.add("jgu346d")

    main_layout.addWidget(widget)
    main.show()
    sys.exit(app.exec_())
