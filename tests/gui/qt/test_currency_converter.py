#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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


from __future__ import annotations
from pytestqt.qtbot import QtBot

import pytest
import bdkpython as bdk
from PyQt6.QtCore import QLocale, QObject, pyqtSignal
from typing import Optional, Tuple

from bitcoin_safe.gui.qt.currency_converter import CurrencyConverter
from bitcoin_safe.gui.qt.ui_tx.spinbox import BTCSpinBox, FiatSpinBox


class DummyConfig:
    def __init__(self, currency: str = "USD") -> None:
        self.currency: str = currency


class DummyFX(QObject):
    """FX stub mirroring methods used by real spin boxes and converter."""

    signal_data_updated = pyqtSignal()
    signal_currency_changed = pyqtSignal()

    rate: float
    last_currency: Optional[str]
    config: DummyConfig

    def __init__(self, rate: float, currency: str = "USD") -> None:
        super().__init__()
        self.rate = rate
        self.last_currency = None
        self.config = DummyConfig(currency)

    def get_currency_iso(self, currency_loc: Optional[str] = None) -> str:
        return self.config.currency

    def get_currency_locale(self, currency_code: Optional[str]) -> QLocale:
        return QLocale()

    def get_locale(self) -> QLocale:
        return QLocale()

    def get_currency_symbol(self, currency_loc: Optional[str] = None) -> str:
        return "$"

    def fiat_to_str_custom(self, fiat_value: float, **_: object) -> str:
        return f"{fiat_value:.2f}"

    def parse_fiat_custom(self, formatted: str, **_: object) -> float:
        return float(formatted)

    def btc_to_fiat(self, amount: int, currency: Optional[str] = None) -> float:
        self.last_currency = currency or self.config.currency
        return amount / 1e8 * self.rate

    def fiat_to_btc(self, fiat: float, currency: Optional[str] = None) -> int:
        self.last_currency = currency or self.config.currency
        return int(1e8 * fiat / self.rate)


@pytest.fixture
def spin_boxes(qtbot: QtBot) -> Tuple[DummyFX, BTCSpinBox, FiatSpinBox]:
    fx = DummyFX(rate=20_000)
    btc_spin = BTCSpinBox(network=bdk.Network.REGTEST, signal_language_switch=fx.signal_data_updated)
    fiat_spin = FiatSpinBox(
        fx=fx,
        signal_currency_changed=fx.signal_currency_changed,
        signal_language_switch=fx.signal_data_updated,
    )
    qtbot.addWidget(btc_spin)
    qtbot.addWidget(fiat_spin)
    return fx, btc_spin, fiat_spin


def test_btc_updates_fiat(qtbot: QtBot, spin_boxes: Tuple[DummyFX, BTCSpinBox, FiatSpinBox]) -> None:
    fx, btc_spin, fiat_spin = spin_boxes
    converter = CurrencyConverter(fx, btc_spin, fiat_spin)

    btc_value: int = 200_000_000  # 2 BTC in satoshis
    btc_spin.setValue(btc_value)
    converter._on_bitcoin_changed(btc_spin.value())

    assert fiat_spin.value() == pytest.approx(btc_value / 1e8 * fx.rate)
    assert fx.last_currency == "USD"


def test_fiat_updates_btc(qtbot: QtBot, spin_boxes: Tuple[DummyFX, BTCSpinBox, FiatSpinBox]) -> None:
    fx, btc_spin, fiat_spin = spin_boxes
    fx.rate = 25_000
    converter = CurrencyConverter(fx, btc_spin, fiat_spin)

    fiat_value: float = 12_500
    fiat_spin.setValue(fiat_value)
    converter._on_fiat_changed(fiat_spin.value())

    assert btc_spin.value() == fx.fiat_to_btc(fiat_value)
    assert fx.last_currency == "USD"


def test_currency_change_updates_fiat(
    qtbot: QtBot, spin_boxes: Tuple[DummyFX, BTCSpinBox, FiatSpinBox]
) -> None:
    fx, btc_spin, fiat_spin = spin_boxes
    converter = CurrencyConverter(fx, btc_spin, fiat_spin)

    btc_value: int = 200_000_000  # 2 BTC in satoshis
    btc_spin.setValue(btc_value)
    converter._on_bitcoin_changed(btc_spin.value())

    fx.rate = 30_000
    fx.config.currency = "EUR"
    fx.signal_currency_changed.emit()

    assert fiat_spin.value() == pytest.approx(btc_value / 1e8 * fx.rate)
    assert fx.last_currency == "EUR"
