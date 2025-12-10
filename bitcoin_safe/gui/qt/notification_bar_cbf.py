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
from collections.abc import Callable

from PyQt6.QtCore import QLocale
from PyQt6.QtWidgets import QPushButton

from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.i18n import translate
from bitcoin_safe.network_config import NetworkConfig
from bitcoin_safe.pythonbdk_types import BlockchainType
from bitcoin_safe.signals import SignalsMin

from .util import svg_tools

logger = logging.getLogger(__name__)


def get_p2p_tooltip_text() -> str:
    """Get p2p tooltip text."""
    return translate(
        "p2p",
        "Passively listen to the bitcoin p2p traffic (just like a bitcoin node), \n"
        "to detect newly broadcasted transactions immediately."
        "\nThis does not reveal anything about your wallet."
        "\nClick here to learn more.",
    )


class NotificationBarCBF(NotificationBar):
    def __init__(
        self,
        callback_open_network_setting: Callable,
        callback_enable_button: Callable,
        network_config: NetworkConfig,
        signals_min: SignalsMin,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="",
            callback_optional_button=callback_open_network_setting,
            has_close_button=True,
        )
        self.network_config = network_config
        self.callback_enable_button = callback_enable_button
        self.signals_min = signals_min
        self.optionalButton.setHidden(False)
        # color = adjust_bg_color_for_darkmode(QColor("#7ad19f"))
        self.set_icon(svg_tools.get_QIcon("node.svg"))

        self.learn_more_button = IconLabel()
        self._layout.insertWidget(1, self.learn_more_button)

        self.enable_button = QPushButton()
        self.enable_button.clicked.connect(self.callback_enable_button)
        self._layout.insertWidget(2, self.enable_button)

        self.updateUi()
        self.signals_min.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.enable_button.setText(self.tr("Activate and restart"))
        self.optionalButton.setText(self.tr("Open Network Settings"))
        tooltip = self.tr("""Connect to bitcoin nodes (p2p) and download relevant blocks from them.""")
        self.icon_label.textLabel.setToolTip(tooltip)
        if (
            self.network_config.server_type == BlockchainType.Esplora
            and "blockstream" in self.network_config.esplora_url
        ):
            self.icon_label.textLabel.setText(
                self.tr(
                    "Update your network settings (current server is unreliable)! You can try Compact Block Filters for p2p syncing"
                )
            )
        else:
            self.icon_label.textLabel.setText(
                self.tr("Compact Block Filters for p2p syncing is now available")
            )

        lang_code_short = QLocale.languageToCode(QLocale().language())
        self.learn_more_button.set_icon_as_help(
            tooltip=tooltip,
            click_url=f"https://bitcoin-safe.org/{lang_code_short}/knowledge/compact-block-filters",
        )
