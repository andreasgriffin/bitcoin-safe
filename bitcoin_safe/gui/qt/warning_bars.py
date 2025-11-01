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

import numpy as np
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QSizePolicy

from bitcoin_safe.address_comparer import FuzzyMatch
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.html_utils import html_f

from ...signals import SignalsMin
from .util import adjust_bg_color_for_darkmode

logger = logging.getLogger(__name__)


class LinkingWarningBar(NotificationBar):
    def __init__(self, signals_min: SignalsMin) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=True,
        )
        self.category_dict: dict[str, set[str]] = {}
        self.signals_min = signals_min
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("#FFDF00")))
        self.set_icon(svg_tools.get_QIcon("warning.svg"))

        self.optionalButton.setVisible(False)
        self.icon_label.textLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.setVisible(False)
        self.updateUi()
        self.signals_min.language_switch.connect(self.updateUi)

    def set_category_dict(
        self,
        category_dict: dict[str, set[str]],
    ):
        """Set category dict."""
        self.category_dict = category_dict
        self.setVisible(len(self.category_dict) > 1)
        self.updateUi()

    @classmethod
    def format_category_and_wallet_ids(cls, category: str, wallet_ids: set[str]):
        """Format category and wallet ids."""
        return cls.tr("{category} (in wallet {wallet_ids})").format(
            category=html_f(category, bf=True),
            wallet_ids=", ".join([html_f(wallet_id, bf=True) for wallet_id in wallet_ids]),
        )

    @classmethod
    def get_warning_text(cls, category_dict: dict[str, set[str]]) -> str:
        """Get warning text."""
        s = ",<br>and ".join(
            [
                cls.format_category_and_wallet_ids(category, wallet_ids)
                for category, wallet_ids in category_dict.items()
            ]
        )
        return cls.tr(
            "This transaction combines the coin categories {categories} and makes these categories linkable!"
        ).format(categories=s)

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.icon_label.setText(self.get_warning_text(self.category_dict))


class PoisoningWarningBar(NotificationBar):
    def __init__(self, signals_min: SignalsMin) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=True,
        )
        self.signals_min = signals_min
        self.poisonous_matches: list[tuple[str, str, FuzzyMatch]] = []
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("#FFDF00")))
        self.set_icon(svg_tools.get_QIcon("warning.svg"))

        self.optionalButton.setVisible(False)
        self.icon_label.textLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.setVisible(False)
        self.updateUi()
        self.signals_min.language_switch.connect(self.updateUi)

    def set_poisonous_matches(self, poisonous_matches: list[tuple[str, str, FuzzyMatch]]):
        """Set poisonous matches."""
        self.poisonous_matches = poisonous_matches
        self.setVisible(bool(self.poisonous_matches))
        self.updateUi()

    @classmethod
    def get_warning_text(cls, poisonous_matches: list[tuple[str, str, FuzzyMatch]]) -> str:
        """Get warning text."""

        def add_match(a: str, r: str, bool_array: np.ndarray):
            """Add match."""
            if (i := a.find(r)) is not None:
                bool_array[i : i + len(r)] += 1

        def underline(a: str, bool_array: np.ndarray) -> str:
            """Underline."""
            new_s = ""
            for char, b in zip(a, list(bool_array), strict=False):
                new_s += f"<u>{char}</u>" if b else char
            return new_s

        def underline_text(a1: str, a2: str, match: FuzzyMatch) -> tuple[str, str]:
            """Underline text."""
            bool1 = np.zeros(len(a1))
            bool2 = np.zeros(len(a2))

            for r1, r2 in match.matches:
                add_match(a1, r1, bool1)
                add_match(a2, r2, bool2)

            return underline(a1, bool1.astype(bool)), underline(a2, bool2.astype(bool))

        formatted_addresses = [underline_text(a1, a2, match) for a1, a2, match in poisonous_matches]

        s = "<br>".join([f"{a1} != {a2}" for a1, a2 in formatted_addresses])
        return cls.tr(
            "Warning! This transaction involves deceptively similar addresses. "
            "It may be an address poisoning attack. "
            "Similar addresses are  <br>{addresses}.<br> "
            "Double-check all transaction details carefully!"
        ).format(addresses=s)

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.icon_label.setText(self.get_warning_text(self.poisonous_matches))
