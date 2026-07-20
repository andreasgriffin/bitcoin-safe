#
# Bitcoin-Safe
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

import enum
import logging

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class ThemeMode(enum.Enum):
    SYSTEM = enum.auto()
    LIGHT = enum.auto()
    DARK = enum.auto()


def _standard_palette(app: QApplication) -> QPalette:
    style = app.style()
    if style:
        return QPalette(style.standardPalette())
    return QPalette(app.palette())


def create_dark_palette(base_palette: QPalette | None = None) -> QPalette:
    """Create the app's dark palette."""
    dark_palette = QPalette(base_palette) if base_palette is not None else QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(42, 42, 42))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(66, 66, 66))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(0, 0, 0))
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    dark_palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    return dark_palette


def create_light_palette(base_palette: QPalette | None = None) -> QPalette:
    """Create a light palette independent of the desktop theme."""
    light_palette = QPalette(base_palette) if base_palette is not None else QPalette()
    light_palette.setColor(QPalette.ColorRole.Window, QColor("#efefef"))
    light_palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
    light_palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    light_palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f7f7"))
    light_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffdc"))
    light_palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#000000"))
    light_palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
    light_palette.setColor(QPalette.ColorRole.Button, QColor("#efefef"))
    light_palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
    light_palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    return light_palette


def apply_theme_mode(app: QApplication, theme_mode: ThemeMode) -> None:
    """Apply the configured theme mode to the application palette."""
    if theme_mode == ThemeMode.SYSTEM:
        # Clear any app-level override so Qt can follow the desktop palette again.
        app.setPalette(QPalette())
        return

    if theme_mode == ThemeMode.DARK:
        standard_palette = _standard_palette(app)
        app.setPalette(create_dark_palette(standard_palette))
        return

    app.setPalette(create_light_palette(_standard_palette(app)))
