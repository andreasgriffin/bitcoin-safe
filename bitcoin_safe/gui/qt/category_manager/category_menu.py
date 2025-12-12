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

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalTracker
from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import QComboBox

from bitcoin_safe.category_info import CategoryInfo
from bitcoin_safe.gui.qt.category_manager.category_core import (
    CategoryCore,
    prompt_new_category,
)
from bitcoin_safe.gui.qt.util import category_color, create_color_circle, svg_tools
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason

logger = logging.getLogger(__name__)


class CategoryComboBox(QComboBox):
    ADD_CATEGORY_DATA = object()

    def __init__(self, category_core: CategoryCore | None = None, parent=None):
        """Initialize instance."""
        super().__init__(parent=parent)
        self._last_valid_index = -1
        self.signnal_tracker = SignalTracker()
        self.set_category_core(category_core=category_core)

        # catch only user‐driven changes
        self.activated[int].connect(self._on_activated)
        self.update_content()

        # signals

    def set_category_core(self, category_core: CategoryCore | None):
        """Set category core."""
        self.signnal_tracker.disconnect_all()
        self.category_core = category_core

        if self.category_core:
            self.signnal_tracker.connect(self.category_core.wallet_signals.updated, self.on_wallet_updated)
        self.update_content()

    def _get_category_infos(self) -> list[CategoryInfo]:
        """Get category infos."""
        d: list[CategoryInfo] = []
        for i in range(self.count()):
            data = self.itemData(i)
            if isinstance(data, CategoryInfo):
                d.append(data)
        return d

    def on_wallet_updated(self, update_filter: UpdateFilter):
        """On wallet updated."""
        if not self.category_core:
            return
        my_categories = [info.category for info in self._get_category_infos()]

        wallet_categories = self.category_core.wallet.labels.categories
        if len(my_categories) != len(wallet_categories) or any(
            [
                my_category != wallet_category
                for my_category, wallet_category in zip(my_categories, wallet_categories, strict=False)
            ]
        ):
            self.update_content()

    def update_content(self):
        """Rebuild the list and reset to first real category."""
        if not self.category_core:
            return
        with QSignalBlocker(self):
            self.clear()

            self.addItem("All", None)

            infos = self.category_core.wallet_signals.get_category_infos.emit() or []
            for info in infos:
                icon = create_color_circle(category_color(info.category))
                self.addItem(icon, info.category, info)

            self.addItem(
                svg_tools.get_QIcon("bi--plus-lg.svg"), self.tr("Add category"), self.ADD_CATEGORY_DATA
            )

            if len(infos) == 1:
                first_category_index = 1  # "All" is at index 0
                super().setCurrentIndex(first_category_index)
                self._last_valid_index = first_category_index

    def _on_activated(self, index: int):
        """On activated."""
        data = self.itemData(index)
        if data is self.ADD_CATEGORY_DATA:
            # user clicked “Add category”
            self._on_add_category()
            # revert to last real category
            super().setCurrentIndex(self._last_valid_index)
        else:
            # valid category chosen → remember it
            self._last_valid_index = index
            # (optionally emit your own signal here)

    def _on_add_category(self):
        """On add category."""
        if not self.category_core:
            return
        category = prompt_new_category(self)
        if not category:
            return

        # assume add_category returns the new CategoryInfo
        self.category_core.add(category)
        self.update_content()

        self.select_item(category)

        self.category_core.wallet_signals.updated.emit(
            UpdateFilter(categories=[category], reason=UpdateFilterReason.CategoryChange)
        )

    def select_item(self, category: str):
        # find and select the newly created one
        """Select item."""
        for i in range(self.count()):
            if self.itemText(i) == category:
                super().setCurrentIndex(i)
                self._last_valid_index = i
                break
