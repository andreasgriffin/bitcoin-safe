#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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


import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


import bdkpython as bdk
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QKeyEvent
from PyQt6.QtWidgets import QCompleter, QLineEdit, QTextEdit


class MyTextEdit(QTextEdit):
    def __init__(self, preferred_height=50) -> None:
        super().__init__()
        self.preferred_height = preferred_height

    def sizeHint(self) -> QSize:
        size = super().sizeHint()
        size.setHeight(self.preferred_height)
        return size


class QCompleterLineEdit(QLineEdit):
    signal_focus_out = pyqtSignal()

    def __init__(
        self, network: bdk.Network, suggestions: Dict[bdk.Network, List[str]] = None, parent=None
    ) -> None:
        super().__init__(parent)
        # Dictionary to store suggestions for each network
        self.suggestions = suggestions if suggestions else {network: [] for network in bdk.Network}
        self.network = network  # Set the initial network
        self._completer = QCompleter(self.suggestions[self.network], self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(self._completer)

    def set_network(self, network) -> None:
        """Set the network and update the completer."""
        self.network = network
        if network not in self.suggestions:
            self.suggestions[network] = []
        self._update_completer()

    def reset_memory(self) -> None:
        """Clears the memory for the current network."""
        if self.network:
            self.suggestions[self.network].clear()
            self._update_completer()

    def add_current_to_memory(self) -> None:
        """Adds the current text to the memory of the current network."""
        current_text = self.text()
        if self.network and current_text and current_text not in self.suggestions[self.network]:
            self.suggestions[self.network].append(current_text)
            self._update_completer()

    def add_to_memory(self, text) -> None:
        """Adds a specific string to the memory of the current network."""
        if self.network and text and text not in self.suggestions[self.network]:
            self.suggestions[self.network].append(text)
            self._update_completer()

    def _update_completer(self) -> None:
        """Updates the completer with the current network's suggestions
        list."""
        if self.network:
            self._completer.model().setStringList(self.suggestions[self.network])

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.network and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if not self._completer.popup().isVisible():
                self._completer.complete()
        super(QCompleterLineEdit, self).keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.signal_focus_out.emit()
