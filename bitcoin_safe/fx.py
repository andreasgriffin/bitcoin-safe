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


import logging
from functools import lru_cache
from typing import Any, Dict, Tuple, cast

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtCore import QLocale, QObject, pyqtSignal

from bitcoin_safe.config import UserConfig
from bitcoin_safe.mempool_manager import fetch_from_url
from bitcoin_safe.network_utils import ProxyInfo

from .signals import TypedPyQtSignalNo

logger = logging.getLogger(__name__)


class FX(QObject):
    signal_data_updated = cast(TypedPyQtSignalNo, pyqtSignal())

    def __init__(self, config: UserConfig) -> None:
        super().__init__()  # type: ignore
        self.loop_in_thread = LoopInThread()
        self.config = config
        self.rates: Dict[str, Dict[str, Any]] = config.rates.copy()
        self.update()
        logger.debug(f"initialized {self.__class__.__name__}")

    @staticmethod
    def get_locale() -> QLocale:
        return QLocale()

    @staticmethod
    @lru_cache(maxsize=200_000)
    def _get_currency_locale(currency_iso_code: str) -> QLocale | None:
        # look through every country’s locale to find the currency_symbol
        for country in QLocale.Country:
            if country == QLocale.Country.AnyCountry:
                continue
            currency_loc = QLocale(QLocale.Language.AnyLanguage, country)
            if FX._get_currency_iso(currency_loc) == currency_iso_code.upper():
                return currency_loc
        return None

    @staticmethod
    def _get_currency_iso(currency_loc: QLocale):
        return currency_loc.currencySymbol(QLocale.CurrencySymbolFormat.CurrencyIsoCode).upper()

    def get_currency_locale(self, currency_iso_code: str | None = None) -> QLocale | None:
        return self._get_currency_locale(currency_iso_code if currency_iso_code else self.config.currency)

    def get_currency_iso(self, currency_loc: QLocale | None = None):
        currency_loc = currency_loc if currency_loc else self.get_currency_locale()
        if not currency_loc:
            return self.config.currency.upper()
        return self._get_currency_iso(currency_loc)

    def get_currency_symbol(self, currency_loc: QLocale | None = None):
        currency_loc = currency_loc if currency_loc else self.get_currency_locale()
        if not currency_loc:
            return self.config.currency.upper()
        return currency_loc.currencySymbol(
            QLocale.CurrencySymbolFormat.CurrencySymbol
        ) or self.get_currency_iso(currency_loc=currency_loc)

    def get_currency_name(self, currency_loc: QLocale | None = None):
        currency_loc = currency_loc if currency_loc else self.get_currency_locale()
        if not currency_loc:
            return self.config.currency.upper()
        return currency_loc.currencySymbol(
            QLocale.CurrencySymbolFormat.CurrencyDisplayName
        ) or self.get_currency_iso(currency_loc=currency_loc)

    def close(self):
        self.loop_in_thread.stop()
        logger.debug(f"{self.__class__.__name__} close")

    def update_if_needed(self) -> None:
        if self.rates:
            return
        self.update()

    def fiat_to_str_custom(
        self, fiat_amount: float, locale: QLocale, currency_symbol: str, use_currency_symbol=True
    ) -> str:
        formatted_amount = locale.toCurrencyString(fiat_amount)
        locale_symbol = self.get_currency_symbol(currency_loc=locale)
        new_symbol = currency_symbol if use_currency_symbol else ""
        if len(new_symbol) >= 3:
            # append long symbols at the end
            formatted_amount = formatted_amount.replace(locale_symbol, "") + " " + new_symbol
        else:
            formatted_amount = formatted_amount.replace(locale_symbol, new_symbol)

        return formatted_amount

    def fiat_to_str(self, fiat_amount: float, use_currency_symbol=True) -> str:
        locale = self.get_locale()
        currency_symbol = self.get_currency_symbol()
        return self.fiat_to_str_custom(
            locale=locale,
            currency_symbol=currency_symbol,
            fiat_amount=fiat_amount,
            use_currency_symbol=use_currency_symbol,
        )

    def fiat_to_splitted(self, fiat_amount: float) -> Tuple[str, str]:
        currency_symbol = self.get_currency_symbol()
        formatted_amount = self.fiat_to_str(fiat_amount=fiat_amount, use_currency_symbol=False)
        return formatted_amount, currency_symbol

    def parse_fiat(self, formatted: str) -> float | None:
        """
        Parse a string like '$1,234.56' (or '1,234.56') back into a float.
        Returns None if parsing fails.
        """
        locale = self.get_locale()
        currency_symbol = self.get_currency_symbol()
        return self.parse_fiat_custom(formatted=formatted, locale=locale, currency_symbol=currency_symbol)

    def parse_fiat_custom(self, formatted: str, locale: QLocale, currency_symbol: str) -> float | None:
        """
        Parse a string like '$1,234.56' (or '1,234.56') back into a float.
        Returns None if parsing fails.
        """
        text = formatted.strip()

        # get the locale’s thousands‐separator character
        sep = locale.groupSeparator()

        # default "0" if text is None, then strip out all group‐separators
        text = (text or "0").replace(sep, "")

        # remove symbol if present
        text = text.strip(currency_symbol).strip()

        # Now use QLocale.toDouble to respect the grouping & decimal separators
        value, ok = locale.toDouble(text)
        return value if ok else None

    def fiat_to_btc(self, fiat: float, currency: str | None = None) -> int | None:
        if not (rate := self.rates.get(currency.lower() if currency else self.config.currency.lower())):
            return None

        return int(1e8 * fiat / rate["value"])

    def btc_to_fiat(self, amount: int, currency: str | None = None) -> float | None:
        if not (rate := self.rates.get(currency.lower() if currency else self.config.currency.lower())):
            return None

        fiat_amount = rate["value"] / 1e8 * amount
        return fiat_amount

    def btc_to_fiat_str(self, amount: int, use_currency_symbol=True) -> str:
        fiat_value = self.btc_to_fiat(amount)
        if fiat_value is None:
            return ""
        return self.fiat_to_str(fiat_value, use_currency_symbol=use_currency_symbol)

    def btc_to_fiat_splitted(self, amount: int) -> Tuple[str, str]:
        fiat_amount = self.btc_to_fiat(amount)
        if fiat_amount is None:
            return "", ""
        return self.fiat_to_splitted(fiat_amount)

    def update(self) -> None:
        self._task_set_data = self.loop_in_thread.run_background(self._update())

    def add_additional_rates(self, rates: Dict):
        # gold entry: {'name': 'Gold - Troy Ounce', 'unit': 'XAU', 'value': 35.399, 'type': 'commodity'}

        xau = rates.get("xau")
        if xau:
            rates["xaug"] = {
                "name": "Gold - Gram (g)",
                "unit": "XAUg",
                "value": xau["value"] * 31.10,
                "type": "commodity",
            }
            rates["xaukg"] = {
                "name": "Gold - Kilogram (kg)",
                "unit": "XAUkg",
                "value": xau["value"] * 31.10 / 1000,
                "type": "commodity",
            }

        sats = rates.get("sats")
        if sats:
            rates["tsat"] = {
                "name": "Satoshis",
                "unit": "tSat",
                "value": sats["value"],
                "type": "crypto",
            }
            rates["tsats"] = {
                "name": "Satoshis",
                "unit": "tSats",
                "value": sats["value"],
                "type": "crypto",
            }

        btc = rates.get("btc")
        if btc:
            rates["tbtc"] = {
                "name": "Bitcoin",
                "unit": "tBTC",
                "value": btc["value"],
                "type": "crypto",
            }

    async def _update(self) -> None:
        data = await fetch_from_url(
            "https://api.coingecko.com/api/v3/exchange_rates",
            proxies=(
                ProxyInfo.parse(self.config.network_config.proxy_url).get_requests_proxy_dict()
                if self.config.network_config.proxy_url
                else None
            ),
        )
        if not data:
            logger.debug(f"empty result of https://api.coingecko.com/api/v3/exchange_rates")
            return
        self.rates = data.get("rates", {})
        self.add_additional_rates(self.rates)
        if self.rates:
            self.signal_data_updated.emit()
