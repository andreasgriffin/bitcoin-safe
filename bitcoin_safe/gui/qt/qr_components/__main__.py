from PySide2.QtWidgets import *
from PySide2.QtCore import *
from PySide2.QtGui import *
from .quick_receive import ReceiveGroup, QuickReceive

import random


def generate_random_hex_color():
    """Generate a random hex color code."""
    random_color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
    return random_color


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    custom_widget = QuickReceive("Quick Receive")

    # Example usage
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(color, generate_random_hex_color(), color, color)
    )
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(color, generate_random_hex_color(), color, color)
    )
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(color, generate_random_hex_color(), color, color)
    )

    custom_widget.show()
    sys.exit(app.exec_())
