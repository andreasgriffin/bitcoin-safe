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

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol
from pytestqt.qtbot import QtBot

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.currency_converter import CurrencyConverter
from bitcoin_safe.gui.qt.ui_tx.spinbox import BTCSpinBox, FiatSpinBox
from bitcoin_safe.util import SATOSHIS_PER_BTC

from ...helpers import TestConfig


def test_conversions(
    qtbot: QtBot,
    test_config: TestConfig,
) -> None:
    # Provide deterministic rates across a wide currency list.
    fx = FX(config=test_config, loop_in_thread=None, update_rates=False)
    fx.rates = {
        "AED": {"name": "United Arab Emirates Dirham", "type": "fiat", "unit": "DH", "value": 335019.905},
        "AMD": {"name": "Armenian Dram", "type": "fiat", "unit": "\u058f", "value": 34741452.395},
        "ARS": {"name": "Argentine Peso", "type": "fiat", "unit": "$", "value": 131364739.576},
        "AUD": {"name": "Australian Dollar", "type": "fiat", "unit": "A$", "value": 137448.473},
        "BAM": {
            "name": "Bosnia and Herzegovina Convertible Mark",
            "type": "fiat",
            "unit": "KM",
            "value": 153138.077,
        },
        "BCH": {"name": "Bitcoin Cash", "type": "crypto", "unit": "BCH", "value": 157.237},
        "BDT": {"name": "Bangladeshi Taka", "type": "fiat", "unit": "\u09f3", "value": 11155117.157},
        "BHD": {"name": "Bahraini Dinar", "type": "fiat", "unit": "BD", "value": 34389.052},
        "BITS": {"name": "Bits", "type": "crypto", "unit": "\u03bcBTC", "value": 1000000.0},
        "BMD": {"name": "Bermudian Dollar", "type": "fiat", "unit": "$", "value": 91223.936},
        "BNB": {"name": "Binance Coin", "type": "crypto", "unit": "BNB", "value": 102.041},
        "BRL": {"name": "Brazil Real", "type": "fiat", "unit": "R$", "value": 484490.325},
        "BTC": {"name": "Bitcoin", "type": "crypto", "unit": "BTC", "value": 1.0},
        "CAD": {"name": "Canadian Dollar", "type": "fiat", "unit": "CA$", "value": 127138.982},
        "CHF": {"name": "Swiss Franc", "type": "fiat", "unit": "Fr.", "value": 73363.019},
        "CLP": {"name": "Chilean Peso", "type": "fiat", "unit": "CLP$", "value": 83795571.057},
        "CNY": {"name": "Chinese Yuan", "type": "fiat", "unit": "\u00a5", "value": 644980.595},
        "COP": {"name": "Colombian Peso", "type": "fiat", "unit": "$", "value": 348469962.084},
        "CRC": {"name": "Costa Rican Col\u00f3n", "type": "fiat", "unit": "\u20a1", "value": 44544568.858},
        "CZK": {"name": "Czech Koruna", "type": "fiat", "unit": "K\u010d", "value": 1896454.5},
        "DKK": {"name": "Danish Krone", "type": "fiat", "unit": "kr.", "value": 585078.854},
        "DOP": {"name": "Dominican Peso", "type": "fiat", "unit": "RD$", "value": 5809738.674},
        "DOT": {"name": "Polkadot", "type": "crypto", "unit": "DOT", "value": 40756.493},
        "EOS": {"name": "EOS", "type": "crypto", "unit": "EOS", "value": 488624.859},
        "ETH": {"name": "Ether", "type": "crypto", "unit": "ETH", "value": 29.147},
        "EUR": {"name": "Euro", "type": "fiat", "unit": "\u20ac", "value": 78336.457},
        "GBP": {"name": "British Pound Sterling", "type": "fiat", "unit": "\u00a3", "value": 68365.407},
        "GEL": {"name": "Georgian Lari", "type": "fiat", "unit": "\u20be", "value": 246304.627},
        "GTQ": {"name": "Guatemalan Quetzal", "type": "fiat", "unit": "Q", "value": 698509.341},
        "HKD": {"name": "Hong Kong Dollar", "type": "fiat", "unit": "HK$", "value": 710150.063},
        "HNL": {"name": "Honduran Lempira", "type": "fiat", "unit": "L", "value": 2401757.014},
        "HUF": {"name": "Hungarian Forint", "type": "fiat", "unit": "Ft", "value": 29907137.575},
        "IDR": {"name": "Indonesian Rupiah", "type": "fiat", "unit": "Rp", "value": 1520741205.666},
        "ILS": {"name": "Israeli New Shekel", "type": "fiat", "unit": "\u20aa", "value": 294757.765},
        "INR": {"name": "Indian Rupee", "type": "fiat", "unit": "\u20b9", "value": 8203587.227},
        "JPY": {"name": "Japanese Yen", "type": "fiat", "unit": "\u00a5", "value": 14159943.577},
        "KES": {"name": "Kenyan Shilling", "type": "fiat", "unit": "KSh", "value": 11794342.685},
        "KRW": {"name": "South Korean Won", "type": "fiat", "unit": "\u20a9", "value": 134336957.361},
        "KWD": {"name": "Kuwaiti Dinar", "type": "fiat", "unit": "KD", "value": 27999.271},
        "LBP": {"name": "Lebanese Pound", "type": "fiat", "unit": "\u0644.\u0644", "value": 8164644626.533},
        "LINK": {"name": "Chainlink", "type": "crypto", "unit": "LINK", "value": 6513.112},
        "LKR": {"name": "Sri Lankan Rupee", "type": "fiat", "unit": "Rs", "value": 28127514.026},
        "LTC": {"name": "Litecoin", "type": "crypto", "unit": "LTC", "value": 1106.721},
        "MMK": {"name": "Burmese Kyat", "type": "fiat", "unit": "K", "value": 191542898.798},
        "MXN": {"name": "Mexican Peso", "type": "fiat", "unit": "MX$", "value": 1660063.177},
        "MYR": {"name": "Malaysian Ringgit", "type": "fiat", "unit": "RM", "value": 375021.601},
        "NGN": {"name": "Nigerian Naira", "type": "fiat", "unit": "\u20a6", "value": 132323056.148},
        "NOK": {"name": "Norwegian Krone", "type": "fiat", "unit": "kr", "value": 920836.305},
        "NZD": {"name": "New Zealand Dollar", "type": "fiat", "unit": "NZ$", "value": 157915.566},
        "PEN": {"name": "Peruvian Sol", "type": "fiat", "unit": "S/", "value": 306526.656},
        "PHP": {"name": "Philippine Peso", "type": "fiat", "unit": "\u20b1", "value": 5383170.085},
        "PKR": {"name": "Pakistani Rupee", "type": "fiat", "unit": "\u20a8", "value": 25829144.104},
        "PLN": {"name": "Polish Zloty", "type": "fiat", "unit": "z\u0142", "value": 331549.382},
        "RON": {"name": "Romanian Leu", "type": "fiat", "unit": "lei", "value": 398931.395},
        "RUB": {"name": "Russian Ruble", "type": "fiat", "unit": "\u20bd", "value": 7001621.1},
        "SAR": {"name": "Saudi Riyal", "type": "fiat", "unit": "SR", "value": 342375.838},
        "SATS": {"name": "Satoshi", "type": "crypto", "unit": "sats", "value": 100000000.0},
        "SEK": {"name": "Swedish Krona", "type": "fiat", "unit": "kr", "value": 858515.396},
        "SGD": {"name": "Singapore Dollar", "type": "fiat", "unit": "S$", "value": 118171.03},
        "SOL": {"name": "Solana", "type": "crypto", "unit": "SOL", "value": 666.84},
        "SVC": {"name": "Salvadoran Col\u00f3n", "type": "fiat", "unit": "\u20a1", "value": 797822.924},
        "TBTC": {"name": "Bitcoin", "type": "crypto", "unit": "tBTC", "value": 1.0},
        "THB": {"name": "Thai Baht", "type": "fiat", "unit": "\u0e3f", "value": 2905527.979},
        "TRY": {"name": "Turkish Lira", "type": "fiat", "unit": "\u20ba", "value": 3878258.115},
        "TSAT": {"name": "Satoshis", "type": "crypto", "unit": "tSat", "value": 100000000.0},
        "TSATS": {"name": "Satoshis", "type": "crypto", "unit": "tSats", "value": 100000000.0},
        "TWD": {"name": "New Taiwan Dollar", "type": "fiat", "unit": "NT$", "value": 2853804.007},
        "UAH": {"name": "Ukrainian hryvnia", "type": "fiat", "unit": "\u20b4", "value": 3855045.728},
        "USD": {"name": "US Dollar", "type": "fiat", "unit": "$", "value": 91223.936},
        "VEF": {"name": "Venezuelan bol\u00edvar fuerte", "type": "fiat", "unit": "Bs.F", "value": 9134.252},
        "VND": {
            "name": "Vietnamese \u0111\u1ed3ng",
            "type": "fiat",
            "unit": "\u20ab",
            "value": 2405062948.413,
        },
        "XAG": {"name": "Silver - Troy Ounce", "type": "commodity", "unit": "XAG", "value": 1575.414},
        "XAU": {"name": "Gold - Troy Ounce", "type": "commodity", "unit": "XAU", "value": 21.594},
        "XAUG": {"name": "Gold - Gram (g)", "type": "commodity", "unit": "XAUg", "value": 671.5734000000001},
        "XAUKG": {
            "name": "Gold - Kilogram (kg)",
            "type": "commodity",
            "unit": "XAUkg",
            "value": 0.6715734000000001,
        },
        "XDR": {"name": "IMF Special Drawing Rights", "type": "fiat", "unit": "XDR", "value": 63858.579},
        "XLM": {"name": "Lumens", "type": "crypto", "unit": "XLM", "value": 365697.834},
        "XRP": {"name": "XRP", "type": "crypto", "unit": "XRP", "value": 44029.807},
        "YFI": {"name": "Yearn.finance", "type": "crypto", "unit": "YFI", "value": 23.899},
        "ZAR": {"name": "South African Rand", "type": "fiat", "unit": "R", "value": 1544539.739},
        "ZMW": {"name": "Zambian Kwacha", "type": "fiat", "unit": "ZK", "value": 2100588.488},
    }
    btc_spin = BTCSpinBox(
        network=bdk.Network.REGTEST,
        signal_language_switch=fx.signal_data_updated,
        btc_symbol=BitcoinSymbol.ISO.value,
    )
    fiat_spin = FiatSpinBox(
        fx=fx,
        signal_currency_changed=fx.signal_data_updated,
        signal_language_switch=fx.signal_data_updated,
    )
    qtbot.addWidget(btc_spin)
    qtbot.addWidget(fiat_spin)

    # Wire up the converter to keep the two spin boxes in sync.
    converter = CurrencyConverter(btc_spin, fiat_spin)
    assert isinstance(converter, CurrencyConverter)

    # Setting BTC should update fiat across all currencies.
    btc_value = 123456
    btc_spin.setValue(btc_value)

    for currency_iso in fx.rates:
        fiat_spin.setCurrencyCode(currency_iso)
        assert fiat_spin.value() == pytest.approx(
            btc_value * fx.rates[fx.sanitize_key(currency_iso)]["value"] / SATOSHIS_PER_BTC, abs=1e-1
        )

    # Setting fiat should update BTC across all currencies.
    fiat_value = 34567
    for currency_iso in fx.rates:
        fiat_spin.setCurrencyCode(currency_iso)
        fiat_spin.setValue(fiat_value)
        assert btc_spin.value() == pytest.approx(
            fiat_value * SATOSHIS_PER_BTC / fx.rates[fx.sanitize_key(currency_iso)]["value"], abs=1
        )
