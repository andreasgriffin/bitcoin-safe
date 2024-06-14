import random

from PyQt6.QtWidgets import QApplication

from .quick_receive import QuickReceive, ReceiveGroup


def generate_random_hex_color() -> str:
    """Generate a random hex color code."""
    random_color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
    return random_color


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    custom_widget = QuickReceive("Quick Receive")

    # Example usage
    color = generate_random_hex_color()
    custom_widget.add_box(ReceiveGroup(color, generate_random_hex_color(), color * 10, color * 10))
    color = generate_random_hex_color()
    custom_widget.add_box(ReceiveGroup(color, generate_random_hex_color(), color * 10, color * 10))
    color = generate_random_hex_color()
    custom_widget.add_box(ReceiveGroup(color, generate_random_hex_color(), color * 10, color * 10))

    custom_widget.show()
    sys.exit(app.exec())
