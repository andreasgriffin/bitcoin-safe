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

from bitcoin_safe.gui.qt.ui_tx.spinbox import AnalyzerSpinBox


def test_analyzer_spinbox_ignores_style_change_event(qtbot: QtBot) -> None:
    widget = AnalyzerSpinBox()
    qtbot.addWidget(widget)
    widget.setReadOnly(True)

    widget.changeEvent(QEvent(QEvent.Type.StyleChange))

    assert "background: transparent;" in widget.styleSheet()


def test_analyzer_spinbox_handles_palette_change_event(qtbot: QtBot) -> None:
    widget = AnalyzerSpinBox()
    qtbot.addWidget(widget)
    widget.setReadOnly(True)

    widget.changeEvent(QEvent(QEvent.Type.PaletteChange))

    assert "background: transparent;" in widget.styleSheet()
