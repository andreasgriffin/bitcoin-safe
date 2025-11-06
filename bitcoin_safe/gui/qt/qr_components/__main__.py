import random
from typing import TYPE_CHECKING, Any, cast

import bdkpython as bdk
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.qr_components.quick_receive import QuickReceive, ReceiveGroup
from bitcoin_safe.pythonbdk_types import AddressInfoMin

if TYPE_CHECKING:
    from bitcoin_safe.stubs.typestubs import TypedPyQtSignalNo


def generate_random_hex_color() -> str:
    """Generate a random hex color code."""
    random_color = f"#{random.randint(0, 0xFFFFFF):06x}"
    return random_color


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    class My(QObject):
        close_all_video_widgets: TypedPyQtSignalNo = cast(Any, pyqtSignal())

    my = My()

    custom_widget = QuickReceive("Quick Receive")
    custom_widget.show()

    # Example usage
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(
            color,
            generate_random_hex_color(),
            AddressInfoMin(color * 10, 0, bdk.KeychainKind.EXTERNAL),
            color * 10,
        )
    )
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(
            color,
            generate_random_hex_color(),
            AddressInfoMin(color * 10, 0, bdk.KeychainKind.EXTERNAL),
            color * 10,
        )
    )
    color = generate_random_hex_color()
    custom_widget.add_box(
        ReceiveGroup(
            color,
            generate_random_hex_color(),
            AddressInfoMin(color * 10, 0, bdk.KeychainKind.EXTERNAL),
            color * 10,
        )
    )

    sys.exit(app.exec())
