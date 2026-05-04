#
# Bitcoin Safe
# Copyright (C) 2026 Andreas Griffin
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

from __future__ import annotations

from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QWidget

from bitcoin_safe.gui.qt.util import svg_tools


class NetworkComboBox(QComboBox):
    signal_network_changed = cast(SignalProtocol[[bdk.Network]], pyqtSignal(bdk.Network))

    def __init__(self, network: bdk.Network, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)

        for current_network in bdk.Network:
            self.addItem(
                svg_tools.get_QIcon(f"bitcoin-{current_network.name.lower()}.svg"),
                current_network.name,
                userData=current_network,
            )

        self.network = network
        self.currentIndexChanged.connect(self._on_current_index_changed)

    def _on_current_index_changed(self, _index: int) -> None:
        """Emit the selected network as a typed signal."""
        self.signal_network_changed.emit(self.network)

    @property
    def network(self) -> bdk.Network:
        """Selected network."""
        return cast(bdk.Network, self.currentData())

    @network.setter
    def network(self, value: bdk.Network) -> None:
        """Selected network."""
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)
