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

from bitcoin_safe_lib.gui.qt.util import question_dialog
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QShowEvent
from PyQt6.QtWidgets import QDialogButtonBox, QPushButton, QVBoxLayout, QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.category_manager.category_core import (
    CategoryCore,
    prompt_merge_category,
    prompt_new_category,
    prompt_rename_category,
)
from bitcoin_safe.gui.qt.category_manager.category_list import (
    CategoryList,
    CategoryListWithToolbar,
)
from bitcoin_safe.gui.qt.drag_info import AddressDragInfo
from bitcoin_safe.gui.qt.util import center_on_screen, svg_tools
from bitcoin_safe.labels import LabelType

from ....signals import UpdateFilter, UpdateFilterReason

logger = logging.getLogger(__name__)


class CategoryManager(QWidget):
    def __init__(self, config: UserConfig, category_core: CategoryCore, wallet_id: str):
        """Initialize instance."""
        super().__init__()
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.category_core = category_core
        self.wallet_id = wallet_id
        self._layout = QVBoxLayout(self)

        self.category_list = CategoryList(
            config=config,
            category_core=category_core,
            signals=category_core.signals,
            hidden_columns=(
                [
                    CategoryList.Columns.COLOR,
                    CategoryList.Columns.TXO_BALANCE,
                    CategoryList.Columns.UTXO_BALANCE,
                    CategoryList.Columns.UTXO_COUNT,
                    CategoryList.Columns.TXO_COUNT,
                ]
            ),
        )
        self.category_list_with_toolbar = CategoryListWithToolbar(
            category_list=self.category_list, config=config, parent=self
        )
        self._layout.addWidget(self.category_list_with_toolbar)

        self.category_list.signal_selection_changed.connect(self.on_selection_changed)

        # Create buttons
        self.button_box = QDialogButtonBox()
        self.button_add = QPushButton()
        self.button_add.clicked.connect(self.add_category)
        self.button_box.addButton(self.button_add, QDialogButtonBox.ButtonRole.ActionRole)
        self.button_add.setIcon(svg_tools.get_QIcon("bi--plus-lg.svg"))

        self.button_merge = QPushButton()
        self.button_merge.clicked.connect(self.on_button_merge)
        self.button_box.addButton(self.button_merge, QDialogButtonBox.ButtonRole.ActionRole)
        self.button_merge.setIcon(svg_tools.get_QIcon("bi--sign-merge-right.svg"))

        self.button_rename = QPushButton()
        self.button_rename.clicked.connect(self.on_button_rename)
        self.button_box.addButton(self.button_rename, QDialogButtonBox.ButtonRole.ActionRole)
        self.button_rename.setIcon(svg_tools.get_QIcon("bi--input-cursor-text.svg"))

        self._layout.addWidget(self.button_box)

        self.shortcut_close = QShortcut(QKeySequence("Ctrl+W"), self)
        self.shortcut_close.activated.connect(self.close)
        self.shortcut_close2 = QShortcut(QKeySequence("ESC"), self)
        self.shortcut_close2.activated.connect(self.close)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        center_on_screen(self)

    def on_selection_changed(self):
        """On selection changed."""
        self.set_visibilities()

    def set_visibilities(self):
        """Set visibilities."""
        keys = self.category_list.get_selected_keys()
        self.button_rename.setEnabled(len(keys) == 1)

        self.button_merge.setEnabled(len(keys) > 1)

    def updateUi(self):
        """UpdateUi."""
        self.setWindowTitle(self.tr("Manage Categories of {wallet_id}").format(wallet_id=self.wallet_id))
        self.button_add.setText(self.tr("Add Category"))
        self.button_merge.setText(self.tr("Merge"))
        self.button_rename.setText(self.tr("Rename"))
        self.set_visibilities()

    def add_category(self):
        """Add category."""
        category = prompt_new_category(self)
        if not category:
            return

        # assume add_category returns the new CategoryInfo
        self.category_core.add(category)

        self.category_core.wallet_signals.updated.emit(
            UpdateFilter(categories=[category], reason=UpdateFilterReason.CategoryChange)
        )

    def on_button_merge(self):
        """On button merge."""
        category_infos = self.category_list.get_selected_category_infos()
        if len(category_infos) <= 1:
            return
        categories = [info.category for info in category_infos]

        new_category = prompt_merge_category(categories=categories, parent=self)
        if not new_category:
            return

        used_addresses = []
        for category in categories:
            if category == new_category:
                continue
            used_addresses += self.get_used_addresses(category=category)

        if used_addresses:
            if question_dialog(
                text=self.tr(
                    "The addresses {used_addresses}\nhave transactions linking to other addresses already. Are you sure you want to change their category?"
                ).format(used_addresses="\n   " + "\n   ".join(used_addresses)),
                true_button=self.tr("Change category"),
            ):
                pass
            else:
                return

        for category in categories:
            self.rename_category(old_category=category, new_category=new_category)

    def get_used_addresses(self, category: str, addresses: list[str] | None = None) -> list[str]:
        """Get used addresses."""
        addresses = (
            addresses
            if addresses
            else [
                label.ref
                for label in self.category_core.wallet.labels.get_category_dict_raw(
                    filter_type=LabelType.addr
                ).get(category, [])
            ]
        )
        used_addresses = [
            address for address in addresses if self.category_core.wallet.address_is_used(address=address)
        ]
        return used_addresses

    def on_button_rename(self):
        """On button rename."""
        category_infos = self.category_list.get_selected_category_infos()
        if len(category_infos) != 1:
            return
        category = category_infos[0].category

        new_category = prompt_rename_category(old_name=category, parent=self)
        if not new_category:
            return

        self.rename_category(old_category=category, new_category=new_category)

    def rename_category(self, old_category: str, new_category: str) -> None:
        """Rename category."""
        affected_keys = self.category_core.wallet.labels.rename_category(old_category, new_category)
        # add addresses with no category
        affected_keys += [
            a
            for a in self.category_core.wallet.get_addresses()
            if self.category_core.wallet.labels.get_category(a)
        ]
        affected_keys = list(set(affected_keys))
        self.category_core.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=affected_keys,
                categories=([old_category, new_category]),
                txids=affected_keys,
                reason=UpdateFilterReason.CategoryChange,
            )
        )

    def set_category(self, address_drag_info: AddressDragInfo) -> None:
        """Set category."""
        apply_addresses = address_drag_info.addresses
        used_addresses = [
            address
            for address in address_drag_info.addresses
            if self.category_core.wallet.address_is_used(address=address)
        ]
        if used_addresses:
            if question_dialog(
                text=self.tr(
                    "The addresses {used_addresses}\nhave transactions linking to other addresses already. Are you sure you want to change the category?"
                ).format(used_addresses="\n   " + "\n   ".join(used_addresses)),
                true_button=self.tr("Change category"),
            ):
                apply_addresses = address_drag_info.addresses
            else:
                return

        for address in apply_addresses:
            for category in address_drag_info.tags:
                self.category_core.wallet.labels.set_addr_category(address, category, timestamp="now")

        txids: set[str] = set()
        for address in apply_addresses:
            txids = txids.union(self.category_core.wallet.get_involved_txids(address))

        self.category_core.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=apply_addresses,
                categories=address_drag_info.tags,
                txids=txids,
                reason=UpdateFilterReason.UserInput,
            )
        )

    def close(self) -> bool:
        """Close."""
        self.category_list.close()
        return super().close()
