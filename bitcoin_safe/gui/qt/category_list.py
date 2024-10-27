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

logger = logging.getLogger(__name__)

from typing import Callable, List

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor

from ...signals import UpdateFilter, UpdateFilterReason, WalletSignals
from .taglist import CustomListWidget, TagEditor, hash_color


class CategoryList(CustomListWidget):
    def __init__(
        self,
        categories: List[str],
        wallet_signals: WalletSignals,
        get_sub_texts: Callable[[], List[str]],
        parent=None,
        immediate_release=True,
    ) -> None:
        super().__init__(parent, enable_drag=False, immediate_release=immediate_release)

        self.categories = categories
        self.get_sub_texts = get_sub_texts
        self.wallet_signals = wallet_signals
        self.wallet_signals.updated.connect(self.refresh)
        self.refresh(UpdateFilter(refresh_all=True))

        # signals
        self.wallet_signals.updated.connect(self.refresh)
        self.wallet_signals.import_labels.connect(self.refresh)
        self.wallet_signals.import_bip329_labels.connect(self.refresh)
        self.wallet_signals.import_electrum_wallet_labels.connect(self.refresh)

        self.wallet_signals.language_switch.connect(self.refresh)

    def select_category(self, category: str):
        for i in range(self.count()):
            item = self.item(i)
            if item:
                item.setSelected(item.text() == category)

    def on_language_switch(self):
        self.refresh(UpdateFilter(refresh_all=True))

    @staticmethod
    def shoud_update(update_filter: UpdateFilter | None = None) -> bool:
        should_update = False
        if update_filter is None:
            return True
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.categories:
            should_update = True
        if should_update or update_filter.outpoints:
            should_update = True

        return should_update

    def refresh(self, update_filter: UpdateFilter | None = None) -> None:
        if not self.shoud_update(update_filter):
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")
        self.recreate(self.categories, sub_texts=self.get_sub_texts())

    @classmethod
    def color(cls, category) -> QColor:
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)


class CategoryEditor(TagEditor):
    signal_category_added = pyqtSignal(str)

    def __init__(
        self,
        get_categories: Callable[[], List[str]],
        wallet_signals: WalletSignals,
        get_sub_texts: Callable[[], List[str]],
        parent=None,
        prevent_empty_categories=True,
    ) -> None:
        super().__init__(parent, get_categories(), sub_texts=get_sub_texts())

        self.get_categories = get_categories
        self.get_sub_texts = get_sub_texts
        self.wallet_signals = wallet_signals
        self.prevent_empty_categories = prevent_empty_categories

        self.updateUi()
        # signals
        self.wallet_signals.updated.connect(self.refresh)
        self.wallet_signals.import_labels.connect(self.refresh)
        self.wallet_signals.import_bip329_labels.connect(self.refresh)
        self.wallet_signals.import_electrum_wallet_labels.connect(self.refresh)

        self.list_widget.signal_tag_deleted.connect(self.on_delete)
        self.list_widget.signal_tag_added.connect(self.on_added)
        self.wallet_signals.language_switch.connect(self.updateUi)

    @classmethod
    def get_default_categories(cls) -> List[str]:
        return [cls.tr("KYC Exchange"), cls.tr("Private")]

    def add_default_categories(self):
        for category in self.get_default_categories():
            self.add(category)

    def updateUi(self) -> None:
        self.tag_name = self.tr("category")
        super().updateUi()
        self.refresh(UpdateFilter(refresh_all=True))

    def on_added(self, category) -> None:
        if not category or category in self.get_categories():
            return
        self.signal_category_added.emit(category)

        self.wallet_signals.updated.emit(
            UpdateFilter(categories=[category], reason=UpdateFilterReason.CategoryAdded)
        )

    def on_delete(self, category: str) -> None:
        if category not in self.get_categories():
            return
        self.wallet_signals.updated.emit(
            UpdateFilter(categories=[category], reason=UpdateFilterReason.CategoryDeleted)
        )

        if not self.get_categories() and self.prevent_empty_categories:
            self.list_widget.add("Default")
            self.wallet_signals.updated.emit(
                UpdateFilter(refresh_all=True, reason=UpdateFilterReason.CategoryDeleted)
            )

    def refresh(self, update_filter: UpdateFilter) -> None:
        if not CategoryList.shoud_update(update_filter):
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")
        self.list_widget.recreate(self.get_categories(), sub_texts=self.get_sub_texts())

    @classmethod
    def color(cls, category) -> QColor:
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)
