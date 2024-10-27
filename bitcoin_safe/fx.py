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
from typing import Dict

from bitcoin_safe.threading_manager import ThreadingManager

logger = logging.getLogger(__name__)


from PyQt6.QtCore import QLocale, QObject, pyqtSignal

from .mempool import threaded_fetch


class FX(QObject, ThreadingManager):
    signal_data_updated = pyqtSignal()

    def __init__(self, threading_parent: ThreadingManager | None = None) -> None:
        super().__init__(threading_parent=threading_parent)  # type: ignore

        self.rates: Dict[str, Dict] = {}
        self.update()
        logger.debug(f"initialized {self}")

    def update_if_needed(self) -> None:
        if self.rates:
            return
        self.update()

    @staticmethod
    def format_dollar(amount: float, prepend_dollar_sign=True) -> str:
        symbol = "$"
        locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        formatted_amount = locale.toCurrencyString(amount, symbol=symbol)
        if not prepend_dollar_sign:
            formatted_amount = formatted_amount.lstrip(symbol)
        return formatted_amount

    def to_fiat(self, currency: str, amount: int) -> float | None:
        currency = currency.lower()
        if currency not in self.rates:
            return None

        dollar_amount = self.rates[currency]["value"] / 1e8 * amount
        return dollar_amount

    def to_fiat_str(self, currency: str, amount: int) -> str:
        dollar_amount = self.to_fiat(currency, amount)
        if dollar_amount is None:
            return ""
        return self.format_dollar(dollar_amount)

    def update(self) -> None:
        def on_success(data) -> None:
            if not data:
                logger.debug(f"empty result of https://api.coingecko.com/api/v3/exchange_rates")
                return
            self.rates = data.get("rates", {})
            if self.rates:
                self.signal_data_updated.emit()

        self.append_thread(
            threaded_fetch(
                "https://api.coingecko.com/api/v3/exchange_rates",
                on_success,
            )
        )
