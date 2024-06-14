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

from typing import List

from PyQt6.QtGui import QColor

from ...signals import Signals, UpdateFilter
from .taglist import CustomListWidget, TagEditor, hash_color


class CategoryList(CustomListWidget):
    def __init__(
        self,
        categories: List,
        signals: Signals,
        get_sub_texts=None,
        parent=None,
        tag_name="category",
        immediate_release=True,
    ) -> None:
        super().__init__(parent, enable_drag=False, immediate_release=immediate_release)

        self.categories = categories
        self.get_sub_texts = get_sub_texts
        self.signals = signals
        self.signals.category_updated.connect(self.refresh)
        self.signals.utxos_updated.connect(self.refresh)
        self.refresh(UpdateFilter(refresh_all=True))
        self.signals.language_switch.connect(lambda: self.refresh(UpdateFilter(refresh_all=True)))

    def refresh(self, update_filter: UpdateFilter) -> None:
        self.recreate(self.categories, sub_texts=self.get_sub_texts())

    @classmethod
    def color(cls, category) -> QColor:
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)


class CategoryEditor(TagEditor):
    def __init__(
        self,
        categories: List,
        signals: Signals,
        get_sub_texts=None,
        parent=None,
        prevent_empty_categories=True,
    ) -> None:
        sub_texts = get_sub_texts() if get_sub_texts else None
        super().__init__(parent, categories, tag_name="", sub_texts=sub_texts)

        self.categories = categories
        self.get_sub_texts = get_sub_texts
        self.signals = signals
        self.prevent_empty_categories = prevent_empty_categories

        self.updateUi()
        # signals
        self.signals.category_updated.connect(self.refresh)
        self.signals.import_bip329_labels.connect(self.refresh)

        self.list_widget.signal_tag_deleted.connect(self.on_delete)
        self.list_widget.signal_tag_added.connect(self.on_added)
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        self.tag_name = self.tr("category")
        super().updateUi()
        self.refresh(UpdateFilter(refresh_all=True))

    def on_added(self, category) -> None:
        if not category or category in self.categories:
            return

        self.categories.append(category)
        self.signals.category_updated.emit(UpdateFilter(categories=[category]))

    def on_delete(self, category) -> None:
        if category not in self.categories:
            return
        idx = self.categories.index(category)
        self.categories.pop(idx)
        self.signals.category_updated.emit(UpdateFilter(categories=[category]))

        if not self.categories and self.prevent_empty_categories:
            self.list_widget.add("Default")
            self.signals.category_updated.emit(UpdateFilter(refresh_all=True))

    def refresh(self, update_filter: UpdateFilter) -> None:
        self.list_widget.recreate(self.categories, sub_texts=self.get_sub_texts())

    @classmethod
    def color(cls, category) -> QColor:
        if not category:
            return QColor(255, 255, 255, 255)
        return hash_color(category)
