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
from PyQt6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.util import (
    propagate_theme_change_to_descendants,
    remember_theme_state,
    should_process_theme_change,
)


def test_should_process_theme_change_skips_duplicate_palette_event(qtbot: QtBot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    remember_theme_state(widget)

    assert not should_process_theme_change(widget, QEvent(QEvent.Type.PaletteChange))

    palette = QPalette(widget.palette())
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f5f5f5"))
    widget.setPalette(palette)

    assert should_process_theme_change(widget, QEvent(QEvent.Type.PaletteChange))
    assert not should_process_theme_change(widget, QEvent(QEvent.Type.PaletteChange))


def test_should_process_theme_change_keeps_enabled_change_events(qtbot: QtBot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    remember_theme_state(widget)

    assert should_process_theme_change(widget, QEvent(QEvent.Type.EnabledChange), include_enabled_change=True)
    assert should_process_theme_change(widget, QEvent(QEvent.Type.EnabledChange), include_enabled_change=True)


class _ThemePropagationProbe(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette_change_calls = 0

    def changeEvent(self, event: QEvent | None) -> None:
        super().changeEvent(event)
        if should_process_theme_change(self, event):
            self.palette_change_calls += 1


def test_propagate_theme_change_to_descendants_forwards_palette_change(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    parent = QWidget()
    child = _ThemePropagationProbe(parent)
    qtbot.addWidget(parent)
    parent.show()
    qtbot.waitExposed(parent)

    try:
        dark_palette = QPalette(original_palette)
        dark_palette.setColor(QPalette.ColorRole.Window, QColor("#111111"))
        dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("#f5f5f5"))
        app.setPalette(dark_palette)
        propagate_theme_change_to_descendants(parent)
        qtbot.wait(10)
    finally:
        app.setPalette(original_palette)

    assert child.palette_change_calls == 1
    assert child.palette().color(QPalette.ColorRole.Window).name() == "#111111"
