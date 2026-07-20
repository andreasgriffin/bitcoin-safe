#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
#

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.card_base import CardBase, CardExpansionMode
from bitcoin_safe.gui.qt.util import to_color_name
from bitcoin_safe.tx import short_tx_id

TUTORIAL_TX_ICON_RECOGNIZED = "confirmed.svg"
TUTORIAL_TX_ICON_SEND = "bi--send.svg"
TUTORIAL_TX_ICON_WAITING = "bi--hourglass-split.svg"


def completed_tx_subtitle(owner: QObject, txid: str) -> str:
    """Return the shared subtitle for a recognized tutorial transaction."""
    return owner.tr("Successfully completed! txid: {txid}").format(
        txid=f"<span style='text-decoration: underline;'>{(txid)}</span>"
    )


def pending_tx_subtitle(owner: QObject, txid: str) -> str:
    """Return the shared subtitle for a pending tutorial transaction."""
    return owner.tr("Pending - txid {txid}").format(txid=short_tx_id(txid))


@dataclass
class TutorialTxCardState:
    title: str
    subtitle: str
    icon_name: str
    expansion_mode: CardExpansionMode
    clickable: bool
    expanded: bool
    hidden: bool = False


class TutorialTxCard(CardBase):
    signal_header_activated = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        self.cached_background_color: QColor | str | None = None
        super().__init__(parent=parent, expansion_mode=CardExpansionMode.FIXED_EXPANDED)
        self.header_icon.setFixedSize(28, 28)
        self.signal_header_clicked.connect(self.signal_header_activated.emit)

    def _get_style_content(self):
        border_color = self.palette().color(QPalette.ColorRole.Mid) if self._expanded else "#00000000"

        if self.background_color:
            self.cached_background_color = self.background_color
        self.background_color = None if self._expanded else self.cached_background_color
        s = super()._get_style_content()
        s += f"\nborder: 1px solid {to_color_name(border_color)};"
        return s

    def set_expanded(self, expanded: bool) -> None:
        super().set_expanded(expanded)
        self.refresh_style()

    def set_header(self, title: str, subtitle: str, icon_name: str) -> None:
        """Update the header content."""
        self.set_title(title)
        self.set_subtitle(subtitle)
        self.set_icon(icon_name, size=(24, 24))

    def set_clickable_header(self, clickable: bool) -> None:
        """Toggle whether clicking the header should emit a signal."""
        self.set_header_clickable(clickable)

    def apply_state(self, state: TutorialTxCardState) -> None:
        """Apply a complete visual state to the tutorial transaction card."""
        self.set_header(state.title, state.subtitle, state.icon_name)
        self.set_expansion_mode(state.expansion_mode)
        self.set_clickable_header(state.clickable)
        self.set_expanded(state.expanded)
        self.setHidden(state.hidden)
