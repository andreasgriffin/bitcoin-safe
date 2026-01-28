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

import logging

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.ui_tx.height_synced_widget import HeightSyncedWidget
from bitcoin_safe.gui.qt.util import HLine, set_no_margins
from bitcoin_safe.html_utils import html_f

logger = logging.getLogger(__name__)


class CurrencySection(QWidget):
    def __init__(
        self, network: bdk.Network, fx: FX, mark_fiat_red_when_exceeding: float | None = None
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.fx = fx
        self.mark_fiat_red_when_exceeding = mark_fiat_red_when_exceeding
        self.network = network
        self.currency_iso: str | None = None

        self._layout = QHBoxLayout(self)
        set_no_margins(self._layout)
        self._layout.setSpacing(3)

        _layout_1 = QVBoxLayout()
        set_no_margins(_layout_1)
        self._layout.addLayout(_layout_1)

        _layout_2 = QVBoxLayout()
        set_no_margins(_layout_2)
        self._layout.addLayout(_layout_2)

        self.l1 = QLabel("", self)
        self.l2 = QLabel("", self)
        self.l1_currency = QLabel("", self)
        self.l2_currency = QLabel("", self)

        _layout_1.addWidget(self.l1, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        _layout_1.addWidget(self.l2, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        _layout_2.addWidget(
            self.l1_currency, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        _layout_2.addWidget(
            self.l2_currency, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

    def set_currency(self, currency_iso: str | None):
        """Set fiat currency override."""
        self.currency_iso = FX.sanitize_key(currency_iso) if currency_iso else None

    def set_amount(self, amount: int | None):
        """Set amount."""
        l1 = self.l1
        l2 = self.l2
        l1_currency = self.l1_currency
        l2_currency = self.l2_currency
        currency_iso = self.currency_iso

        l1.setHidden(amount is None)
        l2.setHidden(amount is None)
        if amount is not None:
            fiat_amount = self.fx.btc_to_fiat(amount=amount, currency=currency_iso)
            l1.setHidden(fiat_amount is None)
            l1_currency.setHidden(fiat_amount is None)
            if fiat_amount is not None:
                if currency_iso:
                    fiat_symbol = self.fx.get_currency_symbol_from_iso(currency_iso)
                    fiat = self.fx.fiat_to_str_custom(
                        fiat_amount=fiat_amount,
                        currency_symbol=fiat_symbol,
                        use_currency_symbol=False,
                    )
                else:
                    fiat, fiat_symbol = self.fx.fiat_to_splitted(fiat_amount=fiat_amount)
                if (
                    self.mark_fiat_red_when_exceeding is not None
                    and fiat_amount >= self.mark_fiat_red_when_exceeding
                ):
                    # make red when dollar amount high
                    fiat = html_f(fiat, bf=True, color="red")
                    fiat_symbol = html_f(fiat_symbol, bf=True, color="red")

                l1.setText(fiat)
                l1_currency.setText(fiat_symbol)

            btc_amount, btc_symbol = Satoshis(amount, network=self.network).format_splitted(
                btc_symbol=self.fx.config.bitcoin_symbol.value
            )

            l2.setText(btc_amount)
            l2_currency.setText(btc_symbol)


class TotalsBox(HeightSyncedWidget):
    def __init__(
        self,
        network: bdk.Network,
        fx: FX,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.fx = fx
        self.network = network

        # Horizontal line across both columns
        line = HLine(self)

        self.c0 = CurrencySection(network=network, fx=fx)
        self.c1 = CurrencySection(network=network, fx=fx)
        self.c2 = CurrencySection(network=network, fx=fx)

        # Grid layout
        self._layout = QGridLayout(self)
        set_no_margins(self._layout)
        self._layout.setSpacing(5)

        self._layout.addWidget(line, 0, 0, 1, 4)

        self._layout.addWidget(
            self.c0, 1, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._layout.addWidget(
            self.c1, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._layout.addWidget(
            self.c2, 1, 3, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        # Make both columns expand evenly
        self._layout.setColumnStretch(0, 0)
        self._layout.setColumnStretch(1, 0)
        self._layout.setColumnStretch(2, 1)  # the empty column
        self._layout.setColumnStretch(3, 0)

        self.setLayout(self._layout)

    def set_amount(self, amount: int | None, alignment=Qt.Edge.RightEdge):
        """Set amount."""
        if alignment == Qt.Edge.LeftEdge:
            c = self.c1
        elif alignment == Qt.Edge.RightEdge:
            c = self.c2
        else:
            return

        c.set_amount(amount=amount)
