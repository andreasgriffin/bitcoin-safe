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

import enum
from collections.abc import Iterable, Sequence

from PyQt6.QtWidgets import QComboBox

from ...fx import FX


class CurrencyGroupFormatting(enum.Enum):
    Short = enum.auto()
    Full = enum.auto()


class CurrencyGroup(enum.Enum):
    TOP_FIAT = enum.auto()
    BTC_ONLY = enum.auto()
    BITCOIN_OTHER = enum.auto()
    FIAT = enum.auto()
    CRYPTO = enum.auto()
    Commodity = enum.auto()


class CurrencyComboBox(QComboBox):
    """Helper for populating currency combo boxes."""

    def __init__(
        self,
        fx: FX,
        groups: Sequence[CurrencyGroup],
        formatting: CurrencyGroupFormatting,
    ) -> None:
        super().__init__()
        self.fx = fx
        self.groups = groups
        self.formatting = formatting

    TOP_CURRENCY_CODES: Sequence[str] = (
        "USD",
        "EUR",
        "JPY",
        "GBP",
        "CHF",
        "CNY",
    )

    BITCOIN_OTHER_CODES: Sequence[str] = (
        "BITS",
        "SATS",
    )

    def _format_currency_label(self, code: str, symbol: str, name: str) -> str:
        """Format currency label."""
        display_symbol = symbol or code
        if self.formatting == CurrencyGroupFormatting.Short:
            return f"{code} - {display_symbol.ljust(4)}"
        else:
            return f"{code} - {display_symbol.ljust(4)} - {name}"

    def _available_codes(self, codes: Iterable[str]) -> list[str]:
        """Filter the provided iterable to only include available currency codes."""
        return [code for code in codes if self.fx.get_rate(code)]

    def _add_currency_item(self, code: str) -> None:
        """Add a currency entry to the combo box if data for the code exists."""
        code = FX.sanitize_key(code)
        self.addItem(
            self._format_currency_label(
                code, (self.fx.get_currency_symbol_from_iso(code)), (self.fx.get_currency_name_from_iso(code))
            ),
            code,
        )

    def _build_groups_by_order(self) -> list[list[str]]:
        """Return lists of currency codes grouped according to the given order."""
        groups: list[list[str]] = []
        grouped_codes: set[str] = set()

        def add_group(codes: Iterable[str]) -> None:
            codes_list = [c for c in codes if c not in grouped_codes]
            if codes_list:
                groups.append(codes_list)
                grouped_codes.update(codes_list)

        for item in self.groups:
            if item is CurrencyGroup.TOP_FIAT:
                add_group(self._available_codes(self.TOP_CURRENCY_CODES))

            elif item is CurrencyGroup.BTC_ONLY:
                add_group(self._available_codes(["BTC"]))

            elif item is CurrencyGroup.BITCOIN_OTHER:
                add_group(self._available_codes(self.BITCOIN_OTHER_CODES))

            elif item is CurrencyGroup.FIAT:
                add_group(
                    [
                        code
                        for code, data in sorted(self.fx.list_rates().items())
                        if data.get("type") == "fiat" and code not in grouped_codes
                    ]
                )

            elif item is CurrencyGroup.CRYPTO:
                add_group(
                    [
                        code
                        for code, data in sorted(self.fx.list_rates().items())
                        if data.get("type") == "crypto" and code not in grouped_codes
                    ]
                )
            elif item is CurrencyGroup.Commodity:
                add_group(
                    [
                        code
                        for code, data in sorted(self.fx.list_rates().items())
                        if data.get("type") == "commodity" and code not in grouped_codes
                    ]
                )

        return groups

    def populate(
        self,
        selected_currency: str | None = None,
    ) -> None:
        """Populate the currency combobox with items grouped and ordered by `groups`."""
        self.blockSignals(True)
        try:
            self.clear()

            selected_currency_code = FX.sanitize_key(selected_currency or self.fx.config.currency)

            group_lists = self._build_groups_by_order()

            for group_index, codes in enumerate(group_lists):
                if group_index > 0:
                    self.insertSeparator(self.count())
                for code in codes:
                    self._add_currency_item(code)

            def _find_index(currency: str) -> int:
                """Find the index for a given currency code (case-insensitive)."""
                for index in range(self.count()):
                    data = self.itemData(index)
                    if isinstance(data, str) and FX.sanitize_key(data) == FX.sanitize_key(currency):
                        return index
                return -1

            target_index = _find_index(selected_currency_code)
            if target_index >= 0:
                self.setCurrentIndex(target_index)
        finally:
            self.blockSignals(False)
