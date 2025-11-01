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

import logging

from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtGui import QEnterEvent, QIcon, QPalette
from PyQt6.QtWidgets import QPushButton, QWidget

from bitcoin_safe.gui.qt.util import set_translucent, svg_tools, to_color_name

logger = logging.getLogger(__name__)
SMALL_ICON_SIZE = QSize(16, 16)
DEFAULT_ICON_SIZE = QSize(16, 16)


class FlatSquareButton(QPushButton):
    def __init__(
        self,
        qicon: QIcon,
        size=DEFAULT_ICON_SIZE,
        parent: QWidget | None = None,
        hover_icon: QIcon | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self._default_icon = qicon
        self._hover_icon = hover_icon
        self.setFlat(True)
        self.setFixedSize(size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        set_translucent(self)
        self._set_current_icon(qicon)

    def setIcon(self, icon: QIcon) -> None:
        """SetIcon."""
        self._default_icon = icon
        self._set_current_icon(icon)

    def _set_current_icon(self, icon: QIcon) -> None:
        """Set current icon."""
        super().setIcon(icon)

    def enterEvent(self, event: QEnterEvent | None) -> None:
        """EnterEvent."""
        if self._hover_icon is not None and self.isEnabled():
            self._set_current_icon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, a0: QEvent | None) -> None:
        """LeaveEvent."""
        if self._hover_icon is not None:
            self._set_current_icon(self._default_icon)
        super().leaveEvent(a0)

    def changeEvent(self, e: QEvent | None) -> None:
        """ChangeEvent."""
        if e and e.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._set_current_icon(self._default_icon)
        super().changeEvent(e)


class CloseButton(FlatSquareButton):
    def __init__(self, size=SMALL_ICON_SIZE, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        default_icon = svg_tools.get_QIcon(
            "close.svg",
            auto_theme=False,
            replace_tuples=(("#FE1D01", to_color_name(QPalette.ColorRole.Dark)),),
        )
        hover_icon = svg_tools.get_QIcon(
            "close.svg",
            auto_theme=False,
        )
        super().__init__(qicon=default_icon, size=size, parent=parent, hover_icon=hover_icon)
