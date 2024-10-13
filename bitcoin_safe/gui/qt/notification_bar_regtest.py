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

from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.util import icon_path
from bitcoin_safe.signals import SignalsMin

logger = logging.getLogger(__name__)


import bdkpython as bdk
from PyQt6.QtGui import QIcon


class NotificationBarRegtest(NotificationBar):
    def __init__(self, open_network_settings, network: bdk.Network, signals_min: SignalsMin) -> None:
        super().__init__(
            text="",
            optional_button_text="",
            callback_optional_button=open_network_settings,
            has_close_button=True,
        )
        self.network = network
        self.signals_min = signals_min
        self.set_background_color("lightblue")
        self.set_icon(QIcon(icon_path(f"bitcoin-{network.name.lower()}.svg")))

        self.updateUi()
        self.signals_min.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        self.optionalButton.setText(self.tr("Change Network"))
        self.textLabel.setText(
            self.tr("Network = {network}. The coins are worthless!").format(
                network=self.network.name.capitalize()
            )
        )
