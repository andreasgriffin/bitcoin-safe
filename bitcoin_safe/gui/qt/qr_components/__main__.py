import random

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.qr_components.quick_receive import QuickReceive, ReceiveGroup

from ....signals import TypedPyQtSignalNo


def generate_random_hex_color() -> str:
    """Generate a random hex color code."""
    random_color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
    return random_color


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    class My(QObject):
        close_all_video_widgets: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    my = My()

    custom_widget = QuickReceive("Quick Receive")
    custom_widget.show()

    # Example usage
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(
            color,
            generate_random_hex_color(),
            color * 10,
            color * 10,
            close_all_video_widgets=my.close_all_video_widgets,
        )
    )
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(
            color,
            generate_random_hex_color(),
            color * 10,
            color * 10,
            close_all_video_widgets=my.close_all_video_widgets,
        )
    )
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(
            color,
            generate_random_hex_color(),
            color * 10,
            color * 10,
            close_all_video_widgets=my.close_all_video_widgets,
        )
    )

    sys.exit(app.exec())
