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

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

import bitcoin_safe.theme as theme


def test_apply_theme_mode_system_clears_app_palette_override(qtbot) -> None:
    del qtbot
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original_palette = QPalette(app.palette())
    custom_palette = QPalette(original_palette)
    custom_palette.setColor(QPalette.ColorRole.Window, QColor("#123456"))
    app.setPalette(custom_palette)

    try:
        theme.apply_theme_mode(app, theme.ThemeMode.SYSTEM)
        assert app.palette().color(QPalette.ColorRole.Window) == original_palette.color(
            QPalette.ColorRole.Window
        )
    finally:
        app.setPalette(original_palette)


def test_apply_theme_mode_light_overrides_dark_app_palette(qtbot) -> None:
    del qtbot
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original_palette = QPalette(app.palette())
    dark_palette = QPalette(original_palette)
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#111111"))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("#f5f5f5"))
    dark_palette.setColor(QPalette.ColorRole.Base, QColor("#181818"))
    dark_palette.setColor(QPalette.ColorRole.Text, QColor("#f5f5f5"))
    app.setPalette(dark_palette)

    try:
        theme.apply_theme_mode(app, theme.ThemeMode.LIGHT)
        assert app.palette().color(QPalette.ColorRole.Window).name() == "#efefef"
        assert app.palette().color(QPalette.ColorRole.WindowText).name() == "#000000"
        assert app.palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
        assert app.palette().color(QPalette.ColorRole.Text).name() == "#000000"
    finally:
        app.setPalette(original_palette)
