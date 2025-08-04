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

from PyQt6.QtWidgets import QComboBox, QFormLayout, QLabel, QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.language_chooser import (
    LanguageChooser,
    create_language_combobox,
)

from ...fx import FX

logger = logging.getLogger(__name__)


class InterfaceSettingsUi(QWidget):
    def __init__(self, fx: FX, language_chooser: LanguageChooser, config: UserConfig, parent=None):
        super().__init__(parent)
        self.fx = fx
        self.config = config
        self.language_chooser = language_chooser

        # 1) Language combo
        self.language_combo = create_language_combobox(language_chooser.get_languages())
        for idx in range(self.language_combo.count()):
            if self.language_combo.itemData(idx) == self.config.language_code:
                self.language_combo.setCurrentIndex(idx)

        # 2) Currency combo
        self.currency_combo = QComboBox()

        # 3) Layout
        form = QFormLayout(self)
        self.label_language = QLabel("")
        self.label_currency = QLabel("")
        form.addRow(self.label_language, self.language_combo)
        form.addRow(self.label_currency, self.currency_combo)

        # 4) initial selection
        self.data_updated()

        # signals
        self.fx.signal_data_updated.connect(self.data_updated)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.currency_combo.currentIndexChanged.connect(self._on_currency_changed)

    def data_updated(self):
        # refill
        rates = self.fx.rates
        if not rates:
            return
        self.currency_combo.clear()

        # --- Add top 5 most-traded currencies ---
        top_currencies = [
            "USD",
            "EUR",
            "JPY",
            "GBP",
            "CHF",
            "CNY",
        ]
        for currency_iso_code in top_currencies:
            data = rates.get(currency_iso_code.lower())
            if not data:
                continue
            currency_locale = self.fx.get_currency_locale(currency_iso_code=currency_iso_code)
            symbol = self.fx.get_currency_symbol(currency_loc=currency_locale)
            name = self.fx.get_currency_name(currency_loc=currency_locale)
            if not name:
                continue
            self.currency_combo.addItem(
                f"{currency_iso_code} - {symbol.ljust(4)} - {name}",
                currency_iso_code.lower(),
            )

        # add a separator before the rest
        self.currency_combo.insertSeparator(self.currency_combo.count())

        # --- Add currencies grouped by type ---
        # Determine unique types excluding crypto
        types = {t for data in rates.values() if isinstance(t := data.get("type"), str)}
        for currency_type in sorted(types, reverse=True):
            # optional: visually separate types
            self.currency_combo.insertSeparator(self.currency_combo.count())
            for currency_iso_code, currency_data in sorted(rates.items()):
                if currency_data.get("type") != currency_type:
                    continue
                if currency_data.get("type") == "crypto" and currency_data.get("name") not in [
                    "Bits",
                    "Satoshi",
                ]:
                    continue
                currency_locale = self.fx.get_currency_locale(currency_iso_code=currency_iso_code)
                symbol = (
                    self.fx.get_currency_symbol(currency_loc=currency_locale)
                    if currency_locale
                    else currency_iso_code
                )
                # no need to check for missing name
                self.currency_combo.addItem(
                    f"{currency_iso_code.upper()} - {symbol.ljust(4)} - {currency_data.get('name')}",
                    currency_iso_code.lower(),
                )

        # restore old selection if still available,
        # otherwise fall back to fx.currency (if valid) or first item
        if self.config.currency.lower() in rates.keys():
            for i in range(self.currency_combo.count()):
                if self.currency_combo.itemData(i) == self.config.currency.lower():
                    self.currency_combo.setCurrentIndex(i)
                    break

    def _on_currency_changed(self, idx: int):
        currency = self.currency_combo.currentData()
        if not currency:
            return
        self.language_chooser.set_currency(currency)

    def _on_language_changed(self, idx: int):
        self.language_chooser.switchLanguage(self.language_combo.itemData(idx))

    def updateUi(self):
        self.label_language.setText("Language")
        self.label_currency.setText("Currency")
