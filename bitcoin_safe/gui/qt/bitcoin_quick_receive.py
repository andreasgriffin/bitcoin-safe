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
from typing import List

import bdkpython as bdk
from PyQt6.QtGui import QShowEvent

from ...signals import UpdateFilter, UpdateFilterReason, WalletSignals
from ...wallet import Wallet
from .qr_components.quick_receive import QuickReceive, ReceiveGroup
from .taglist.main import hash_color

logger = logging.getLogger(__name__)


class BitcoinQuickReceive(QuickReceive):
    def __init__(
        self,
        wallet_signals: WalletSignals,
        wallet: Wallet,
        limit_to_categories=None,
    ) -> None:
        super().__init__(self.tr("Quick Receive"))
        self.wallet_signals = wallet_signals
        self.wallet = wallet
        self.limit_to_categories = limit_to_categories
        self._pending_update = False

        self.setFixedHeight(250)
        self.wallet_signals.updated.connect(self.update_content)
        self.wallet_signals.language_switch.connect(
            lambda: self.update_content(UpdateFilter(refresh_all=True))
        )

    def set_address(self, category: str, address_info: bdk.AddressInfo):
        address = address_info.address.as_string()

        self.add_box(
            ReceiveGroup(
                category, hash_color(category).name(), address, address_info.address.to_qr_uri(), parent=self
            )
        )

    @property
    def addresses(self) -> List[str]:
        return [group_box.address for group_box in self.group_boxes]

    @property
    def categories(self) -> List[str]:
        return [group_box.category for group_box in self.group_boxes]

    def showEvent(self, e: QShowEvent | None) -> None:
        super().showEvent(e)
        if e and e.isAccepted() and self._pending_update:
            self._forced_update = True
            self.update_content(UpdateFilter(refresh_all=True))
            self._forced_update = False

    def maybe_defer_update(self) -> bool:
        """Returns whether we should defer an update/refresh."""
        defer = not self.isVisible()
        # side-effect: if we decide to defer update, the state will become stale:
        self._pending_update = defer
        return defer

    def update_content(self, update_filter: UpdateFilter) -> None:
        if self.maybe_defer_update():
            return

        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or set(self.addresses).intersection(update_filter.addresses):
            should_update = True
        if should_update or set(self.categories).intersection(update_filter.categories):
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")
        super().update()

        self.clear_boxes()
        self.label_title.setText(self.tr("Quick Receive"))
        old_tips = self.wallet.tips

        updated_addressed = set()
        updated_categories = set()
        for category in self.wallet.labels.categories:
            if self.limit_to_categories and category not in self.limit_to_categories:
                continue

            address_info = self.wallet.get_unused_category_address(category)
            updated_addressed.add(address_info.address.as_string())
            updated_categories.add(category)
            self.set_address(category, address_info)

        if not self.wallet.labels.categories:
            address_info = self.wallet.get_unused_category_address(None)
            address = address_info.address.as_string()
            category = self.wallet.labels.get_category(address)
            self.set_address(category, address_info)
            updated_addressed.add(address)
            updated_categories.add(category)

        if old_tips != self.wallet.tips:
            self.wallet_signals.updated.emit(
                UpdateFilter(
                    addresses=updated_addressed,
                    categories=updated_categories,
                    reason=UpdateFilterReason.GetUnusedCategoryAddress,
                )
            )
