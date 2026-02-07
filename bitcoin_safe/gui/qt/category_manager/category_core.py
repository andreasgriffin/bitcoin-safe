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

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.wallet import Wallet
from bitcoin_safe.wallet_util import get_default_categories

from ....i18n import translate
from ....signals import Signals, UpdateFilter, UpdateFilterReason, WalletSignals

logger = logging.getLogger(__name__)


def move_items(lst: list[str], from_indices: list[int], to_idx: int) -> None:
    """Move items."""
    if not from_indices:
        return

    # If we're moving it _forward_, then popping at from_idx
    # will shift all later slots left by one, so adjust:
    if to_idx >= from_indices[-1]:
        to_idx -= len(from_indices)

    reverse_items = []
    for from_idx in sorted(from_indices, reverse=True):
        reverse_items.append(lst.pop(from_idx))

    for item in reverse_items:
        lst.insert(to_idx, item)


def prompt_new_category(parent: QWidget | None = None) -> str | None:
    """Show a modal input dialog titled “Add Category”.

    Returns the trimmed category name if OK was clicked and non-empty, otherwise returns None.
    """
    text, ok = QInputDialog.getText(
        parent, translate("category", "Add Category"), translate("category", "Category name:")
    )
    name = text.strip()
    if ok and name:
        return name
    return None


def prompt_rename_category(old_name: str, parent: QWidget | None = None) -> str | None:
    """Show a modal dialog titled “Rename Category” with a prefilled line edit.

    Returns the new trimmed name if OK was clicked and non-empty, otherwise returns None.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(translate("category", "Rename Category"))
    dialog.setModal(True)

    layout = QVBoxLayout(dialog)

    label = QLabel(translate("category", "New category name:"))
    line_edit = QLineEdit()
    line_edit.setText(old_name)
    line_edit.setPlaceholderText(translate("category", "Enter new category name..."))

    layout.addWidget(label)
    layout.addWidget(line_edit)

    button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    layout.addWidget(button_box)

    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)

    if dialog.exec():
        new_name = line_edit.text().strip()
        if new_name:
            return new_name
    return None


def prompt_merge_category(categories: list[str], parent: QWidget | None = None) -> str | None:
    """Show a modal dialog titled “Merge Categories” with a combo box to select a
    category.

    Returns the selected category if OK was clicked, otherwise returns None.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle(translate("category", "Merge Categories"))
    dialog.setModal(True)

    layout = QVBoxLayout(dialog)
    label = QLabel(translate("category", "Resulting category:"))
    combo = QComboBox()
    combo.addItems(categories)

    layout.addWidget(label)
    layout.addWidget(combo)

    button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    layout.addWidget(button_box)

    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)

    if dialog.exec():
        return combo.currentText()
    return None


class CategoryCore(QObject):
    def __init__(self, wallet: Wallet, signals: Signals, wallet_signals: WalletSignals):
        """Initialize instance."""
        super().__init__()
        self.wallet = wallet
        self.wallet_signals = wallet_signals
        self.signals = signals

    def add_default_categories(self) -> None:
        """Add default categories."""
        for category in get_default_categories():
            self.add(category)

    def add(self, category: str):
        """Add."""
        if category in self.wallet.labels.categories:
            return
        self.wallet.labels.add_category(category)

    def move_categories(self, categories: list[str], to_idx: int):
        """Move categories."""
        from_indices = [
            self.wallet.labels.categories.index(category)
            for category in categories
            if category in self.wallet.labels.categories
        ]
        if not from_indices:
            return
        move_items(lst=self.wallet.labels.categories, from_indices=from_indices, to_idx=to_idx)

        self.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=[],
                categories=[],
                txids=[],
                reason=UpdateFilterReason.CategoryChange,
                refresh_all=True,
            )
        )
