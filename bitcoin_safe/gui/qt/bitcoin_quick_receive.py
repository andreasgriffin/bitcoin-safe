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
from PyQt6.QtGui import QShowEvent

from bitcoin_safe.gui.qt.util import category_color
from bitcoin_safe.pythonbdk_types import AddressInfoMin

from ...signals import SignalsMin, UpdateFilter, UpdateFilterReason, WalletSignals
from ...wallet import Wallet
from .qr_components.quick_receive import QuickReceive, ReceiveGroup

logger = logging.getLogger(__name__)


class BitcoinQuickReceive(
    QuickReceive,
):
    def __init__(
        self,
        wallet_signals: WalletSignals,
        wallet: Wallet,
        signals_min: SignalsMin,
        limit_to_categories=None,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__("", parent=parent)
        self.wallet_signals = wallet_signals
        self.wallet = wallet
        self.signals_min = signals_min
        self.limit_to_categories = limit_to_categories
        self._pending_update = False
        self._forced_update = False

        # signals
        self.wallet_signals.updated.connect(self.update_content)
        self.wallet_signals.language_switch.connect(self.refresh_all)

    def refresh_all(self):
        """Refresh all."""
        self.update_content(UpdateFilter(refresh_all=True))

    def set_address(self, category: str, address_info: bdk.AddressInfo) -> ReceiveGroup:
        """Set address."""
        receive_group = ReceiveGroup(
            category,
            category_color(category).name(),
            AddressInfoMin.from_bdk_address_info(address_info),
            address_info.address.to_qr_uri(),
            parent=self,
        )
        receive_group.signal_set_address_as_used.connect(self.on_signal_set_address_as_used)
        self.add_box(receive_group)
        return receive_group

    def on_signal_set_address_as_used(self, address_info: AddressInfoMin):
        """On signal set address as used."""
        self.wallet.bdkwallet.mark_used(keychain=address_info.keychain, index=address_info.index)
        self.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=[address_info.address],
                categories=[],
                reason=UpdateFilterReason.AddressMarkedUsed,
            )
        )

    @property
    def addresses(self) -> list[str]:
        """Addresses."""
        return [group_box.address for group_box in self.group_boxes]

    @property
    def categories(self) -> list[str]:
        """Categories."""
        return [group_box.category for group_box in self.group_boxes]

    def showEvent(self, a0: QShowEvent | None) -> None:
        """ShowEvent."""
        super().showEvent(a0)
        if a0 and a0.isAccepted() and self._pending_update:
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
        """Update content."""
        if self.maybe_defer_update():
            return

        # decide whether to update
        should_update = False
        if (
            should_update
            or update_filter.refresh_all
            or update_filter.reason
            in [
                UpdateFilterReason.CategoryChange,
                UpdateFilterReason.AddressMarkedUsed,
            ]
        ):
            should_update = True
        if should_update or set(self.addresses).intersection(update_filter.addresses):
            should_update = True
        if should_update or set(self.categories).intersection(update_filter.categories):
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter")
        super().update()

        # reset title & snapshot old tips
        old_tips = self.wallet.tips

        # 1) grab old boxes and clear the list
        old_boxes: list[ReceiveGroup] = list(self.group_boxes)
        self.group_boxes.clear()

        updated_addressed = set()
        updated_categories = set()

        # 2) build & add all new boxes via your helpers
        for category in self.wallet.labels.categories:
            if self.limit_to_categories and category not in self.limit_to_categories:
                continue

            address_info = self.wallet.get_unused_category_address(category)
            updated_addressed.add(str(address_info.address))
            updated_categories.add(category)

            # this calls add_box() under the hood
            self.set_address(category, address_info)

        # fallback if no categories
        if not self.wallet.labels.categories:
            address_info = self.wallet.get_unused_category_address(None)
            addr_str = str(address_info.address)
            category = self.wallet.labels.get_category(addr_str)
            updated_addressed.add(addr_str)
            updated_categories.add(category)

            self.set_address(category, address_info)

        # 3) now remove the old widgets
        for old_box in old_boxes:
            self.remove_box(old_box)

        # 4) emit a follow-up if tips changed
        if old_tips != self.wallet.tips:
            self.wallet_signals.updated.emit(
                UpdateFilter(
                    addresses=updated_addressed,
                    categories=updated_categories,
                    reason=UpdateFilterReason.GetUnusedCategoryAddress,
                )
            )

        self.updateUi()

    def updateUi(self):
        super().updateUi()
        self.label_title.setText(self.tr("Receive addresses"))
