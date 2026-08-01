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

from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractSpinBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.ui_tx.spinbox import AnalyzerSpinBox, BTCSpinBox


class Signals(QObject):
    language_switch = cast(SignalProtocol[[]], pyqtSignal())


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


def test_btc_spinbox_restores_editable_style_after_send_max(qtbot: QtBot) -> None:
    signals = Signals()
    widget = BTCSpinBox(
        network=bdk.Network.REGTEST,
        signal_language_switch=signals.language_switch,
        btc_symbol=BitcoinSymbol.ISO.value,
    )
    qtbot.addWidget(widget)

    widget.set_max(True, True)
    assert "background: transparent;" in widget.styleSheet()

    widget.set_max(False, False)

    assert widget.styleSheet() == ""
    assert widget.hasFrame()
    assert widget.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.UpDownArrows
    assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert not widget.lineEdit().isReadOnly()
