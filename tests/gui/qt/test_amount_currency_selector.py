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

import os

import bdkpython as bdk
import pytest
from pytestqt.qtbot import QtBot

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.amount_currency_selector import AmountCurrencySelector
from bitcoin_safe.signals import Signals
from bitcoin_safe.util import SATOSHIS_PER_BTC

from ...helpers import TestConfig

# Ensure Qt runs headless before the QApplication fixture is created
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _build_fx(config: TestConfig) -> FX:
    # Provide deterministic rates for conversion tests.
    config.currency = "USD"
    config.rates = {
        "BTC": {"name": "Bitcoin", "unit": "BTC", "value": 1.0, "type": "crypto"},
        "USD": {"name": "US Dollar", "unit": "USD", "value": 100_000.0, "type": "fiat"},
        "EUR": {"name": "Euro", "unit": "EUR", "value": 50_000.0, "type": "fiat"},
    }
    return FX(config=config, loop_in_thread=None, update_rates=False)


def _select_currency(selector: AmountCurrencySelector, code: str) -> None:
    """Helper to move the combobox to a specific currency code."""
    idx = selector.currency_combo.findData(code)
    assert idx != -1, f"{code} not available in currency combo"
    selector.currency_combo.setCurrentIndex(idx)


def _expected_btc_sats(fiat_amount: float, rate: float) -> int:
    """Compute sats from a fiat amount using the provided FX rate."""
    return int(round(fiat_amount * SATOSHIS_PER_BTC / rate))


def _expected_fiat_amount(btc_sats: int, rate: float) -> float:
    """Compute fiat amount from sats using the provided FX rate."""
    return btc_sats * rate / SATOSHIS_PER_BTC


def test_auto_conversion_enabled(qtbot: QtBot, test_config: TestConfig) -> None:
    # Auto-conversion should keep BTC sats consistent across fiat changes.
    fx = _build_fx(test_config)
    signals = Signals()

    selector = AmountCurrencySelector(
        network=bdk.Network.REGTEST,
        fx=fx,
        signals=signals,
        auto_fiat_conversions=True,
    )
    qtbot.addWidget(selector)

    # Start in USD, then switch to EUR and BTC while preserving sats.
    starting_usd = 100.0
    usd_rate = fx.rates["USD"]["value"]
    eur_rate = fx.rates["EUR"]["value"]

    selector.set_amount(starting_usd, "USD")
    btc_expected = _expected_btc_sats(starting_usd, usd_rate)
    assert selector.btc_spin.value() == pytest.approx(btc_expected, abs=1)

    _select_currency(selector, "EUR")
    qtbot.wait(10)
    eur_value = selector.fiat_spin.value()
    assert eur_value == pytest.approx(_expected_fiat_amount(btc_expected, eur_rate), rel=1e-6)

    _select_currency(selector, "BTC")
    qtbot.wait(10)
    amount, unit = selector.amount_and_current_iso()
    assert unit == "BTC"
    assert amount == pytest.approx(btc_expected, abs=1)


def test_auto_conversion_disabled(qtbot: QtBot, test_config: TestConfig) -> None:
    # Without auto-conversion, the fiat amount should remain unchanged on switch.
    fx = _build_fx(test_config)
    signals = Signals()

    selector = AmountCurrencySelector(
        network=bdk.Network.REGTEST,
        fx=fx,
        signals=signals,
        auto_fiat_conversions=False,
    )
    qtbot.addWidget(selector)

    # Set an initial USD amount and verify BTC value.
    starting_usd = 100.0
    usd_rate = fx.rates["USD"]["value"]

    selector.set_amount(starting_usd, "USD")
    btc_expected = _expected_btc_sats(starting_usd, usd_rate)
    assert selector.btc_spin.value() == pytest.approx(btc_expected, abs=1)

    _select_currency(selector, "EUR")
    qtbot.wait(10)
    eur_value = selector.fiat_spin.value()
    assert eur_value == pytest.approx(starting_usd)  # no auto conversion

    _select_currency(selector, "BTC")
    qtbot.wait(10)
    amount, unit = selector.amount_and_current_iso()
    assert unit == "BTC"
    assert amount == pytest.approx(btc_expected, abs=1)
