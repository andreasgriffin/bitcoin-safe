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

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QEvent, QLocale, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QValidator
from PyQt6.QtWidgets import QAbstractSpinBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.ui_tx.spinbox import AnalyzerSpinBox, BTCSpinBox, parse_btc_str_to_sats


class Signals(QObject):
    language_switch = cast(SignalProtocol[[]], pyqtSignal())


@contextmanager
def default_locale(locale_name: str) -> Iterator[None]:
    """Temporarily install the default locale, because BTCSpinBox parses with it."""
    original = QLocale()
    QLocale.setDefault(QLocale(locale_name))
    try:
        yield
    finally:
        QLocale.setDefault(original)


def btc_spin_box(
    signal_language_switch: SignalProtocol[[]], network: bdk.Network = bdk.Network.BITCOIN
) -> BTCSpinBox:
    """Btc spin box."""
    return BTCSpinBox(
        network=network,
        signal_language_switch=signal_language_switch,
        btc_symbol=BitcoinSymbol.ISO.value,
    )


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
    widget.show()
    qtbot.waitUntil(widget.isVisible)
    line_edit = widget.lineEdit()
    spin_box_background = widget.palette().color(widget.backgroundRole())
    line_edit_background = line_edit.palette().color(line_edit.backgroundRole())

    widget.set_max(True, True)
    qtbot.wait(0)
    assert "background: transparent;" in widget.styleSheet()

    widget.set_max(False, False)
    qtbot.wait(0)

    assert widget.styleSheet() == ""
    assert widget.palette().color(widget.backgroundRole()) == spin_box_background
    assert line_edit.palette().color(line_edit.backgroundRole()) == line_edit_background
    assert widget.hasFrame()
    assert widget.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.UpDownArrows
    assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert not line_edit.isReadOnly()


@pytest.mark.parametrize(
    "locale_name,text,expected_sats",
    [
        # pasting a "foreign" formatted amount: the separator following a leading
        # zero can never be a group separator and must read as a decimal point
        pytest.param("de_DE", "0.001", 100_000, id="dot-paste into german locale"),
        pytest.param("en_US", "0,001", 100_000, id="comma-paste into us locale"),
        pytest.param("de_DE", "0,001", 100_000, id="native german decimal"),
        pytest.param("en_US", "0.001", 100_000, id="native us decimal"),
        pytest.param("de_DE", "1,234.56", 123_456_000_000, id="foreign full paste into german"),
        pytest.param("en_US", "1.234,56", 123_456_000_000, id="foreign full paste into us"),
        # the locale's own notation keeps working
        pytest.param("de_DE", "1.000", 100_000_000_000, id="native german grouping"),
        pytest.param("en_US", "1,000", 100_000_000_000, id="native us grouping"),
        pytest.param("de_DE", "1.234.567", 123_456_700_000_000, id="native german grouping twice"),
        pytest.param("en_US", "1,234,567", 123_456_700_000_000, id="native us grouping twice"),
        pytest.param("de_DE", "1.234,56", 123_456_000_000, id="native german full"),
        pytest.param("en_US", "1,234.56", 123_456_000_000, id="native us full"),
        pytest.param("fr_FR", "1\u202f234,56", 123_456_000_000, id="native french grouping"),
        # unit suffix and the app's own formatting (spaces inside the decimals)
        pytest.param("en_US", "1,234.56 BTC", 123_456_000_000, id="with unit"),
        pytest.param("en_US", "0.5 BTC", 50_000_000, id="half with unit"),
        pytest.param("en_US", "1.00 000 000", 100_000_000, id="app formatted round-trip"),
        pytest.param("de_DE", "1,00 000 000", 100_000_000, id="app formatted round-trip german"),
        pytest.param("en_US", "+1.5", 150_000_000, id="explicit sign"),
        pytest.param("en_US", "0.00001000", 1_000, id="dust"),
        # an empty (or unit-only) field stays 0
        pytest.param("de_DE", "", 0, id="empty"),
        pytest.param("en_US", "   ", 0, id="whitespace only"),
        pytest.param("en_US", "BTC", 0, id="unit only"),
    ],
)
def test_parse_btc_str_to_sats(locale_name: str, text: str, expected_sats: int) -> None:
    with default_locale(locale_name):
        assert (
            parse_btc_str_to_sats(text, network=bdk.Network.BITCOIN, btc_symbol=BitcoinSymbol.ISO.value)
            == expected_sats
        )


@pytest.mark.parametrize(
    "locale_name,text",
    [
        pytest.param("de_DE", "abc", id="letters"),
        pytest.param("de_DE", "1..2", id="empty group"),
        pytest.param("de_DE", "1.2345.678", id="bad group width"),
        pytest.param("de_DE", ".234.567", id="group before leading digits"),
        pytest.param("en_US", "1.2.3", id="several decimal points"),
        pytest.param("en_US", "1,2.3,4", id="mixed garbage"),
        pytest.param("en_US", ".", id="lone decimal point"),
        pytest.param("en_US", "1.2a", id="trailing garbage"),
        pytest.param("en_US", "1e5", id="exponent"),
        pytest.param("en_US", "1_000", id="python style grouping"),
    ],
)
def test_parse_btc_str_to_sats_rejects_garbage(locale_name: str, text: str) -> None:
    with default_locale(locale_name):
        with pytest.raises(ValueError):
            parse_btc_str_to_sats(text, network=bdk.Network.BITCOIN, btc_symbol=BitcoinSymbol.ISO.value)


def test_btc_spinbox_parses_pasted_foreign_amount(qtbot: QtBot) -> None:
    "A german locale user pasting '0.001' must not be sent 1000x too much."
    with default_locale("de_DE"):
        signals = Signals()
        widget = btc_spin_box(signal_language_switch=signals.language_switch)
        qtbot.addWidget(widget)

        widget.lineEdit().setText("0.001")
        widget.interpretText()

        assert widget.value() == 100_000
        state, _, _ = widget.validate("0.001", 0)
        assert state == QValidator.State.Acceptable


def test_btc_spinbox_rejects_garbage_instead_of_zeroing(qtbot: QtBot) -> None:
    with default_locale("en_US"):
        signals = Signals()
        widget = btc_spin_box(signal_language_switch=signals.language_switch)
        qtbot.addWidget(widget)

        widget.setValue(100_000)
        state, _, _ = widget.validate("12abc", 0)

        assert state == QValidator.State.Invalid
        assert widget.value() == 100_000


@pytest.mark.parametrize("locale_name", ["en_US", "de_DE", "fr_FR", "ar_EG", "de_CH", "ru_RU"])
@pytest.mark.parametrize("sats", [0, 1, 100_000, 123_456_789_123, 2_100_000_000_000_000])
def test_btc_spinbox_text_round_trip(qtbot: QtBot, locale_name: str, sats: int) -> None:
    with default_locale(locale_name):
        signals = Signals()
        widget = btc_spin_box(signal_language_switch=signals.language_switch)
        qtbot.addWidget(widget)

        widget.setValue(sats)

        assert widget.valueFromText(widget.text()) == sats
