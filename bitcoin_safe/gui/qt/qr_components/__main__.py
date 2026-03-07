#
# Bitcoin Safe
# Copyright (C) 2023-2026 Andreas Griffin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

import random
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.qr_components.quick_receive import QuickReceive, ReceiveGroup
from bitcoin_safe.pythonbdk_types import AddressInfoMin


def generate_random_hex_color() -> str:
    """Generate a random hex color code."""
    random_color = f"#{random.randint(0, 0xFFFFFF):06x}"
    return random_color


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    class My(QObject):
        close_all_video_widgets = cast(SignalProtocol[[]], pyqtSignal())

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
