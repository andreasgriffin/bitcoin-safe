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


import csv
import logging
from pathlib import Path
from typing import Any, List

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.analyzers import AmountAnalyzer
from bitcoin_safe.gui.qt.labeledit import WalletLabelAndCategoryEdit
from bitcoin_safe.gui.qt.util import Message, MessageType, read_QIcon
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.labels import LabelType
from bitcoin_safe.typestubs import TypedPyQtSignal
from bitcoin_safe.wallet import get_wallet_of_address

from ...pythonbdk_types import Recipient, is_address
from ...signals import Signals
from ...util import is_int, unit_sat_str, unit_str
from .invisible_scroll_area import InvisibleScrollArea
from .spinbox import BTCSpinBox

logger = logging.getLogger(__name__)


class CloseButton(QPushButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(16, 16))  # Adjust the size as needed

    def paintEvent(self, event) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        option.initFrom(self)
        option.features = QStyleOptionButton.ButtonFeature.None_
        option.icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_TabCloseButton)  # type: ignore[attr-defined]
        option.iconSize = QSize(14, 14)  # Adjust icon size as needed
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class RecipientWidget(QWidget):
    def __init__(
        self,
        signals: Signals,
        network: bdk.Network,
        allow_edit=True,
        allow_label_edit=True,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.signals = signals
        self.allow_edit = allow_edit
        self.allow_label_edit = allow_label_edit

        self.form_layout = QFormLayout()
        self.setLayout(self.form_layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        # works only for automatically created QLabels
        # self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        self.address_edit = AddressEdit(
            network=network, allow_edit=allow_edit, parent=self, signals=self.signals
        )
        self.label_line_edit = WalletLabelAndCategoryEdit(
            signals=self.signals,
            get_label_ref=self._get_label_ref,
            label_type=LabelType.addr,
            parent=self,
            dismiss_label_on_focus_loss=False,
        )

        self.amount_layout = QHBoxLayout()
        self.amount_spin_box = BTCSpinBox(self.signals.get_network())
        amount_analyzer = AmountAnalyzer()
        amount_analyzer.min_amount = 0
        amount_analyzer.max_amount = int(21e6 * 1e8)
        self.amount_spin_box.setAnalyzer(amount_analyzer)
        self.label_unit = QLabel(unit_str(self.signals.get_network()))
        self.send_max_button = QPushButton()
        self.send_max_button.setCheckable(True)
        self.send_max_button.setMaximumWidth(80)
        self.send_max_button.clicked.connect(self.on_send_max_button_click)
        self.amount_layout.addWidget(self.amount_spin_box)
        self.amount_layout.addWidget(self.label_unit)
        self.amount_layout.addWidget(self.send_max_button)

        self.address_label = QLabel()
        self.address_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.label_txlabel = QLabel()
        self.label_txlabel.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.amount_label = QLabel()
        self.amount_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        self.form_layout.addRow(self.address_label, self.address_edit)
        self.form_layout.addRow(self.label_txlabel, self.label_line_edit)
        self.form_layout.addRow(self.amount_label, self.amount_layout)

        self.set_allow_edit(allow_edit)
        self.label_line_edit.set_label_readonly(not allow_label_edit)

        self.updateUi()

        # signals
        self.signals.language_switch.connect(self.updateUi)
        self.address_edit.signal_text_change.connect(self.on_address_change)
        self.address_edit.signal_bip21_input.connect(self.on_address_bip21_input)

    def _get_label_ref(self):
        return self.address_edit.address

    def on_address_change(self, value: str):
        self.label_line_edit.updateUi()
        self.label_line_edit.autofill_label_and_category()

    def set_max(self, value: bool):
        self.send_max_button.setChecked(value)
        # update the amount_spin_box text
        self.updateUi()

    def set_allow_edit(self, allow_edit: bool):
        self.allow_edit = allow_edit

        self.send_max_button.setVisible(allow_edit)

        self.address_edit.setReadOnly(not allow_edit)
        self.amount_spin_box.setReadOnly(not allow_edit)
        self.address_edit.set_allow_edit(allow_edit)

    def set_category(self, category: str):
        self.label_line_edit.set_category(category if category else "")

    def set_category_visible(self, value: bool):
        self.label_line_edit.set_category_visible(value)

    def on_address_bip21_input(self, data: Data) -> None:
        if data.data_type == DataType.Bip21:
            if data.data.get("address"):
                self.address_edit.address = data.data.get("address")
            if data.data.get("amount"):
                self.amount_spin_box.setValue(data.data.get("amount"))
            if data.data.get("label"):
                self.label_line_edit.set_label(data.data.get("label"))

    def updateUi(self) -> None:
        self.address_label.setText(self.tr("Address"))
        self.label_txlabel.setText(self.tr("Label"))
        self.amount_label.setText(self.tr("Amount"))

        self.label_line_edit.set_placeholder(self.tr("Enter label here"))
        self.send_max_button.setText(self.tr("Send max"))

        self.amount_spin_box.set_max(self.send_max_button.isChecked())

        self.address_edit.updateUi()
        self.label_line_edit.updateUi()

    def showEvent(self, event) -> None:
        # this is necessary, otherwise the background color of the
        # address_line_edit.input_field is not updated properly when setting the adddress
        self.updateUi()

    def on_send_max_button_click(self) -> None:
        if not self.allow_edit:
            return
        self.updateUi()

    @property
    def address(self) -> str:
        return self.address_edit.address

    @address.setter
    def address(self, value: str) -> None:
        self.address_edit.address = value

    @property
    def category(self) -> str:
        return self.label_line_edit.category()

    @category.setter
    def category(self, value: str) -> None:
        self.label_line_edit.set_category(value)

    @property
    def label(self) -> str:
        return self.label_line_edit.label()

    @label.setter
    def label(self, value: str) -> None:
        self.label_line_edit.set_label(value)

    @property
    def amount(self) -> int:
        return self.amount_spin_box.value()

    @amount.setter
    def amount(self, value: int) -> None:
        self.amount_spin_box.setValue(value)

    @property
    def enabled(self) -> bool:
        return not self.address_edit.input_field.isReadOnly()

    @enabled.setter
    def enabled(self, state: bool) -> None:
        self.address_edit.setReadOnly(not state)
        self.label_line_edit.set_label_readonly(not state)
        self.amount_spin_box.setReadOnly(not state)
        self.send_max_button.setEnabled(state)


class RecipientTabWidget(QTabWidget):
    signal_close: "TypedPyQtSignal[RecipientTabWidget]" = pyqtSignal(QTabWidget)  # type: ignore
    signal_clicked_send_max_button: "TypedPyQtSignal[RecipientWidget]" = pyqtSignal(RecipientWidget)  # type: ignore
    signal_amount_changed: "TypedPyQtSignal[RecipientWidget]" = pyqtSignal(RecipientWidget)  # type: ignore

    def __init__(
        self,
        signals: Signals,
        network: bdk.Network,
        allow_edit=True,
        title="",
        parent=None,
        tab_string=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setTabsClosable(allow_edit)
        self.title = title
        self.tab_string = tab_string if tab_string else self.tr('Wallet "{id}"')
        self.recipient_widget = RecipientWidget(
            signals=signals,
            network=network,
            allow_edit=allow_edit,
            parent=self,
        )

        self.addTab(self.recipient_widget, read_QIcon("person.svg"), title)

        # connect signals
        self.tabCloseRequested.connect(self.on_tabCloseRequested)
        self.recipient_widget.amount_spin_box.valueChanged.connect(self.on_amount_spin_box_changed)
        self.recipient_widget.send_max_button.clicked.connect(self.on_send_max_button)

        self.recipient_widget.address_edit.signal_text_change.connect(self.autofill_tab_text)

    def on_tabCloseRequested(self):
        self.signal_close.emit(self)

    def on_send_max_button(self):
        self.signal_clicked_send_max_button.emit(self.recipient_widget)

    def on_amount_spin_box_changed(self):
        self.signal_amount_changed.emit(self.recipient_widget)

    def set_allow_edit(self, allow_edit: bool):
        self.recipient_widget.set_allow_edit(allow_edit)
        self.setTabsClosable(allow_edit)

    def updateUi(self) -> None:
        self.recipient_widget.updateUi()
        self.autofill_tab_text()

    def showEvent(self, event) -> None:
        # this is necessary, otherwise the background color of the
        # address_line_edit.input_field is not updated properly when setting the adddress
        self.updateUi()

    @property
    def address(self) -> str:
        return self.recipient_widget.address

    @address.setter
    def address(self, value: str) -> None:
        self.recipient_widget.address = value

    @property
    def label(self) -> str:
        return self.recipient_widget.label

    @label.setter
    def label(self, value: str) -> None:
        self.recipient_widget.label = value

    @property
    def category(self) -> str:
        return self.recipient_widget.category

    @category.setter
    def category(self, value: str) -> None:
        self.recipient_widget.category = value

    @property
    def amount(self) -> int:
        return self.recipient_widget.amount

    @amount.setter
    def amount(self, value: int) -> None:
        self.recipient_widget.amount = value

    @property
    def enabled(self) -> bool:
        return not self.recipient_widget.enabled

    @enabled.setter
    def enabled(self, state: bool) -> None:
        self.recipient_widget.enabled = state

    def autofill_tab_text(self, *args):
        wallet = get_wallet_of_address(
            self.recipient_widget.address_edit.address, self.recipient_widget.signals
        )
        if wallet:
            self.setTabText(self.indexOf(self.recipient_widget), self.tab_string.format(id=wallet.id))
            self.setTabBarAutoHide(
                not self.tabText(self.indexOf(self.recipient_widget)) and not self.recipient_widget.allow_edit
            )
        else:
            self.setTabText(self.indexOf(self.recipient_widget), self.title)
            self.setTabBarAutoHide(
                not self.tabText(self.indexOf(self.recipient_widget)) and not self.recipient_widget.allow_edit
            )


class Recipients(QWidget):
    signal_added_recipient: TypedPyQtSignal[RecipientTabWidget] = pyqtSignal(RecipientTabWidget)  # type: ignore
    signal_removed_recipient: TypedPyQtSignal[RecipientTabWidget] = pyqtSignal(RecipientTabWidget)  # type: ignore
    signal_clicked_send_max_button: TypedPyQtSignal[RecipientWidget] = pyqtSignal(RecipientWidget)  # type: ignore
    signal_amount_changed: TypedPyQtSignal[RecipientWidget] = pyqtSignal(RecipientWidget)  # type: ignore

    def __init__(self, signals: Signals, network: bdk.Network, allow_edit=True) -> None:
        super().__init__()
        self.signals = signals
        self.allow_edit = allow_edit
        self.network = network

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.recipient_list = InvisibleScrollArea()
        self.recipient_list.setWidgetResizable(True)
        self.recipient_list_content_layout = QVBoxLayout(self.recipient_list.content_widget)

        self.recipient_list_content_layout.setContentsMargins(0, 0, 0, 0)  # Set all margins to zero
        self.recipient_list_content_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.main_layout.addWidget(self.recipient_list)

        self.add_recipient_button = QPushButton("")
        self.add_recipient_button.setMaximumWidth(150)
        self.add_recipient_button.setIcon(read_QIcon("add-person.svg"))
        self.add_recipient_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_recipient_button.clicked.connect(self.add_recipient)

        self.toolbutton_csv = QToolButton()
        self.toolbutton_csv.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbutton_csv.setIcon(read_QIcon("csv-file.svg"))

        menu = Menu(self)
        self.action_export_csv_template = menu.add_action(
            "", self.on_action_export_csv_template, icon=read_QIcon("csv-file.svg")
        )
        self.action_import_csv = menu.add_action("", self.import_csv, icon=read_QIcon("csv-file.svg"))
        menu.addSeparator()
        self.action_export_csv = menu.add_action(
            "", self.on_action_export_csv, icon=read_QIcon("csv-file.svg")
        )

        self.toolbutton_csv.setMenu(menu)
        self.toolbutton_csv.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # button bar
        self.button_bar = QWidget(self.recipient_list.content_widget)
        self.button_bar_layout = QHBoxLayout(self.button_bar)
        self.button_bar_layout.setContentsMargins(0, 0, 0, 0)

        self.button_bar_layout.addWidget(self.add_recipient_button)
        self.button_bar_layout.addItem(
            QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        )
        self.button_bar_layout.addWidget(self.toolbutton_csv)

        self.main_layout.addWidget(self.button_bar)
        self.set_allow_edit(allow_edit)

        self.updateUi()
        self.signals.language_switch.connect(self.updateUi)

    def set_allow_edit(self, allow_edit: bool):
        self.allow_edit = allow_edit
        self.button_bar.setVisible(allow_edit)

        for recipient_tab_widget in self.recipient_list.content_widget.findChildren(RecipientTabWidget):
            recipient_tab_widget.set_allow_edit(allow_edit=allow_edit)

    def as_list(self, recipients: List[Recipient], include_header=True) -> List[List[Any]]:
        table: List[List[Any]] = []

        if include_header:
            table.append(self._get_csv_header())

        for recipient in recipients:
            row: List[Any] = [recipient.address, recipient.amount, recipient.label]
            table.append(row)
        return table

    def _get_csv_header(self) -> List[str]:
        return [
            self.tr("Address"),
            self.tr("Amount [{unit}]").format(unit=unit_sat_str(self.network)),
            self.tr("Label"),
        ]

    def on_action_export_csv_template(self):
        self.export_csv([])

    def on_action_export_csv(self):
        self.export_csv(self.recipients)

    def export_csv(self, recipients: List[Recipient], file_path: str | Path | None = None) -> Path | None:

        if not file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                self.tr("Export csv"),
                f"recipients.csv",
                self.tr("All Files (*);;Wallet Files (*.csv)"),
            )
            if not file_path:
                logger.info(self.tr("No file selected"))
                return None

        table = self.as_list(recipients)
        with open(str(file_path), "w") as file:
            writer = csv.writer(file)
            writer.writerows(table)

        logger.debug(f"CSV Table saved to {file_path}")
        return Path(file_path)

    def import_csv(self, file_path: str | None = None):

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

        with open(file_path, "r") as file:
            reader = csv.reader(file)
            data = list(reader)
            header = data[0]

        if self._get_csv_header() != header:
            Message(
                self.tr("Please use the CSV template and include the header row."), type=MessageType.Error
            )
            return

        if len(data) <= 1:
            Message(self.tr("No rows recognized"), type=MessageType.Error)
            return

        rows = data[1:]

        # check that all amounts are int, and addresses valid
        for row in rows:
            if not is_address(row[0], network=self.network):
                Message(
                    self.tr("{address} is not a valid address!").format(address=row[0]),
                    type=MessageType.Error,
                )
                return
            if not is_int(row[1]):
                Message(
                    self.tr("{amount} is not a valid integer!").format(amount=row[1]), type=MessageType.Error
                )
                return

        self.recipients = [Recipient(address=row[0], amount=int(row[1]), label=row[2]) for row in rows]

    def updateUi(self) -> None:
        self.recipient_list.setToolTip(self.tr("Recipients"))
        self.add_recipient_button.setText(self.tr("Add Recipient"))

        self.toolbutton_csv.setText(self.tr("Import/Export"))

        self.action_export_csv_template.setText(self.tr("Export CSV Template"))
        self.action_import_csv.setText(self.tr("Import CSV file"))

        self.action_export_csv.setText(self.tr("Export as CSV file"))

    def add_recipient(self, recipient: Recipient | None = None) -> RecipientTabWidget:
        if not recipient:
            recipient = Recipient("", 0)
        recipient_box = RecipientTabWidget(
            self.signals,
            network=self.network,
            allow_edit=self.allow_edit,
            title="Recipient" if self.allow_edit else "",
        )
        recipient_box.address = recipient.address
        recipient_box.amount = recipient.amount
        recipient_box.recipient_widget.set_max(recipient.checked_max_amount)
        if recipient.label is not None:
            recipient_box.label = recipient.label

        # insert before the button position
        def insert_before_button(new_widget: QWidget) -> None:
            index = self.recipient_list_content_layout.indexOf(self.add_recipient_button)
            if index >= 0:
                self.recipient_list_content_layout.insertWidget(index, new_widget)
            else:
                self.recipient_list_content_layout.addWidget(new_widget)

        insert_before_button(recipient_box)

        recipient_box.signal_close.connect(self.ui_remove_recipient_widget)
        recipient_box.signal_clicked_send_max_button.connect(self.signal_amount_changed.emit)
        self.signal_added_recipient.emit(recipient_box)
        return recipient_box

    def ui_remove_recipient_widget(self, recipient_box: RecipientTabWidget) -> None:
        self.remove_recipient_widget(recipient_box)

        if not self.recipients:
            self.add_recipient()

    def remove_recipient_widget(self, recipient_box: RecipientTabWidget) -> None:
        self.recipient_list_content_layout.removeWidget(recipient_box)
        recipient_box.hide()
        recipient_box.setParent(None)
        self.signal_removed_recipient.emit(recipient_box)

    @property
    def recipients(self) -> List[Recipient]:
        return [
            Recipient(
                recipient_box.address,
                recipient_box.amount,
                recipient_box.label if recipient_box.label else None,
                checked_max_amount=recipient_box.recipient_widget.send_max_button.isChecked(),
            )
            for recipient_box in self.get_recipient_group_boxes()
        ]

    @recipients.setter
    def recipients(self, recipient_list: List[Recipient]) -> None:
        # remove all old ones
        for recipient_box in self.get_recipient_group_boxes():
            self.remove_recipient_widget(recipient_box)

        for recipient in recipient_list:
            self.add_recipient(recipient)

    def get_recipient_group_boxes(self) -> List[RecipientTabWidget]:
        return self.recipient_list.findChildren(RecipientTabWidget)
