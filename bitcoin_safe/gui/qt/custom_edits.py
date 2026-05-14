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

from __future__ import annotations

import enum
import logging
from abc import abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QRect, QSize, QStringListModel, Qt, pyqtSignal
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


class AnalyzerEditable(Protocol):
    """Minimal text-edit interface required by analyzer support."""

    display_name: str

    def text(self) -> str: ...
    def setText(self, a0: str | None) -> None: ...

    def cursorPosition(self) -> int: ...
    def setCursorPosition(self, a0: int) -> None: ...

    def setObjectName(self, name: str) -> None: ...
    def objectName(self) -> str: ...
    def setStyleSheet(self, styleSheet: str) -> None: ...


TEdit = TypeVar("TEdit", bound=AnalyzerEditable)


class AnalyzerSupport(Generic[TEdit]):
    """Analyzer behavior shared by different edit widgets."""

    def __init__(self, edit: TEdit) -> None:
        self.edit = edit
        self._analyzer: BaseAnalyzer | None = None

    def set_analyzer(self, analyzer: BaseAnalyzer) -> None:
        self._analyzer = analyzer

    def analyzer(self) -> BaseAnalyzer | None:
        return self._analyzer

    def analyze_text(self, text: str, pos: int = 0) -> AnalyzerMessage:
        analyzer = self.analyzer()
        return analyzer.analyze(text, pos) if analyzer else AnalyzerMessage.valid()

    def analyze_current_text(self) -> AnalyzerMessage:
        self.normalize()
        return self.analyze_text(self.edit.text(), self.edit.cursorPosition())

    def normalize(self) -> None:
        analyzer = self.analyzer()
        if analyzer is None:
            return

        old_text = self.edit.text()
        old_pos = self.edit.cursorPosition()

        new_text, new_pos = analyzer.normalize(old_text, old_pos)

        if new_text != old_text:
            self.edit.setText(new_text)

        new_pos = min(new_pos, len(new_text))
        if new_pos != old_pos:
            self.edit.setCursorPosition(new_pos)

    def format_edit(self, analyzer_state: AnalyzerState | None) -> None:
        from .util import ColorScheme

        edit = self.edit
        edit.setObjectName(str(id(edit)))

        if analyzer_state == AnalyzerState.Warning:
            color = ColorScheme.WARNING.as_color(background=True).name()
            edit.setStyleSheet(f"#{edit.objectName()} {{ background-color: {color}; }}")
        elif analyzer_state == AnalyzerState.Invalid:
            color = ColorScheme.ERROR.as_color(background=True).name()
            edit.setStyleSheet(f"#{edit.objectName()} {{ background-color: {color}; }}")
        else:
            edit.setStyleSheet(f"#{edit.objectName()} {{ }}")

    @staticmethod
    def state_for_text(
        text: str,
        analysis: AnalyzerMessage,
        override_state: AnalyzerState | None = None,
    ) -> AnalyzerState | None:
        if override_state is not None:
            return override_state
        if text and analysis.state != AnalyzerState.Valid:
            return analysis.state
        return None


class AnalyzerLineEdit(QLineEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self.display_name = ""
        self._analyzer_support = AnalyzerSupport(self)

    def setAnalyzer(self, analyzer: BaseAnalyzer) -> None:
        self._analyzer_support.set_analyzer(analyzer)

    def analyzer(self) -> BaseAnalyzer | None:
        return self._analyzer_support.analyzer()

    def analyze_text(self, text: str, pos: int = 0) -> AnalyzerMessage:
        return self._analyzer_support.analyze_text(text, pos)

    def analyze_current_text(self) -> AnalyzerMessage:
        return self._analyzer_support.analyze_current_text()

    def normalize(self) -> None:
        self._analyzer_support.normalize()

    def format_edit(self, analyzer_state: AnalyzerState | None) -> None:
        self._analyzer_support.format_edit(analyzer_state)

    @staticmethod
    def state_for_text(
        text: str,
        analysis: AnalyzerMessage,
        override_state: AnalyzerState | None = None,
    ) -> AnalyzerState | None:
        return AnalyzerSupport.state_for_text(text, analysis, override_state)

    def setReadOnly(self, a0: bool) -> None:
        super().setReadOnly(a0)
        super().setFrame(not a0)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus if a0 else Qt.FocusPolicy.StrongFocus)
        self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        if not self.isReadOnly():
            return super().paintEvent(a0)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        curr_bg = self.palette().color(QPalette.ColorRole.Base)
        default_bg = QApplication.palette().color(QPalette.ColorRole.Base)

        if curr_bg != default_bg:
            painter.fillRect(self.rect(), curr_bg)

        painter.setPen(self.palette().color(QPalette.ColorRole.Text))

        margins = self.textMargins()
        text_rect = QRect(
            margins.left(),
            margins.top(),
            self.width() - margins.left() - margins.right(),
            self.height() - margins.top() - margins.bottom(),
        )

        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.displayText(),
        )


class FlexibleHeightTextedit(QTextEdit):
    def sizeHint(self) -> QSize:
        """SizeHint."""
        size = super().sizeHint()
        size.setHeight(30)
        return size


class AnalyzerTextEdit(FlexibleHeightTextedit):
    def __init__(
        self,
        text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.display_name = ""
        self._analyzer = AnalyzerSupport(self)
        self.setAcceptRichText(False)

    def setAnalyzer(self, analyzer: BaseAnalyzer) -> None:
        self._analyzer.set_analyzer(analyzer)

    def analyzer(self) -> BaseAnalyzer | None:
        return self._analyzer.analyzer()

    def analyze_text(self, text: str, pos: int = 0) -> AnalyzerMessage:
        return self._analyzer.analyze_text(text, pos)

    def analyze_current_text(self) -> AnalyzerMessage:
        return self._analyzer.analyze_current_text()

    def normalize(self) -> None:
        self._analyzer.normalize()

    def format_edit(self, analyzer_state: AnalyzerState | None) -> None:
        self._analyzer.format_edit(analyzer_state)

    @staticmethod
    def state_for_text(
        text: str,
        analysis: AnalyzerMessage,
        override_state: AnalyzerState | None = None,
    ) -> AnalyzerState | None:
        return AnalyzerSupport.state_for_text(text, analysis, override_state)

    def text(self) -> str:
        return self.toPlainText()

    def cursorPosition(self) -> int:
        return self.textCursor().position()

    def setCursorPosition(self, a0: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(a0)
        self.setTextCursor(cursor)

    def setText(self, a0: str | None) -> None:  # type: ignore
        self.setPlainText(a0 or "")


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
