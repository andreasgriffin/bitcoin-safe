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
from typing import cast

from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.language_chooser import (
    LanguageChooser,
    create_language_combobox,
)

from ...fx import FX
from .currency_combobox import CurrencyComboBox, CurrencyGroup, CurrencyGroupFormatting
from .dialogs import PasswordCreation

logger = logging.getLogger(__name__)


class InterfaceSettingsUi(QWidget):
    signal_app_lock_password_changed = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        fx: FX,
        language_chooser: LanguageChooser,
        config: UserConfig,
        parent=None,
    ):
        """Initialize instance."""
        super().__init__(parent)
        self.fx = fx
        self.config = config
        self.language_chooser = language_chooser

        # 1) Language combo
        self.language_combo = create_language_combobox(language_chooser.get_languages())
        for idx in range(self.language_combo.count()):
            if self.language_combo.itemData(idx) == self.config.language_code:
                self.language_combo.setCurrentIndex(idx)

        # 2) Currency combo
        self.currency_combo = CurrencyComboBox(
            self.fx,
            groups=[
                CurrencyGroup.TOP_FIAT,
                CurrencyGroup.FIAT,
                CurrencyGroup.Commodity,
                CurrencyGroup.BITCOIN_OTHER,
            ],
            formatting=CurrencyGroupFormatting.Full,
        )

        # 2b) Bitcoin symbol
        self.bitcoin_symbol_combo = QComboBox(self)
        self.bitcoin_symbol_combo.addItem(BitcoinSymbol.ISO.value, BitcoinSymbol.ISO)
        self.bitcoin_symbol_combo.addItem(BitcoinSymbol.UNICODE.value, BitcoinSymbol.UNICODE)
        idx = self.bitcoin_symbol_combo.findData(self.config.bitcoin_symbol)
        self.bitcoin_symbol_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # 3) Layout
        form = QFormLayout(self)
        self.label_language = QLabel("")
        self.label_currency = QLabel("")
        self.label_bitcoin_symbol = QLabel("")
        self.label_app_lock_password = QLabel("")

        self.app_lock_password_status = QLabel("")
        self.button_set_app_lock_password = QPushButton(self)
        self.button_clear_app_lock_password = QPushButton(self)

        self.app_lock_controls = QWidget(self)
        app_lock_layout = QHBoxLayout(self.app_lock_controls)
        app_lock_layout.setContentsMargins(0, 0, 0, 0)
        app_lock_layout.addWidget(self.app_lock_password_status, 1)
        app_lock_layout.addWidget(self.button_set_app_lock_password)
        app_lock_layout.addWidget(self.button_clear_app_lock_password)

        form.addRow(self.label_language, self.language_combo)
        form.addRow(self.label_currency, self.currency_combo)
        form.addRow(self.label_bitcoin_symbol, self.bitcoin_symbol_combo)
        form.addRow(self.label_app_lock_password, self.app_lock_controls)

        # 4) initial selection
        self.data_updated()
        self.refresh_app_lock_status()

        # signals
        self.fx.signal_data_updated.connect(self.data_updated)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.currency_combo.currentIndexChanged.connect(self._on_currency_changed)
        self.bitcoin_symbol_combo.currentIndexChanged.connect(self._on_bitcoin_symbol_changed)
        self.button_set_app_lock_password.clicked.connect(self._on_set_app_lock_password)
        self.button_clear_app_lock_password.clicked.connect(self._on_clear_app_lock_password)

    def data_updated(self):
        """Data updated."""
        current_data = self.currency_combo.currentData()
        selected = current_data if isinstance(current_data, str) else self.config.currency
        self.currency_combo.populate(
            selected_currency=selected,
        )

    def _on_currency_changed(self, idx: int):
        """On currency changed."""
        currency = self.currency_combo.currentData()
        if not currency:
            return
        self.language_chooser.set_currency(currency)

    def _on_language_changed(self, idx: int):
        """On language changed."""
        self.language_chooser.switchLanguage(self.language_combo.itemData(idx))

    def _on_bitcoin_symbol_changed(self, _idx: int):
        """On bitcoin symbol changed."""
        symbol = self.bitcoin_symbol_combo.currentData()
        self.config.bitcoin_symbol = symbol or BitcoinSymbol.ISO
        self.language_chooser.signals_currency_switch.emit()

    def refresh_app_lock_status(self) -> None:
        has_password = self.config.has_app_lock_password()
        self.app_lock_password_status.setText(
            self.tr("Configured") if has_password else self.tr("Not configured")
        )
        self.button_set_app_lock_password.setText(self.tr("Change") if has_password else self.tr("Set"))
        self.button_clear_app_lock_password.setEnabled(has_password)

    def _on_set_app_lock_password(self) -> None:
        while True:
            password = PasswordCreation(
                parent=self,
                window_title=self.tr("App lock password"),
                label_text=self.tr("Enter app lock password:"),
            ).get_password()
            if password is None:
                return
            if password:
                self.config.set_app_lock_password(password)
                self.config.save()
                self.refresh_app_lock_status()
                self.signal_app_lock_password_changed.emit()
                return
            QMessageBox.warning(
                self,
                self.tr("Invalid password"),
                self.tr("App lock password cannot be empty."),
            )

    def _on_clear_app_lock_password(self) -> None:
        if not self.config.has_app_lock_password():
            return
        answer = QMessageBox.question(
            self,
            self.tr("Clear app lock password"),
            self.tr("Remove the app lock password?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.config.set_app_lock_password(None)
            self.config.save()
            self.refresh_app_lock_status()
            self.signal_app_lock_password_changed.emit()

    def updateUi(self):
        """UpdateUi."""
        self.label_language.setText("Language")
        self.label_currency.setText("Currency")
        self.label_bitcoin_symbol.setText("Bitcoin symbol")
        self.label_app_lock_password.setText("App lock")
        self.button_clear_app_lock_password.setText("Clear")
        self.refresh_app_lock_status()
