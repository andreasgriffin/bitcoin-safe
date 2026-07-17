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

from PyQt6.QtCore import QEvent
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.wizard.wizard_support import ThemeAwareStepWidget


class DummyTab:
    def __init__(self) -> None:
        self.is_closed = False
        self.update_calls = 0

    def updateUi(self) -> None:
        self.update_calls += 1


def test_theme_aware_step_widget_updates_open_tab_on_palette_change(qtbot: QtBot) -> None:
    tab = DummyTab()
    widget = ThemeAwareStepWidget(tab=tab)
    qtbot.addWidget(widget)

    widget.changeEvent(QEvent(QEvent.Type.ApplicationPaletteChange))

    assert tab.update_calls == 1


def test_theme_aware_step_widget_skips_closed_tab_on_palette_change(qtbot: QtBot) -> None:
    tab = DummyTab()
    tab.is_closed = True
    widget = ThemeAwareStepWidget(tab=tab)
    qtbot.addWidget(widget)

    widget.changeEvent(QEvent(QEvent.Type.ApplicationPaletteChange))

    assert tab.update_calls == 0
