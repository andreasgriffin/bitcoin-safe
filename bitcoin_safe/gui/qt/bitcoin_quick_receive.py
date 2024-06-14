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

from ...signals import Signals, UpdateFilter
from ...wallet import Wallet
from .qr_components.quick_receive import QuickReceive, ReceiveGroup
from .taglist.main import hash_color

logger = logging.getLogger(__name__)


class BitcoinQuickReceive(QuickReceive):
    def __init__(
        self,
        signals: Signals,
        wallet: Wallet,
        title="",
        limit_to_categories=None,
    ) -> None:
        super().__init__(title)
        self.signals = signals
        self.wallet = wallet
        self.limit_to_categories = limit_to_categories

        self.setFixedHeight(250)
        self.signals.category_updated.connect(self.update)
        self.signals.language_switch.connect(self.update)

    def update(self) -> None:
        super().update()
        self.clear_boxes()
        self.label_title.setText(self.tr("Quick Receive"))
        old_tips = self.wallet.tips

        for category in self.wallet.labels.categories:
            if self.limit_to_categories and category not in self.limit_to_categories:
                continue

            address_info = self.wallet.get_unused_category_address(category)

            self.add_box(
                ReceiveGroup(
                    category,
                    hash_color(category).name(),
                    address_info.address.as_string(),
                    address_info.address.to_qr_uri(),
                )
            )

        if not self.wallet.labels.categories:
            address_info = self.wallet.get_unused_category_address(None)

            self.add_box(
                ReceiveGroup(
                    self.tr("Receive Address"),
                    hash_color("None").name(),
                    address_info.address.as_string(),
                    address_info.address.to_qr_uri(),
                )
            )
        if old_tips != self.wallet.tips:
            self.signals.addresses_updated.emit(UpdateFilter(refresh_all=True))
