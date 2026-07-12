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

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.util import NeutralSurfaceColors, color_with_alpha
from bitcoin_safe.plugin_framework.plugin_list_widget import BasePluginWidget


def test_base_plugin_widget_refreshes_theme_assets_on_palette_change(qtbot: QtBot, monkeypatch) -> None:
    app = QApplication.instance()
    assert app is not None

    widget = BasePluginWidget(
        title="Plugin",
        description="Plugin description",
        provider="Provider",
        icon="bi--question-circle.svg",
    )
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    def local_surface_colors() -> NeutralSurfaceColors:
        palette = widget.palette()
        return NeutralSurfaceColors(
            panel_background=QColor(palette.color(QPalette.ColorRole.Window)),
            content_background=QColor(palette.color(QPalette.ColorRole.Base)),
            panel_border=color_with_alpha(palette.color(QPalette.ColorRole.Mid), 110),
            row_hover=color_with_alpha(palette.color(QPalette.ColorRole.Mid), 55),
            muted_text=color_with_alpha(palette.color(QPalette.ColorRole.WindowText), 170),
        )

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.plugin_list_widget.get_neutral_surface_colors", local_surface_colors
    )

    def render_with_palette(window: str, text: str) -> tuple[str, str]:
        palette = QPalette(widget.palette())
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.Base, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        palette.setColor(QPalette.ColorRole.Text, QColor(text))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(text))
        palette.setColor(QPalette.ColorRole.Dark, QColor(text))
        widget.setPalette(palette)
        QApplication.sendEvent(widget, QEvent(QEvent.Type.PaletteChange))
        qtbot.waitUntil(lambda: widget.background_color is not None, timeout=1000)
        qtbot.wait(10)
        pixmap = widget.icon_label.pixmap()
        assert pixmap is not None and not pixmap.isNull()
        return (
            widget.description_label.styleSheet(),
            widget.provider_label.styleSheet(),
        )

    light_description, light_provider = render_with_palette("#ffffff", "#101010")
    dark_description, dark_provider = render_with_palette("#101010", "#f5f5f5")

    assert light_description != dark_description
    assert light_provider != dark_provider
