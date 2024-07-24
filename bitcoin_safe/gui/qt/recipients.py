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

from bitcoin_safe.gui.qt.address_edit import AddressEdit

from ...pythonbdk_types import Recipient
from .invisible_scroll_area import InvisibleScrollArea

logger = logging.getLogger(__name__)

from typing import List

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QTabWidget,
    QWidget,
)

from ...signals import Signals, UpdateFilter
from ...util import unit_str
from .spinbox import BTCSpinBox


class CloseButton(QPushButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(16, 16))  # Adjust the size as needed

    def paintEvent(self, event) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        option.initFrom(self)
        option.features = QStyleOptionButton.ButtonFeature.None_
        option.icon = self.style().standardIcon(QStyle.StandardPixmap.SP_TabCloseButton)
        option.iconSize = QSize(14, 14)  # Adjust icon size as needed
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class LabelLineEdit(QLineEdit):
    signal_enterPressed = pyqtSignal()  # Signal for Enter key
    signal_textEditedAndFocusLost = pyqtSignal()  # Signal for text edited and focus lost

    def __init__(self, parent=None):
        super().__init__(parent)
        self.originalText = ""
        self.textChangedSinceFocus = False
        self.installEventFilter(self)  # Install an event filter
        self.textChanged.connect(self.onTextChanged)  # Connect the textChanged signal

    def onTextChanged(self):
        self.textChangedSinceFocus = True  # Set flag when text changes

    def eventFilter(self, obj, event):
        if obj == self:
            if event.type() == QKeyEvent.Type.FocusIn:
                self.originalText = self.text()  # Store text when focused
                self.textChangedSinceFocus = False  # Reset change flag
            elif event.type() == QKeyEvent.Type.FocusOut:
                if self.textChangedSinceFocus:
                    self.signal_textEditedAndFocusLost.emit()  # Emit signal if text was edited
                self.textChangedSinceFocus = False  # Reset change flag
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.signal_enterPressed.emit()  # Emit Enter pressed signal
        elif event.key() == Qt.Key.Key_Escape:
            self.setText(self.originalText)  # Reset text on ESC
        else:
            super().keyPressEvent(event)


