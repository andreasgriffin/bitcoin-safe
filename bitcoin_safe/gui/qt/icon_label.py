#
# Bitcoin Safe
# Copyright (C) 2025-2026 Andreas Griffin
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

import logging
from pathlib import Path
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.util_os import webopen
from PyQt6.QtCore import QEvent, QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from bitcoin_safe.gui.qt.util import svg_tools

from .util import set_no_margins, should_process_theme_change

logger = logging.getLogger(__name__)


class ClickableLabel(QLabel):
    # define a new signal
    clicked = cast(SignalProtocol[[]], pyqtSignal())

    def mouseReleaseEvent(self, ev: QMouseEvent | None) -> None:
        # only emit on left-click
        """MouseReleaseEvent."""
        if ev and ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        # pass on the event in case anything else is listening
        super().mouseReleaseEvent(ev)


class IconLabel(QWidget):
    def __init__(
        self,
        text: str = "",
        parent=None,
        icon_on_right: bool = False,
        **kwargs,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent, **kwargs)
        self._layout = QHBoxLayout(self)
        set_no_margins(self._layout)
        self._icon_on_right = icon_on_right

        self.click_url: str | None = None
        self._icon_name: str | Path | None = None
        self._icon_sizes: tuple[int | None, int | None] = (None, None)

        # Icon Label
        self.icon_label = ClickableLabel()
        self.icon_label.setVisible(False)
        self.icon_label.clicked.connect(self.on_icon_click)
        self._layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Text Label
        self.textLabel = QLabel(text)
        self.textLabel.setTextFormat(Qt.TextFormat.RichText)
        self.textLabel.setOpenExternalLinks(True)  # Enable opening links
        self._sync_layout_order()

        for widget in (self, self.icon_label, self.textLabel):
            widget.installEventFilter(self)

    def set_icon_on_right(self, icon_on_right: bool) -> None:
        """Set whether the icon should be displayed after the text."""
        if self._icon_on_right == icon_on_right:
            return
        self._icon_on_right = icon_on_right
        self._sync_layout_order()

    def _sync_layout_order(self) -> None:
        while self._layout.count():
            self._layout.takeAt(0)
        widgets = (
            (self.textLabel, self.icon_label) if self._icon_on_right else (self.icon_label, self.textLabel)
        )
        for widget in widgets:
            self._layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def setText(self, a0: str | None) -> None:
        """SetText."""
        if a0 is None:
            a0 = ""
        # IconLabel uses RichText to allow links; convert newlines so they render.
        a0 = a0.replace("\n", "<br>")
        self.textLabel.setText(a0)

    def set_icon(self, icon: str | Path | None, sizes: tuple[int | None, int | None] = (None, None)) -> None:
        """Set icon."""
        self._icon_name = icon
        self._icon_sizes = sizes
        self._apply_icon()

    def _apply_icon(self) -> None:
        icon_name = str(self._icon_name) if self._icon_name else None
        icon = svg_tools.get_QIcon(icon_name) if icon_name else None
        self.icon_label.setVisible(bool(icon))
        if not icon:
            self.icon_label.clear()
            return

        fm = self.textLabel.fontMetrics()
        line_height = fm.height()
        pixmap_sizes = [s if s else line_height for s in self._icon_sizes]
        self.icon_label.setPixmap(icon.pixmap(QSize(*pixmap_sizes), self.devicePixelRatioF()))
        self.icon_label.setFixedSize(QSize(*pixmap_sizes))

    def on_icon_click(self):
        """On icon click."""
        if not self.click_url:
            return
        webopen(self.click_url)

    def set_icon_as_help(self, tooltip: str | None, click_url: str | None = None):
        """Set icon as help."""
        effective_tooltip = tooltip or click_url or ""
        self.setToolTip(effective_tooltip)
        self.icon_label.setToolTip(effective_tooltip)
        self.textLabel.setToolTip(effective_tooltip)
        self.click_url = click_url
        if self.click_url:
            self.set_icon("bi--question-circle-link.svg")
            self.icon_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.textLabel.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.set_icon("bi--question-circle.svg")
            self.icon_label.unsetCursor()
            self.textLabel.unsetCursor()
            self.unsetCursor()

    def changeEvent(self, a0: QEvent | None) -> None:
        """Re-render theme-colored SVG icons when the palette changes."""
        super().changeEvent(a0)
        if should_process_theme_change(self, a0):
            self._apply_icon()

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        """Handle clicks locally for clickable help labels."""
        if (
            self.click_url
            and a0 in (self, self.icon_label, self.textLabel)
            and isinstance(a1, QMouseEvent)
            and a1.button() == Qt.MouseButton.LeftButton
        ):
            if a1.type() == QEvent.Type.MouseButtonPress:
                a1.accept()
                return True
            if a1.type() == QEvent.Type.MouseButtonRelease:
                self.on_icon_click()
                a1.accept()
                return True
        return super().eventFilter(a0, a1)
