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

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QFrame, QWidget

from .util import get_neutral_surface_colors, to_color_name


class BaseCardFrame(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self._border_radius = 8
        self.background_color: QColor | str | None = get_neutral_surface_colors().panel_background

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if not self.objectName():
            self.setObjectName(f"styledCardFrame_{id(self)}")

    def _get_style_content(self):
        return f"border-radius: {self._border_radius}px;" + (
            f" background: {to_color_name(self.background_color)};" if self.background_color else ""
        )

    def refresh_style(self) -> None:
        self.setStyleSheet(
            f"""
            #{self.objectName()} {{
                {self._get_style_content()}
            }}
            """
        )


class BaseBorderCardFrame(BaseCardFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected = False
        self.border_width = 1

    def _get_style_content(self):
        surface_colors = get_neutral_surface_colors()
        border_color = (
            self.palette().color(QPalette.ColorRole.Mid) if self._selected else surface_colors.panel_border
        )

        s = super()._get_style_content()
        s += f"\nborder: {self.border_width}px solid {to_color_name(border_color)};"
        return s
