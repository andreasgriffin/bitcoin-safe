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

import bdkpython as bdk
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QLabel
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.notification_bar_regtest import NotificationBarRegtest
from bitcoin_safe.gui.qt.util import adjust_brightness
from bitcoin_safe.signals import SignalsMin


def test_notification_bar_reapplies_base_background_on_palette_change(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    bar = NotificationBar("Status")
    extra_label = QLabel("extra")
    bar.add_styled_widget(extra_label)
    qtbot.addWidget(bar)
    bar.show()
    qtbot.waitExposed(bar)

    base_color = QColor("#FFDF00")

    def apply_palette(window: str, text: str) -> str:
        palette = QPalette(original_palette)
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        app.setPalette(palette)
        bar.set_background_base_color(base_color)
        QApplication.sendEvent(bar, QEvent(QEvent.Type.ApplicationPaletteChange))
        qtbot.wait(10)
        assert bar.color is not None
        assert f"background-color: {bar.color.name()};" in extra_label.styleSheet()
        return bar.color.name()

    try:
        light_name = apply_palette("#ffffff", "#101010")
        dark_name = apply_palette("#101010", "#f5f5f5")
    finally:
        app.setPalette(original_palette)
        QApplication.sendEvent(bar, QEvent(QEvent.Type.ApplicationPaletteChange))

    assert light_name == base_color.name()
    assert dark_name == adjust_brightness(base_color, -0.4).name()


def test_regtest_notification_bar_reacts_to_application_palette_change(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    bar = NotificationBarRegtest(
        callback_open_network_setting=lambda: None,
        network=bdk.Network.REGTEST,
        signals_min=SignalsMin(),
    )
    qtbot.addWidget(bar)
    bar.show()
    qtbot.waitExposed(bar)

    def apply_palette(window: str, text: str) -> str:
        palette = QPalette(original_palette)
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        app.setPalette(palette)
        qtbot.wait(10)
        assert bar.color is not None
        return bar.color.name()

    try:
        light_name = apply_palette("#ffffff", "#101010")
        dark_name = apply_palette("#101010", "#f5f5f5")
    finally:
        app.setPalette(original_palette)

    assert light_name == QColor("lightblue").name()
    assert dark_name == adjust_brightness(QColor("lightblue"), -0.4).name()


def test_notification_bar_ignores_style_change_event(qtbot: QtBot, monkeypatch) -> None:
    bar = NotificationBar("Status")
    qtbot.addWidget(bar)

    calls = 0

    def track_refresh() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(bar, "_refresh_theme_background", track_refresh)

    bar.changeEvent(QEvent(QEvent.Type.StyleChange))

    assert calls == 0