class RecipientWidget(QWidget):
    def __init__(
        self,
        signals: Signals,
        network: bdk.Network,
        allow_edit=True,
        allow_label_edit=True,
        parent=None,
        dismiss_label_on_focus_loss=True,
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
        # ensure that the address_edit is the minimum vertical size
        self.address_edit.button_container.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.label_line_edit = LabelLineEdit()

        self.amount_layout = QHBoxLayout()
        self.amount_spin_box = BTCSpinBox(self.signals.get_network())
        self.label_unit = QLabel(unit_str(self.signals.get_network()))
        self.send_max_button = QPushButton()
        self.send_max_button.setCheckable(True)
        self.send_max_button.setMaximumWidth(80)
        self.send_max_button.clicked.connect(self.on_send_max_button_click)
        self.amount_layout.addWidget(self.amount_spin_box)
        self.amount_layout.addWidget(self.label_unit)
        if allow_edit:
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

        self.address_edit.setReadOnly(not allow_edit)
        self.amount_spin_box.setReadOnly(not allow_edit)
        self.label_line_edit.setReadOnly(not allow_label_edit)

        self.updateUi()

        # signals
        self.signals.language_switch.connect(self.updateUi)
        self.address_edit.signal_text_change.connect(self.autofill_label)
        self.address_edit.signal_bip21_input.connect(self.on_handle_input)
        self.label_line_edit.signal_enterPressed.connect(self.on_label_edited)
        if dismiss_label_on_focus_loss:
            self.label_line_edit.signal_textEditedAndFocusLost.connect(
                lambda: self.label_line_edit.setText(self.label_line_edit.originalText)
            )

    def on_label_edited(self) -> None:
        wallet = self.address_edit.get_wallet_of_address()
        if not wallet:
            return
        address = self.address_edit.address
        wallet.labels.set_addr_label(address, self.label_line_edit.text().strip(), timestamp="now")
        self.signals.labels_updated.emit(
            UpdateFilter(
                addresses=[address],
                txids=wallet.get_involved_txids(address),
            )
        )

    def on_handle_input(self, data: Data, parent: QWidget) -> None:
        if data.data_type == DataType.Bip21:
            if data.data.get("address"):
                self.address_edit.address = data.data.get("address")
            if data.data.get("amount"):
                self.amount_spin_box.setValue(data.data.get("amount"))
            if data.data.get("label"):
                self.label_line_edit.setText(data.data.get("label"))

    def updateUi(self) -> None:

        self.address_label.setText(self.tr("Address"))
        self.label_txlabel.setText(self.tr("Label"))
        self.amount_label.setText(self.tr("Amount"))

        self.label_line_edit.setPlaceholderText(self.tr("Enter label here"))
        self.send_max_button.setText(self.tr("Send max"))

        self.address_edit.updateUi()
        self.autofill_label()

    def showEvent(self, event) -> None:
        # this is necessary, otherwise the background color of the
        # address_line_edit.input_field is not updated properly when setting the adddress
        self.updateUi()

    def on_send_max_button_click(self) -> None:
        # self.amount_spin_box.setValue(0)
        # self.amount_spin_box.setEnabled(not self.send_max_button.isChecked())
        self.amount_spin_box.set_max(self.send_max_button.isChecked())

    @property
    def address(self) -> str:
        return self.address_edit.address

    @address.setter
    def address(self, value: str) -> None:
        self.address_edit.address = value

    @property
    def label(self) -> str:
        return self.label_line_edit.text().strip()

    @label.setter
    def label(self, value: str) -> None:
        self.label_line_edit.setText(value)

    @property
    def amount(self) -> int:
        return self.amount_spin_box.value()

    @amount.setter
    def amount(self, value: int) -> None:
        self.amount_spin_box.setValue(value)

    @property
    def enabled(self) -> bool:
        return not self.address_edit.isReadOnly()

    @enabled.setter
    def enabled(self, state: bool) -> None:
        self.address_edit.setReadOnly(not state)
        self.label_line_edit.setReadOnly(not state)
        self.amount_spin_box.setReadOnly(not state)
        self.send_max_button.setEnabled(state)

    def autofill_label(self, *args):
        wallet = self.address_edit.get_wallet_of_address()
        if wallet:
            label = wallet.get_label_for_address(self.address_edit.address)
            self.label_line_edit.setPlaceholderText(label)
            if not self.allow_edit:
                self.label_line_edit.setText(label)

        else:
            self.label_line_edit.setPlaceholderText(self.tr("Enter label for recipient address"))


class RecipientTabWidget(QTabWidget):
    signal_close = pyqtSignal(QTabWidget)

    def __init__(
        self,
        signals: Signals,
        network: bdk.Network,
        allow_edit=True,
        title="",
        parent=None,
        tab_string=None,
        dismiss_label_on_focus_loss=True,
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
            dismiss_label_on_focus_loss=dismiss_label_on_focus_loss,
        )
        self.addTab(self.recipient_widget, title)

        self.tabCloseRequested.connect(lambda: self.signal_close.emit(self))

        self.recipient_widget.address_edit.signal_text_change.connect(self.autofill_tab_text)

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
        wallet = self.recipient_widget.address_edit.get_wallet_of_address()
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


class Recipients(QtWidgets.QWidget):
    signal_added_recipient = pyqtSignal(RecipientTabWidget)
    signal_removed_recipient = pyqtSignal(RecipientTabWidget)
    signal_clicked_send_max_button = pyqtSignal(RecipientTabWidget)
    signal_amount_changed = pyqtSignal(RecipientTabWidget)

    def __init__(
        self, signals: Signals, network: bdk.Network, allow_edit=True, dismiss_label_on_focus_loss=False
    ) -> None:
        super().__init__()
        self.signals = signals
        self.allow_edit = allow_edit
        self.network = network
        self.dismiss_label_on_focus_loss = dismiss_label_on_focus_loss

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.recipient_list = InvisibleScrollArea()
        self.recipient_list.setWidgetResizable(True)
        self.recipient_list.content_widget.setLayout(QtWidgets.QVBoxLayout())

        self.recipient_list.content_widget.layout().setContentsMargins(0, 0, 0, 0)  # Set all margins to zero
        self.recipient_list.content_widget.layout().setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.main_layout.addWidget(self.recipient_list)

        self.add_recipient_button = QtWidgets.QPushButton("")
        self.add_recipient_button.setMaximumWidth(150)
        # self.add_recipient_button.setStyleSheet("background-color: green")
        self.add_recipient_button.clicked.connect(lambda: self.add_recipient())
        if allow_edit:
            self.recipient_list.content_widget.layout().addWidget(self.add_recipient_button)
            # self.main_layout.addWidget(self.add_recipient_button)
        self.updateUi()
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        self.recipient_list.setToolTip(self.tr("Recipients"))
        self.add_recipient_button.setText(self.tr("+ Add Recipient"))

    def add_recipient(self, recipient: Recipient = None) -> RecipientTabWidget:
        if recipient is None:
            recipient = Recipient("", 0)
        recipient_box = RecipientTabWidget(
            self.signals,
            network=self.network,
            allow_edit=self.allow_edit,
            title="Recipient" if self.allow_edit else "",
            dismiss_label_on_focus_loss=self.dismiss_label_on_focus_loss,
        )
        recipient_box.address = recipient.address
        recipient_box.amount = recipient.amount
        if recipient.checked_max_amount:
            recipient_box.recipient_widget.send_max_button.click()
        if recipient.label:
            recipient_box.label = recipient.label
        recipient_box.signal_close.connect(self.remove_recipient_widget)
        recipient_box.recipient_widget.amount_spin_box.valueChanged.connect(
            lambda *args: self.signal_amount_changed.emit(recipient_box)
        )

        # insert before the button position
        def insert_before_button(new_widget: QWidget) -> None:
            index = self.recipient_list.content_widget.layout().indexOf(self.add_recipient_button)
            if index >= 0:
                self.recipient_list.content_widget.layout().insertWidget(index, new_widget)
            else:
                self.recipient_list.content_widget.layout().addWidget(new_widget)

        insert_before_button(recipient_box)

        recipient_box.recipient_widget.send_max_button.clicked.connect(
            lambda: self.signal_clicked_send_max_button.emit(recipient_box)
        )
        self.signal_added_recipient.emit(recipient_box)
        return recipient_box

    def remove_recipient_widget(self, recipient_box: RecipientTabWidget) -> None:
        recipient_box.close()
        recipient_box.setParent(None)
        self.recipient_list.content_widget.layout().removeWidget(recipient_box)
        self.signal_removed_recipient.emit(recipient_box)
        recipient_box.deleteLater()

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
