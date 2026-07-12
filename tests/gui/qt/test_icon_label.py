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

from pathlib import Path

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.gui.qt.util import get_icon_path


def test_icon_label_defaults_to_icon_left(qtbot: QtBot) -> None:
    label = IconLabel("Default")
    label.set_icon(Path(get_icon_path("checkmark.svg")))
    qtbot.addWidget(label)

    layout = label.layout()

    assert layout is not None
    assert layout.itemAt(0).widget() == label.icon_label
    assert layout.itemAt(1).widget() == label.textLabel


def test_icon_label_can_place_icon_on_right(qtbot: QtBot) -> None:
    label = IconLabel("Status", icon_on_right=True)
    label.set_icon(Path(get_icon_path("checkmark.svg")))
    qtbot.addWidget(label)

    layout = label.layout()

    assert layout is not None
    assert layout.itemAt(0).widget() == label.textLabel
    assert layout.itemAt(1).widget() == label.icon_label


def test_icon_label_re_renders_theme_icon_on_palette_change(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    label = IconLabel("Status")
    label.set_icon("bi--question-circle.svg")
    qtbot.addWidget(label)
    label.show()
    qtbot.waitExposed(label)

    def render_with_palette(window: str, text: str):
        palette = QPalette(original_palette)
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        palette.setColor(QPalette.ColorRole.Text, QColor(text))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(text))
        palette.setColor(QPalette.ColorRole.Dark, QColor(text))
        app.setPalette(palette)
        QApplication.sendEvent(label, QEvent(QEvent.Type.ApplicationPaletteChange))
        qtbot.wait(10)
        pixmap = label.icon_label.pixmap()
        assert pixmap is not None and not pixmap.isNull()
        return pixmap.toImage()

    try:
        light_image = render_with_palette("#ffffff", "#101010")
        dark_image = render_with_palette("#101010", "#f5f5f5")
    finally:
        app.setPalette(original_palette)
        QApplication.sendEvent(label, QEvent(QEvent.Type.ApplicationPaletteChange))

    assert light_image != dark_image


def test_icon_label_supports_absolute_icon_path_on_palette_change(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    label = IconLabel("Status")
    label.set_icon(Path(get_icon_path("bi--question-circle.svg")))
    qtbot.addWidget(label)
    label.show()
    qtbot.waitExposed(label)

    try:
        dark_palette = QPalette(original_palette)
        dark_palette.setColor(QPalette.ColorRole.Window, QColor("#101010"))
        dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("#f5f5f5"))
        dark_palette.setColor(QPalette.ColorRole.Text, QColor("#f5f5f5"))
        dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f5f5f5"))
        dark_palette.setColor(QPalette.ColorRole.Dark, QColor("#f5f5f5"))
        app.setPalette(dark_palette)
        QApplication.sendEvent(label, QEvent(QEvent.Type.ApplicationPaletteChange))
        qtbot.wait(10)
    finally:
        app.setPalette(original_palette)
        QApplication.sendEvent(label, QEvent(QEvent.Type.ApplicationPaletteChange))

    pixmap = label.icon_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()


def test_icon_label_ignores_style_change_event(qtbot: QtBot, monkeypatch) -> None:
    label = IconLabel("Status")
    qtbot.addWidget(label)

    calls = 0

    def track_apply_icon() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(label, "_apply_icon", track_apply_icon)

    label.changeEvent(QEvent(QEvent.Type.StyleChange))

    assert calls == 0
