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
from typing import Iterable, Sequence

from PyQt6.QtWidgets import QComboBox, QFormLayout, QLabel, QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.language_chooser import (
    LanguageChooser,
    create_language_combobox,
)

from ...fx import FX

logger = logging.getLogger(__name__)

TOP_CURRENCY_CODES: Sequence[str] = (
    "USD",
    "EUR",
    "JPY",
    "GBP",
    "CHF",
    "CNY",
)

BITCOIN_CURRENCY_CODES: Sequence[str] = (
    "btc",
    "bits",
    "sats",
)


def _format_currency_label(code_upper: str, symbol: str, name: str) -> str:
    display_symbol = symbol or code_upper
    return f"{code_upper} - {display_symbol.ljust(4)} - {name}"


def _available_codes(rates: dict[str, dict], codes: Iterable[str]) -> list[str]:
    return [code.lower() for code in codes if rates.get(code.lower())]


def _add_currency_item(combo: QComboBox, fx: FX, code_lower: str) -> None:
    data = fx.rates.get(code_lower)
    if not data:
        return

    code_upper = code_lower.upper()
    currency_locale = fx.get_currency_locale(currency_iso_code=code_upper)

    symbol = ""
    if currency_locale:
        symbol = fx.get_currency_symbol(currency_loc=currency_locale) or ""
    if not symbol:
        symbol = data.get("unit") or code_upper
    name = data.get("name")
    if not name and currency_locale:
        name = fx.get_currency_name(currency_loc=currency_locale)
    if not name:
        name = code_upper

    combo.addItem(_format_currency_label(code_upper, str(symbol), str(name)), code_lower)


def populate_currency_combobox(
    combo: QComboBox,
    fx: FX,
    *,
    selected_currency: str | None = None,
) -> None:
    combo.blockSignals(True)
    try:
        combo.clear()

        rates = fx.rates
        if not rates:
            return

        selected_lower = (selected_currency or fx.config.currency).lower()

        groups: list[list[str]] = []
        grouped_codes: set[str] = set()

        top_group = _available_codes(rates, TOP_CURRENCY_CODES)
        if top_group:
            groups.append(top_group)
            grouped_codes.update(top_group)

        bitcoin_group = _available_codes(rates, BITCOIN_CURRENCY_CODES)
        if bitcoin_group:
            groups.append(bitcoin_group)
            grouped_codes.update(bitcoin_group)

        types = sorted(
            {
                currency_type
                for currency_data in rates.values()
                if isinstance(currency_type := currency_data.get("type"), str)
            },
            reverse=True,
        )

        for currency_type in types:
            type_codes = [
                code
                for code, data in sorted(rates.items())
                if data.get("type") == currency_type and code not in grouped_codes
            ]
            if not type_codes:
                continue
            groups.append(type_codes)
            grouped_codes.update(type_codes)

        for group_index, group in enumerate(groups):
            if group_index > 0:
                combo.insertSeparator(combo.count())
            for code in group:
                _add_currency_item(combo, fx, code)

        def _find_index(currency: str) -> int:
            currency_lower = currency.lower()
            for index in range(combo.count()):
                data = combo.itemData(index)
                if isinstance(data, str) and data.lower() == currency_lower:
                    return index
            return -1

        target_index = _find_index(selected_lower)
        if target_index < 0:
            target_index = _find_index(fx.config.currency)
        if target_index < 0:
            target_index = _find_index("btc")
        if target_index < 0 and combo.count():
            target_index = 0

        if target_index >= 0:
            combo.setCurrentIndex(target_index)
    finally:
        combo.blockSignals(False)


def create_currency_combobox(
    fx: FX,
    *,
    selected_currency: str | None = None,
    parent: QWidget | None = None,
) -> QComboBox:
    combo = QComboBox(parent)
    populate_currency_combobox(combo, fx, selected_currency=selected_currency)
    return combo


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
        self.currency_combo = create_currency_combobox(
            self.fx, selected_currency=self.config.currency, parent=self
        )

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
        current_data = self.currency_combo.currentData()
        selected = current_data if isinstance(current_data, str) else self.config.currency
        populate_currency_combobox(self.currency_combo, self.fx, selected_currency=selected)

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
