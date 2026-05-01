#
# Bitcoin Safe
# Copyright (C) 2025-2026 Andreas Griffin
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
#

from __future__ import annotations

import csv
import logging
from typing import cast

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.util import is_int
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.analyzers import AmountAnalyzer
from bitcoin_safe.gui.qt.labeledit import WalletLabelAndCategoryEdit
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.recipient_csv import export_recipients_csv, get_recipient_csv_header
from bitcoin_safe.gui.qt.ui_tx.header_widget import HeaderWidget
from bitcoin_safe.gui.qt.util import (
    Message,
    MessageType,
    set_margins,
    set_no_margins,
    svg_tools,
)
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.labels import LabelType
from bitcoin_safe.wallet import get_label_from_any_wallet, get_wallet_of_address, get_wallets

from ....pythonbdk_types import Recipient, is_address
from ....signals import SignalsMin, UpdateFilter, WalletFunctions
from ..currency_converter import CurrencyConverter
from ..invisible_scroll_area import InvisibleScrollArea
from .spinbox import BTCSpinBox, FiatSpinBox

logger = logging.getLogger(__name__)


class RecipientWidget(QWidget):
    def __init__(
        self,
        fx: FX | None,
        wallet_functions: WalletFunctions,
        network: bdk.Network,
        allow_edit=True,
        allow_label_edit=True,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.wallet_functions = wallet_functions
        self.fx = fx
        self.allow_edit = allow_edit
        self.allow_label_edit = allow_label_edit
        self.signal_tracker = SignalTracker()

        self.form_layout = QFormLayout()
        self.setLayout(self.form_layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        # works only for automatically created QLabels
        # self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        self.address_edit = AddressEdit(
            network=network, allow_edit=allow_edit, parent=self, wallet_functions=self.wallet_functions
        )
        self.label_line_edit = WalletLabelAndCategoryEdit(
            wallet_functions=self.wallet_functions,
            get_label_ref=self._get_label_ref,
            label_type=LabelType.addr,
            parent=self,
            dismiss_label_on_focus_loss=False,
        )

        self.amount_layout = QHBoxLayout()
        language_switch = cast(SignalProtocol[[]], self.wallet_functions.signals.language_switch)
        self.amount_spin_box = BTCSpinBox(
            network=network,
            signal_language_switch=language_switch,
            btc_symbol=self.wallet_functions.signals.get_btc_symbol() or BitcoinSymbol.ISO.value,
        )
        amount_analyzer = AmountAnalyzer()
        amount_analyzer.min_amount = 0
        amount_analyzer.max_amount = int(21e6 * 1e8)
        self.amount_spin_box.setAnalyzer(amount_analyzer)
        self.label_unit = QLabel(self.fx.config.bitcoin_symbol.value if self.fx else BitcoinSymbol.ISO.value)
        self.send_max_checkbox = QCheckBox()
        self.signal_tracker.connect(
            cast(SignalProtocol[[]], self.send_max_checkbox.clicked), self.on_send_max_button_click
        )
        self.amount_layout.addWidget(self.amount_spin_box)
        self.amount_layout.addWidget(self.label_unit)
        self.amount_layout.addWidget(self.send_max_checkbox)
        self.amount_layout.addStretch()

        self.address_label = QLabel()
        self.address_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.label_txlabel = QLabel()
        self.label_txlabel.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.amount_label = QLabel()
        self.amount_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        self.fiat_layout = QHBoxLayout()
        self.fiat_label = QLabel()
        self.fiat_unit = QLabel()
        self.fiat_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.fiat_spin_box = FiatSpinBox(
            fx=fx,
            signal_currency_changed=wallet_functions.signals.currency_switch,
            signal_language_switch=wallet_functions.signals.language_switch,
        )

        self.fiat_layout.addWidget(self.fiat_spin_box)
        self.fiat_layout.addWidget(self.fiat_unit)
        self.fiat_layout.addStretch()

        w = max(self.amount_spin_box.sizeHint().width(), self.fiat_spin_box.sizeHint().width())
        self.amount_spin_box.setFixedWidth(w)
        self.fiat_spin_box.setFixedWidth(w)

        self._currency_converter = CurrencyConverter(
            btc_spin_box=self.amount_spin_box, fiat_spin_box=self.fiat_spin_box
        )

        self.form_layout.addRow(self.address_label, self.address_edit)
        self.form_layout.addRow(self.label_txlabel, self.label_line_edit)
        self.form_layout.addRow(self.fiat_label, self.fiat_layout)
        self.form_layout.addRow(self.amount_label, self.amount_layout)

        self.set_allow_edit(allow_edit)
        self.label_line_edit.set_label_readonly(not allow_label_edit)

        # signals
        self.signal_tracker.connect(self.address_edit.signal_text_change, self.on_address_change)
        self.signal_tracker.connect(self.address_edit.signal_bip21_input, self.on_address_bip21_input)
        self.signal_tracker.connect(wallet_functions.signals.any_wallet_updated, self.update_with_filter)
        self.signal_tracker.connect(self.wallet_functions.signals.language_switch, self.updateUi)
        self.signal_tracker.connect(self.wallet_functions.signals.currency_switch, self.updateUi)

    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        """Update with filter."""
        if not self.address:
            return

        should_update = False
        if should_update or self.address in update_filter.addresses:
            should_update = True

        if not should_update:
            return

        self.label_line_edit.autofill_label_and_category(update_filter=update_filter)

    def _get_label_ref(self):
        """Get label ref."""
        return self.address_edit.address

    def on_address_change(self, value: str):
        """On address change."""
        self.label_line_edit.updateUi()
        self.label_line_edit.autofill_label_and_category()

    def set_currency(self):
        """Set currency."""
        if self.fx:
            currency_symbol = self.fx.get_currency_symbol()
            self.fiat_unit.setText(currency_symbol)

    def set_max(self, value: bool):
        """Set max."""
        self.send_max_checkbox.setChecked(value)
        # update the amount_spin_box text
        self.updateUi()

    def set_allow_edit(self, allow_edit: bool):
        """Set allow edit."""
        self.allow_edit = allow_edit

        self.send_max_checkbox.setVisible(allow_edit)

        self.amount_spin_box.setReadOnly(not allow_edit)
        self.fiat_spin_box.setReadOnly(not allow_edit)
        self.address_edit.set_allow_edit(allow_edit)

    def set_category(self, category: str):
        """Set category."""
        self.label_line_edit.set_category(category if category else "")

    def set_category_visible(self, value: bool):
        """Set category visible."""
        self.label_line_edit.set_category_visible(value)

    def set_fiat_value(self):
        """Set fiat value."""
        self.fiat_label.setHidden(not self.fx)
        self.fiat_spin_box.setHidden(not self.fx)
        if not self.fx:
            return

        fiat_value = self.fx.btc_to_fiat(amount=self.amount)
        if fiat_value is None:
            self.fiat_label.setHidden(True)
            self.fiat_spin_box.setHidden(True)
            return
        self.fiat_spin_box.setValue(fiat_value)

    def on_address_bip21_input(self, data: Data) -> None:
        """On address bip21 input."""
        if data.data_type == DataType.Bip21:
            if address := data.data.get("address"):
                try:
                    # overwrite address with correct formatting if possible
                    address = str(bdk.Address(address, self.address_edit.network))
                except Exception:
                    pass
                self.address_edit.address = address
            if amount := data.data.get("amount"):
                self.amount = amount
            if label := data.data.get("label"):
                self.label_line_edit.set_label(label)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.address_label.setText(self.tr("Address"))
        self.label_txlabel.setText(self.tr("Label"))
        self.amount_label.setText(self.tr("Amount"))
        self.fiat_label.setText(self.tr("Value"))

        self.label_line_edit.set_placeholder(self.tr("Enter label here"))
        self.send_max_checkbox.setText(self.tr("Send max"))

        self.amount_spin_box.set_max(self.send_max_checkbox.isChecked())
        self.fiat_spin_box.set_max(self.send_max_checkbox.isChecked())

        self.address_edit.updateUi()
        self.label_line_edit.updateUi()
        self.set_currency()

    def showEvent(self, a0) -> None:
        # this is necessary, otherwise the background color of the
        # address_line_edit.input_field is not updated properly when setting the adddress
        """ShowEvent."""
        self.updateUi()

    def on_send_max_button_click(self) -> None:
        """On send max button click."""
        if not self.allow_edit:
            return
        self.updateUi()

    @property
    def address(self) -> str:
        """Address."""
        return self.address_edit.address

    @address.setter
    def address(self, value: str) -> None:
        """Address."""
        self.address_edit.address = value

    @property
    def category(self) -> str:
        """Category."""
        return self.label_line_edit.category()

    @category.setter
    def category(self, value: str) -> None:
        """Category."""
        self.label_line_edit.set_category(value)

    @property
    def label(self) -> str:
        """Label."""
        return self.label_line_edit.label()

    @label.setter
    def label(self, value: str) -> None:
        """Label."""
        self.label_line_edit.set_label(value)

    @property
    def amount(self) -> int:
        """Amount."""
        return self.amount_spin_box.value()

    @amount.setter
    def amount(self, value: int) -> None:
        """Amount."""
        self.amount_spin_box.setValue(value)
        self.set_fiat_value()

    @property
    def enabled(self) -> bool:
        """Enabled."""
        return not self.address_edit.input_field.isReadOnly()

    @enabled.setter
    def enabled(self, state: bool) -> None:
        """Enabled."""
        self.address_edit.setReadOnly(not state)
        self.label_line_edit.set_label_readonly(not state)
        self.amount_spin_box.setReadOnly(not state)
        self.send_max_checkbox.setEnabled(state)

    def close(self) -> bool:
        self.signal_tracker.disconnect_all()
        return super().close()


class NotificationBarRecipient(NotificationBar):
    def __init__(
        self,
        signals_min: SignalsMin,
        has_close_button=True,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=has_close_button,
            parent=parent,
        )
        self.signals_min = signals_min
        self.wallet_id: str | None = None

        self.closeButton.setFlat(True)
        self.optionalButton.hide()

        self.updateUi()
        self.signals_min.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        if self.wallet_id is None:
            self.icon_label.setText("")
            self.set_icon(svg_tools.get_QIcon("bi--person-no-left-margin.svg"))
        else:
            self.icon_label.setText(
                self.tr("This address belongs to wallet: <b>{wallet_id}</b>").format(wallet_id=self.wallet_id)
            )
            self.set_icon(svg_tools.get_QIcon("bi--wallet2.svg"))
        self.icon_label.setToolTip("")

    def set_wallet_id(self, wallet_id: str | None):
        """Set wallet id."""
        self.wallet_id = wallet_id
        self.updateUi()


class HiddenRecipientsPlaceholder(QWidget):
    def __init__(self, hidden_count: int, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.hidden_count = hidden_count

        layout = QVBoxLayout(self)
        set_no_margins(layout)

        self.label_dots = QLabel(".\n.\n.")
        self.label_dots.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.label_count = QLabel()
        self.label_count.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.label_dots)
        layout.addWidget(self.label_count)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        self.label_count.setText(self.tr("({count} outputs)").format(count=self.hidden_count))
        self.setToolTip(
            self.tr("{count} outputs without a known wallet or label are hidden here.").format(
                count=self.hidden_count
            )
        )


class RecipientBox(QWidget):
    signal_close = cast(SignalProtocol[[RecipientWidget]], pyqtSignal(RecipientWidget))
    signal_clicked_send_max_button = cast(SignalProtocol[[RecipientWidget]], pyqtSignal(RecipientWidget))
    signal_address_text_changed = cast(SignalProtocol[[RecipientWidget]], pyqtSignal(RecipientWidget))
    signal_amount_changed = cast(SignalProtocol[[RecipientWidget]], pyqtSignal(RecipientWidget))

    def __init__(
        self,
        fx: FX | None,
        wallet_functions: WalletFunctions,
        network: bdk.Network,
        show_header_bar=True,
        allow_edit=True,
        groupbox_style=False,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.wallet_functions = wallet_functions
        self.fx = fx
        self.main_layout = QVBoxLayout(self)
        set_no_margins(self.main_layout)

        # Common content to display
        self.content_widget = QGroupBox() if groupbox_style else QWidget()
        self.main_layout.addWidget(self.content_widget)
        self._layout = QVBoxLayout(self.content_widget)

        set_margins(self._layout, {Qt.Edge.TopEdge: 0, Qt.Edge.LeftEdge: 0, Qt.Edge.RightEdge: 0})
        self.recipient_widget = RecipientWidget(
            wallet_functions=wallet_functions,
            network=network,
            allow_edit=allow_edit,
            parent=self,
            fx=fx,
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.notification_bar = NotificationBarRecipient(
            signals_min=wallet_functions.signals,
            has_close_button=allow_edit,
            parent=self,
        )
        self.notification_bar.setHidden(not show_header_bar)
        self._layout.addWidget(self.notification_bar)
        self._layout.addWidget(self.recipient_widget)
        set_margins(
            self.recipient_widget.form_layout,
            {Qt.Edge.LeftEdge: self.notification_bar._layout.contentsMargins().left()},
        )

        # connect signals
        self.notification_bar.closeButton.clicked.connect(self.on_close)
        self.recipient_widget.amount_spin_box.valueChanged.connect(self.on_amount_spin_box_changed)
        self.recipient_widget.send_max_checkbox.clicked.connect(self.on_send_max_button)

        self.recipient_widget.address_edit.signal_text_change.connect(self.on_address_text_changed)

    def on_close(self):
        """On close."""
        self.signal_close.emit(self.recipient_widget)

    def on_send_max_button(self):
        """On send max button."""
        self.signal_clicked_send_max_button.emit(self.recipient_widget)

    def on_address_text_changed(self, text: str):
        """On address text changed."""
        self.signal_address_text_changed.emit(self.recipient_widget)
        self.autofill_wallet_id()

    def on_amount_spin_box_changed(self):
        """On amount spin box changed."""
        self.signal_amount_changed.emit(self.recipient_widget)

    def set_allow_edit(self, allow_edit: bool):
        """Set allow edit."""
        self.recipient_widget.set_allow_edit(allow_edit)
        self.notification_bar.set_has_close_button(allow_edit)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.recipient_widget.updateUi()
        self.autofill_wallet_id()

    def showEvent(self, a0: QShowEvent | None) -> None:
        # this is necessary, otherwise the background color of the
        # address_line_edit.input_field is not updated properly when setting the adddress
        """ShowEvent."""
        self.updateUi()

    @property
    def address(self) -> str:
        """Address."""
        return self.recipient_widget.address

    @address.setter
    def address(self, value: str) -> None:
        """Address."""
        self.recipient_widget.address = value

    @property
    def label(self) -> str:
        """Label."""
        return self.recipient_widget.label

    @label.setter
    def label(self, value: str) -> None:
        """Label."""
        self.recipient_widget.label = value

    @property
    def category(self) -> str:
        """Category."""
        return self.recipient_widget.category

    @category.setter
    def category(self, value: str) -> None:
        """Category."""
        self.recipient_widget.category = value

    @property
    def amount(self) -> int:
        """Amount."""
        return self.recipient_widget.amount

    @amount.setter
    def amount(self, value: int) -> None:
        """Amount."""
        self.recipient_widget.amount = value

    @property
    def enabled(self) -> bool:
        """Enabled."""
        return not self.recipient_widget.enabled

    @enabled.setter
    def enabled(self, state: bool) -> None:
        """Enabled."""
        self.recipient_widget.enabled = state

    def autofill_wallet_id(self):
        """Autofill wallet id."""
        address = self.recipient_widget.address_edit.address
        wallet = get_wallet_of_address(address, self.recipient_widget.wallet_functions)
        self.notification_bar.set_wallet_id(wallet.id if wallet else None)

    def close(self) -> bool:
        self.recipient_widget.close()
        return super().close()


class Recipients(QWidget):
    MAX_VISIBLE_RECIPIENTS = 200

    signal_added_recipient = cast(SignalProtocol[[RecipientBox]], pyqtSignal(RecipientBox))
    signal_removed_recipient = cast(SignalProtocol[[]], pyqtSignal())
    signal_clicked_send_max_button = cast(SignalProtocol[[RecipientWidget]], pyqtSignal(RecipientWidget))
    signal_address_text_changed = cast(SignalProtocol[[RecipientWidget]], pyqtSignal(RecipientWidget))
    signal_amount_changed = cast(SignalProtocol[[RecipientWidget]], pyqtSignal(RecipientWidget))
    signal_recipients_imported = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        wallet_functions: WalletFunctions,
        network: bdk.Network,
        fx: FX | None,
        header_widget: HeaderWidget,
        allow_edit=True,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.wallet_functions = wallet_functions
        self.fx = fx
        self.allow_edit = allow_edit
        self.network = network

        self.header_widget = header_widget
        self.setup_header_widget()
        self._all_recipients: list[Recipient] = []
        self._recipient_box_indices: dict[RecipientBox, int] = {}
        self._hidden_recipient_placeholders: list[HiddenRecipientsPlaceholder] = []

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        set_no_margins(self.main_layout)

        self.recipient_list = InvisibleScrollArea()
        self.recipient_list.setWidgetResizable(True)
        self.recipient_list_content_layout = QVBoxLayout(self.recipient_list.content_widget)

        set_no_margins(self.recipient_list_content_layout)
        self.recipient_list_content_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.main_layout.addWidget(self.recipient_list)

        self.set_allow_edit(allow_edit)

        self.updateUi()
        self.wallet_functions.signals.language_switch.connect(self.updateUi)

    def setup_header_widget(self):
        """Setup header widget."""
        self.header_widget.set_icon("bi--recipients.svg")
        self.header_widget.label_title.setText(self.tr("Recipients"))

        self.add_recipient_button = QPushButton("")
        self.add_recipient_button.setIcon(svg_tools.get_QIcon("bi--person-add.svg"))
        self.add_recipient_button.clicked.connect(self.add_recipient)

        self.toolbutton_csv = QToolButton()
        self.toolbutton_csv.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbutton_csv.setIcon(svg_tools.get_QIcon("bi--filetype-csv.svg"))

        menu = Menu(self)
        self.action_import_csv = menu.add_action(
            "", self.import_csv, icon=svg_tools.get_QIcon("bi--upload.svg")
        )
        self.action_export_csv = menu.add_action(
            "", self.on_action_export_csv, icon=svg_tools.get_QIcon("bi--download.svg")
        )
        menu.addSeparator()
        self.action_export_csv_template = menu.add_action(
            "", self.on_action_export_csv_template, icon=svg_tools.get_QIcon("bi--layout-three-columns.svg")
        )

        self.toolbutton_csv.setMenu(menu)
        self.toolbutton_csv.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.header_widget.h_laylout.addWidget(self.add_recipient_button)
        self.header_widget.h_laylout.addWidget(self.toolbutton_csv)

    def update_recipient_title(self):
        """Update recipient title."""
        self.header_widget.label_title.setText(self.tr("Recipients ({count})").format(count=self.count()))

    def set_allow_edit(self, allow_edit: bool):
        """Set allow edit."""
        self.allow_edit = allow_edit
        self.action_export_csv_template.setVisible(allow_edit)
        self.action_import_csv.setVisible(allow_edit)
        self.add_recipient_button.setVisible(allow_edit)

        for recipient_tab_widget in self.recipient_list.content_widget.findChildren(RecipientBox):
            recipient_tab_widget.set_allow_edit(allow_edit=allow_edit)

    def set_csv_toolbutton_visible(self, visible: bool) -> None:
        """Set whether the CSV toolbutton is visible."""
        self.toolbutton_csv.setVisible(visible)

    def on_action_export_csv_template(self):
        """On action export csv template."""
        self.export_csv([])

    def on_action_export_csv(self):
        """On action export csv."""
        self.export_csv(self.recipients)

    def export_csv(self, recipients: list[Recipient], file_path: str | None = None):
        """Export csv."""
        return export_recipients_csv(
            recipients=recipients,
            network=self.network,
            parent=self,
            file_path=file_path,
        )

    def import_csv(self, file_path: str | None = None):
        """Import csv."""
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("Open CSV"),
                "",
                self.tr("All Files (*);;CSV (*.csv)"),
            )
            if not file_path:
                logger.info(self.tr("No file selected"))
                return

        with open(file_path) as file:
            reader = csv.reader(file)
            data = list(reader)
            header = data[0]

        if get_recipient_csv_header(self.network) != header:
            Message(
                self.tr("Please use the CSV template and include the header row."),
                type=MessageType.Error,
                parent=self,
            )
            return

        if len(data) <= 1:
            Message(self.tr("No rows recognized"), type=MessageType.Error, parent=self)
            return

        rows = data[1:]

        # check that all amounts are int, and addresses valid
        for row in rows:
            if not is_address(row[0], network=self.network):
                Message(
                    self.tr("{address} is not a valid address!").format(address=row[0]),
                    type=MessageType.Error,
                    parent=self,
                )
                return
            if not is_int(row[1]):
                Message(
                    self.tr("{amount} is not a valid integer!").format(amount=row[1]),
                    type=MessageType.Error,
                    parent=self,
                )
                return

        new_recipients = [Recipient(address=row[0], amount=int(row[1]), label=row[2]) for row in rows]

        self.recipients = new_recipients
        self.signal_recipients_imported.emit()

    def updateUi(self) -> None:
        """UpdateUi."""
        self.add_recipient_button.setText(self.tr("Add Recipient"))
        if self.header_widget:
            self.update_recipient_title()

        self.toolbutton_csv.setText(self.tr("Import/Export") if self.allow_edit else self.tr("Export"))

        self.action_export_csv_template.setText(self.tr("Export CSV Template"))
        self.action_import_csv.setText(self.tr("Import CSV file"))

        self.action_export_csv.setText(self.tr("Export as CSV file"))
        for placeholder in self._hidden_recipient_placeholders:
            placeholder.updateUi()

    def _insert_list_widget(self, widget: QWidget) -> None:
        """Insert a widget into the recipients list."""
        index = self.recipient_list_content_layout.indexOf(self.add_recipient_button)
        if index >= 0:
            self.recipient_list_content_layout.insertWidget(index, widget)
            return
        self.recipient_list_content_layout.addWidget(widget)

    def _create_recipient_box(self, recipient: Recipient) -> RecipientBox:
        """Create a recipient box for a single visible recipient."""
        recipient_box = RecipientBox(
            wallet_functions=self.wallet_functions,
            network=self.network,
            allow_edit=self.allow_edit and not recipient.read_only,
            groupbox_style=True,
            fx=self.fx,
        )
        recipient_box.address = recipient.address
        recipient_box.amount = recipient.amount
        recipient_box.recipient_widget.set_max(recipient.checked_max_amount)
        if recipient.label is not None:
            recipient_box.label = recipient.label
        return recipient_box

    def _connect_recipient_box(self, recipient_box: RecipientBox) -> None:
        """Connect a visible recipient box."""
        recipient_box.signal_close.connect(self.ui_remove_recipient_widget)
        recipient_box.signal_clicked_send_max_button.connect(self.signal_clicked_send_max_button)
        recipient_box.signal_clicked_send_max_button.connect(self.signal_amount_changed)
        recipient_box.signal_address_text_changed.connect(self.signal_address_text_changed)
        recipient_box.signal_amount_changed.connect(self.signal_amount_changed)

    def _clear_rendered_recipient_widgets(self) -> None:
        """Remove all rendered recipient widgets."""
        for recipient_box in list(self._recipient_box_indices):
            self.recipient_list_content_layout.removeWidget(recipient_box)
            recipient_box.hide()
            recipient_box.setParent(None)
            recipient_box.close()
        self._recipient_box_indices.clear()
        for placeholder in self._hidden_recipient_placeholders:
            self.recipient_list_content_layout.removeWidget(placeholder)
            placeholder.hide()
            placeholder.setParent(None)
            placeholder.close()
        self._hidden_recipient_placeholders.clear()

    def _sync_visible_recipient_boxes(self) -> None:
        """Persist edits from the visible widgets back into the full recipient list."""
        for recipient_box, recipient_index in self._recipient_box_indices.items():
            self._all_recipients[recipient_index] = Recipient(
                recipient_box.address,
                recipient_box.amount,
                recipient_box.label if recipient_box.label else None,
                checked_max_amount=recipient_box.recipient_widget.send_max_checkbox.isChecked(),
            )

    def _get_visible_recipient_indices(self, force_visible_indices: set[int] | None = None) -> set[int]:
        """Return the indexes that should get a RecipientBox."""
        if len(self._all_recipients) <= self.MAX_VISIBLE_RECIPIENTS:
            visible_indices = set(range(len(self._all_recipients)))
        else:
            wallets = get_wallets(self.wallet_functions)
            visible_indices = {
                index
                for index, recipient in enumerate(self._all_recipients)
                if (
                    not recipient.address
                    or (recipient.label and recipient.label.strip())
                    or any(wallet.is_my_address_with_peek(recipient.address) for wallet in wallets)
                    or get_label_from_any_wallet(
                        label_type=LabelType.addr,
                        ref=recipient.address,
                        wallet_functions=self.wallet_functions,
                        wallets=wallets,
                        autofill_from_txs=False,
                    )
                )
            }
        if force_visible_indices:
            visible_indices.update(force_visible_indices)
        return visible_indices

    def _rebuild_recipient_boxes(self, force_visible_indices: set[int] | None = None) -> None:
        """Rebuild the visible recipient boxes from the full list."""
        self._sync_visible_recipient_boxes()
        self._clear_rendered_recipient_widgets()

        visible_indices = self._get_visible_recipient_indices(force_visible_indices=force_visible_indices)
        hidden_count = 0
        for recipient_index, recipient in enumerate(self._all_recipients):
            if recipient_index not in visible_indices:
                hidden_count += 1
                continue
            if hidden_count:
                placeholder = HiddenRecipientsPlaceholder(hidden_count=hidden_count, parent=self)
                self._insert_list_widget(placeholder)
                self._hidden_recipient_placeholders.append(placeholder)
                hidden_count = 0
            recipient_box = self._create_recipient_box(recipient)
            self._insert_list_widget(recipient_box)
            self._recipient_box_indices[recipient_box] = recipient_index
            self._connect_recipient_box(recipient_box)
        if hidden_count:
            placeholder = HiddenRecipientsPlaceholder(hidden_count=hidden_count, parent=self)
            self._insert_list_widget(placeholder)
            self._hidden_recipient_placeholders.append(placeholder)
        self.update_recipient_title()

    def add_recipient(self, recipient: Recipient | None = None) -> RecipientBox:
        """Add recipient."""
        recipient = recipient.clone() if recipient else Recipient("", 0)
        recipient_index = len(self._all_recipients)
        self._sync_visible_recipient_boxes()
        self._all_recipients.append(recipient)
        self._rebuild_recipient_boxes(force_visible_indices={recipient_index})
        recipient_box = next(
            box
            for box, current_index in self._recipient_box_indices.items()
            if current_index == recipient_index
        )
        self.signal_added_recipient.emit(recipient_box)
        return recipient_box

    def ui_remove_recipient_widget(self, recipient_widget: RecipientWidget) -> None:
        """Ui remove recipient widget."""
        self.remove_recipient_widget(recipient_widget)

        if not self.recipients:
            self.add_recipient()

    def remove_recipient_widget(self, recipient_widget: RecipientWidget) -> None:
        """Remove recipient widget."""
        self._sync_visible_recipient_boxes()
        for widget, recipient_index in list(self._recipient_box_indices.items()):
            if widget.recipient_widget == recipient_widget:
                del self._all_recipients[recipient_index]
                self._clear_rendered_recipient_widgets()
                self._rebuild_recipient_boxes()
                self.signal_removed_recipient.emit()
                break

    @property
    def recipients(self) -> list[Recipient]:
        """Recipients."""
        self._sync_visible_recipient_boxes()
        return [recipient.clone() for recipient in self._all_recipients]

    @recipients.setter
    def recipients(self, recipient_list: list[Recipient]) -> None:
        """Recipients."""
        self._clear_rendered_recipient_widgets()
        self._all_recipients = [recipient.clone() for recipient in recipient_list]
        self._rebuild_recipient_boxes()

    def get_recipient_group_boxes(self) -> list[RecipientBox]:
        """Get recipient group boxes."""
        return [
            recipient_box
            for recipient_box, _recipient_index in sorted(
                self._recipient_box_indices.items(),
                key=lambda item: item[1],
            )
        ]

    def get_address_labels_dict(self) -> dict[str, str]:
        """Get non-empty labels keyed by address."""
        self._sync_visible_recipient_boxes()
        wallets = get_wallets(self.wallet_functions)
        return {
            recipient.address: label
            for recipient in self._all_recipients
            if recipient.address
            and (
                label := recipient.label
                or get_label_from_any_wallet(
                    label_type=LabelType.addr,
                    ref=recipient.address,
                    wallet_functions=self.wallet_functions,
                    wallets=wallets,
                    autofill_from_txs=False,
                )
            )
        }

    def count(self) -> int:
        """Count."""
        return len(self._all_recipients)

    def close(self) -> bool:
        for box in self.get_recipient_group_boxes():
            box.close()
        return super().close()
