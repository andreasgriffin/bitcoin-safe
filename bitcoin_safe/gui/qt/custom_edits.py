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

from __future__ import annotations

import enum
import logging
from abc import abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QRect, QStringListModel, Qt, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QKeyEvent, QPainter, QPaintEvent, QPalette
from PyQt6.QtWidgets import QApplication, QCompleter, QLineEdit, QTextEdit, QWidget

logger = logging.getLogger(__name__)
ENABLE_COMPLETERS = True


class AnalyzerState(enum.IntEnum):
    Valid = enum.auto()
    Warning = enum.auto()
    Invalid = enum.auto()


@dataclass
class AnalyzerMessage:
    msg: str
    state: AnalyzerState

    @classmethod
    def valid(cls):
        """Valid."""
        return cls("", AnalyzerState.Valid)

    def __str__(self) -> str:
        """Return string representation."""
        return f"{self.state.name}: {self.msg}"


class BaseAnalyzer:
    @abstractmethod
    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        """Analyze."""
        raise NotImplementedError()

    def normalize(self, input: str, pos: int = 0) -> tuple[str, int]:
        """Normalize."""
        return input, pos

    @staticmethod
    def worst_message(message_list: list[AnalyzerMessage]):
        """Worst message."""
        if not message_list:
            return AnalyzerMessage("", AnalyzerState.Valid)
        states = [message.state for message in message_list]
        worst_state = max(states)
        return message_list[states.index(worst_state)]


class BaseIntAnalyzer:
    @abstractmethod
    def analyze(self, input: int) -> AnalyzerMessage:
        """Analyze."""
        raise NotImplementedError()

    def normalize(self, input: int) -> int:
        """Normalize."""
        return input

    @staticmethod
    def worst_message(message_list: list[AnalyzerMessage]):
        """Worst message."""
        if not message_list:
            return AnalyzerMessage("", AnalyzerState.Valid)
        states = [message.state for message in message_list]
        worst_state = max(states)
        return message_list[states.index(worst_state)]


class AnalyzerLineEdit(QLineEdit):
    def __init__(self, parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self._smart_state: BaseAnalyzer | None = None
        self.display_name = ""

    def setReadOnly(self, a0: bool):
        """SetReadOnly."""
        super().setReadOnly(a0)
        super().setFrame(not a0)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus if a0 else Qt.FocusPolicy.StrongFocus)
        self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """PaintEvent."""
        if not self.isReadOnly():
            return super().paintEvent(a0)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # current base color
        curr_bg = self.palette().color(QPalette.ColorRole.Base)
        # the “true default” base color from the application
        default_bg = QApplication.palette().color(QPalette.ColorRole.Base)

        # only fill if someone has customized it
        if curr_bg != default_bg:
            painter.fillRect(self.rect(), curr_bg)

        # draw text in the usual way
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        m = self.textMargins()
        text_rect = QRect(
            m.left(),
            m.top(),
            self.width() - (m.left() + m.right()),
            self.height() - (m.top() + m.bottom()),
        )
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.displayText()
        )

    def setAnalyzer(self, smart_state: BaseAnalyzer):
        """Set a custom validator."""
        self._smart_state = smart_state

    def analyzer(self) -> BaseAnalyzer | None:
        """Analyzer."""
        return self._smart_state

    def normalize(self):
        """Normalize."""
        analyzer = self.analyzer()
        if not analyzer:
            return
        old_input = self.text()
        old_pos = self.cursorPosition()
        new_input, new_pos = analyzer.normalize(old_input, old_pos)

        if new_input != old_input:
            self.setText(new_input)

        new_pos = min(new_pos, len(new_input))
        if new_pos != old_pos:
            self.setCursorPosition(new_pos)


class AnalyzerTextEdit(QTextEdit):
    def __init__(self, text: str | None = None, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(text, parent)
        self._smart_state: BaseAnalyzer | None = None
        self.setAcceptRichText(False)
        self.display_name = ""

    def setAnalyzer(self, smart_state: BaseAnalyzer):
        """Set a custom validator."""
        self._smart_state = smart_state

    def analyzer(self) -> BaseAnalyzer | None:
        """Analyzer."""
        return self._smart_state

    def text(self) -> str:
        """Text."""
        return self.toPlainText()

    def cursorPosition(self) -> int:
        """Get the current cursor position within the text."""
        return self.textCursor().position()

    def setCursorPosition(self, position: int):
        """Set the cursor position to the specified index."""
        cursor = self.textCursor()
        cursor.setPosition(position)
        self.setTextCursor(cursor)

    def normalize(self):
        """Normalize."""
        analyzer = self.analyzer()
        if not analyzer:
            return
        old_input = self.text()
        old_pos = self.cursorPosition()
        new_input, new_pos = analyzer.normalize(old_input, old_pos)

        if new_input != old_input:
            self.setText(new_input)

        new_pos = min(new_pos, len(new_input))
        if new_pos != old_pos:
            self.setCursorPosition(new_pos)


class QCompleterLineEdit(AnalyzerLineEdit):
    signal_focus_out = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        network: bdk.Network,
        suggestions: dict[bdk.Network, list[str]] | None = None,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        # Dictionary to store suggestions for each network
        self.suggestions = suggestions if suggestions else {network: [] for network in bdk.Network}
        self.network = network  # Set the initial network
        self._completer = QCompleter(self.suggestions[self.network], self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._model = QStringListModel()
        if ENABLE_COMPLETERS:
            self.setCompleter(self._completer)

    def set_completer_list(self, words: Iterable[str]):
        """Set completer list."""
        self._model.setStringList(words)
        self._completer.setModel(self._model)

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
        """Updates the completer with the current network's suggestions list."""
        if self.network:
            self.set_completer_list(self.suggestions[self.network])

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """KeyPressEvent."""
        if not a0:
            super().keyPressEvent(a0)
            return

        if self.network and a0.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            popup = self._completer.popup()
            if popup and not popup.isVisible():
                self._completer.complete()
        super().keyPressEvent(a0)

    def focusOutEvent(self, a0: QFocusEvent | None) -> None:
        """FocusOutEvent."""
        super().focusOutEvent(a0)
        self.signal_focus_out.emit()

    def close(self) -> bool:
        """Close."""
        self._smart_state = None
        return super().close()
