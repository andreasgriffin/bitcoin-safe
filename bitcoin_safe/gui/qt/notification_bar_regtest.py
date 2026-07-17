#
# Bitcoin-Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import logging
from collections.abc import Callable

import bdkpython as bdk
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QPushButton, QWidget

from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.network_config import get_testnet_faucet
from bitcoin_safe.signals import SignalsMin

from .testnet_faucet import open_testnet_faucet

logger = logging.getLogger(__name__)


class NotificationBarRegtest(NotificationBar):
    def __init__(
        self,
        callback_open_network_setting: Callable,
        network: bdk.Network,
        signals_min: SignalsMin,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="",
            callback_optional_button=callback_open_network_setting,
            has_close_button=True,
            parent=parent,
        )
        self.network = network
        self.signals_min = signals_min
        self.set_background_base_color(QColor("lightblue"))
        self.set_icon(f"bitcoin-{network.name.lower()}.svg")
        self.optionalButton.setHidden(False)

        self.faucet = get_testnet_faucet(network=self.network)
        self.faucet_button = QPushButton(self)
        self.faucet_button.clicked.connect(self.open_faucet)
        self.faucet_button.setHidden(not bool(self.faucet))
        self.add_styled_widget(self.faucet_button)

        self.updateUi()
        self.signals_min.language_switch.connect(self.updateUi)

    def open_faucet(self):
        """Open faucet."""
        open_testnet_faucet(self.network)

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.set_background_base_color(QColor("lightblue"))
        self.set_icon(f"bitcoin-{self.network.name.lower()}.svg")
        self.faucet_button.setText(self.tr("Get {testnet} coins").format(testnet=self.network.name.lower()))
        self.faucet_button.setHidden(not bool(self.faucet))
        self.optionalButton.setText(self.tr("Open Network Settings"))
        self.icon_label.setText(
            self.tr("Network = {network}. The coins are worthless!").format(
                network=self.network.name.capitalize()
            )
        )
