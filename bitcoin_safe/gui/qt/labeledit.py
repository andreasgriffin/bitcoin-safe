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
from collections.abc import Callable
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6 import QtGui
from PyQt6.QtCore import QEvent, QObject, QStringListModel, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.util import category_color
from bitcoin_safe.labels import LabelType
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason, WalletFunctions
from bitcoin_safe.wallet import (
    Wallet,
    get_label_from_any_wallet,
    get_wallet_of_address,
    get_wallets,
)

logger = logging.getLogger(__name__)


class LabelLineEdit(QLineEdit):
    signal_enterPressed = cast(SignalProtocol[[]], pyqtSignal())  # Signal for Enter key
    signal_textEditedAndFocusLost = cast(
        SignalProtocol[[]], pyqtSignal()
    )  # Signal for text edited and focus lost

    def __init__(self, parent=None):
        """Initialize instance."""
        super().__init__(parent)
        self.originalText = ""
        self.textChangedSinceFocus = False
        self.installEventFilter(self)  # Install an event filter

        self._model = QStringListModel()
        self._completer = QCompleter(self._model, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(self._completer)

        # signals
        self.textChanged.connect(self.onTextChanged)  # Connect the textChanged signal

    def set_completer_list(self, strings: list[str]):
        """Set completer list."""
        self._model.setStringList(strings)
        self._completer.setModel(self._model)

    def onTextChanged(self):
        """OnTextChanged."""
        self.textChangedSinceFocus = True  # Set flag when text changes

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        """EventFilter."""
        if not a1:
            return False
        if a0 == self:
            if a1.type() == QKeyEvent.Type.FocusIn:
                self.originalText = self.text()  # Store text when focused
                self.textChangedSinceFocus = False  # Reset change flag
            elif a1.type() == QKeyEvent.Type.FocusOut:
                if self.textChangedSinceFocus:
                    self.signal_textEditedAndFocusLost.emit()  # Emit signal if text was edited
                self.textChangedSinceFocus = False  # Reset change flag
        return super().eventFilter(a0, a1)

    def keyPressEvent(self, a0: QKeyEvent | None):
        """KeyPressEvent."""
        if not a0:
            super().keyPressEvent(a0)
            return

        if a0.key() == Qt.Key.Key_Return or a0.key() == Qt.Key.Key_Enter:
            self.signal_enterPressed.emit()  # Emit Enter pressed signal
        elif a0.key() == Qt.Key.Key_Escape:
            self.setText(self.originalText)  # Reset text on ESC
        elif self._model.stringList() and a0.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            popup = self._completer.popup()
            if popup and not popup.isVisible():
                self._completer.complete()
        else:
            super().keyPressEvent(a0)


class LabelAndCategoryEdit(QWidget):
    def __init__(
        self,
        parent=None,
        dismiss_label_on_focus_loss=False,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.label_edit = LabelLineEdit(parent=self)
        self.category_edit = QLineEdit(parent=self)
        self.category_edit.setReadOnly(True)
        self.category_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.category_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # self.category_edit.setFixedWidth(100)

        self.main_layout = QHBoxLayout(
            self
        )  # Horizontal layout to place the input field and buttons side by side

        # Add the input field and buttons layout to the main layout
        self.main_layout.addWidget(self.label_edit)
        self.main_layout.addWidget(self.category_edit)

        # Ensure there's no spacing that could affect the alignment
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.set_category_visible(False)

        # signals
        if dismiss_label_on_focus_loss:
            self.label_edit.signal_textEditedAndFocusLost.connect(self.on_signal_textEditedAndFocusLost)

    def on_signal_textEditedAndFocusLost(self):
        """On signal textEditedAndFocusLost."""
        return self.label_edit.setText(self.label_edit.originalText)

    def _format_category_edit(self) -> None:
        """Format category edit."""
        palette = QtGui.QPalette()
        background_color = None

        if self.category_edit.text():
            background_color = category_color(self.category_edit.text())
            palette.setColor(QtGui.QPalette.ColorRole.Base, background_color)
        else:
            palette = (self.category_edit.style() or QStyle()).standardPalette()

        self.category_edit.setPalette(palette)
        self.category_edit.update()

    def set(self, label: str, category: str):
        """Set."""
        self.set_label(label)
        self.set_category(category)

    def set_category(self, category: str):
        """Set category."""
        self.category_edit.setText(category)
        self._format_category_edit()

    def set_label(
        self,
        label: str,
    ):
        """Set label."""
        self.label_edit.setText(label)
        self.label_edit.originalText = label

    def set_placeholder(
        self,
        text: str,
    ):
        """Set placeholder."""
        self.label_edit.setPlaceholderText(text)

    def set_category_visible(self, value: bool):
        """Set category visible."""
        self.category_edit.setVisible(value)

    def category(self) -> str:
        """Category."""
        return self.category_edit.text()

    def label(self) -> str:
        """Label."""
        return self.label_edit.text().strip()

    def set_label_readonly(self, value: bool):
        """Set label readonly."""
        self.label_edit.setReadOnly(value)


class WalletLabelAndCategoryEdit(LabelAndCategoryEdit):
    def __init__(
        self,
        wallet_functions: WalletFunctions,
        get_label_ref: Callable[[], str],
        label_type: LabelType,
        parent=None,
        dismiss_label_on_focus_loss=False,
    ) -> None:
        """Initialize instance."""
        self.get_label_ref = get_label_ref
        super().__init__(parent=parent, dismiss_label_on_focus_loss=dismiss_label_on_focus_loss)
        self.wallet_functions = wallet_functions
        self.label_type = label_type

        self.label_edit.signal_enterPressed.connect(self.on_label_edited)
        self.label_edit.signal_textEditedAndFocusLost.connect(self.on_label_edited)
        self.wallet_functions.signals.any_wallet_updated.connect(self.update_with_filter)

    def get_wallets_to_store_label(self, ref: str) -> set[Wallet]:
        """Will return wallets where it occurs in ANY transaction.

        The address doesnt have to belong to any wallet, but might be a recipient
        """

        result = set()
        if not self.wallet_functions:
            return set()

        wallets = get_wallets(self.wallet_functions)

        if self.label_type in [LabelType.addr]:
            for wallet in wallets:
                if wallet.is_my_address_with_peek(ref):
                    result.add(wallet)
                elif wallet.get_label_for_address(ref):
                    result.add(wallet)
                elif wallet.get_involved_txids(ref):
                    result.add(wallet)
        elif self.label_type in [LabelType.tx]:
            for wallet in wallets:
                if ref in wallet.get_txs():
                    # this only works for a tx that is already in the wallet (not a psbt)
                    result.add(wallet)
            # if the txid wasnt in any wallet, then add the label to all the open wallets
            if not result:
                result = result.union(wallets)
        return result

    def on_label_edited(self) -> None:
        """On label edited."""
        if self.label_type not in [LabelType.addr, LabelType.tx]:
            return
        ref = self.get_label_ref()

        wallets = self.get_wallets_to_store_label(ref)
        if not wallets:
            return

        new_labeltext = self.label()
        self.set(new_labeltext, self.category())
        for wallet in wallets:
            wallet.labels.set_label(type=self.label_type, ref=ref, label_value=new_labeltext, timestamp="now")

            categories = []
            if not wallet.labels.get_category_raw(ref):
                # also fix the category to have consitency across wallets via the labelsyncer
                category = wallet.labels.get_category(ref)
                categories += [category]
                wallet.labels.set_category(type=self.label_type, ref=ref, category=category, timestamp="now")

            update_filter = None
            if self.label_type == LabelType.addr:
                update_filter = UpdateFilter(
                    addresses=[ref],
                    categories=categories,
                    txids=wallet.get_involved_txids(ref),
                    reason=UpdateFilterReason.UserInput,
                )
            elif self.label_type == LabelType.tx:
                update_filter = UpdateFilter(
                    addresses=[],
                    categories=categories,
                    txids=[ref],
                    reason=UpdateFilterReason.UserInput,
                )

            if completer := self.label_edit.completer():
                if popup := completer.popup():
                    popup.hide()
            if update_filter:
                self.wallet_functions.wallet_signals[wallet.id].updated.emit(update_filter)

    def autofill_category(self, update_filter: UpdateFilter | None = None):
        """Autofill category."""
        ref = self.get_label_ref()
        if update_filter and not (
            (ref in update_filter.addresses or ref in update_filter.txids)
            or self.category() in update_filter.categories
            or update_filter.refresh_all
        ):
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter")

        wallet = None
        if self.label_type == LabelType.addr:
            wallet = get_wallet_of_address(ref, self.wallet_functions)
        if wallet:
            category = wallet.labels.get_category(ref)
            self.set_category_visible(True)
            self.set_category(category if category else "")
        else:
            self.set_category_visible(False)
            self.set_category("")

    def autofill_label(self, update_filter: UpdateFilter | None = None, overwrite_existing=False):
        """Autofill label."""
        ref = self.get_label_ref()
        if update_filter and not (
            (ref in update_filter.addresses or ref in update_filter.txids) or update_filter.refresh_all
        ):
            return

        # decide wether to overwrite an existing label or not
        if (not overwrite_existing) and self.label() and not self.label_edit.isReadOnly():
            # do not overwrite an existing label that the user can edit
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter")

        label = get_label_from_any_wallet(
            label_type=self.label_type,
            ref=ref,
            wallet_functions=self.wallet_functions,
            autofill_from_txs=False,
        )
        if self.label_type == LabelType.addr:
            self.set_placeholder(self.tr("Enter label for recipient address"))
        elif self.label_type == LabelType.tx:
            self.set_placeholder(self.tr("Enter label for transaction"))

        self.set_label(label if label else "")
        self.label_edit.set_completer_list([label] if label else [])

        if not label:
            # try to autofill from other wallets
            completer_label = get_label_from_any_wallet(
                label_type=self.label_type,
                ref=ref,
                wallet_functions=self.wallet_functions,
                autofill_from_txs=True,
                autofill_from_addresses=True,
            )
            self.label_edit.set_completer_list([completer_label] if completer_label else [])

    def autofill_label_and_category(self, update_filter: UpdateFilter | None = None):
        """Autofill label and category."""
        self.autofill_label(update_filter)
        self.autofill_category(update_filter)

    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        """Update with filter."""
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        pass


# Example usage
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    widget_layout = QVBoxLayout(widget)
    widget_layout.setContentsMargins(0, 0, 0, 0)
    widget_layout.setSpacing(0)

    edit = LabelAndCategoryEdit()
    edit.set("some label", "KYC")
    widget_layout.addWidget(edit)

    widget.show()
    sys.exit(app.exec())
