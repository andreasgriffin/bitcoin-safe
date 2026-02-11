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
from functools import partial
from time import time
from typing import Any, cast

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools
from bitcoin_safe_lib.tx_util import serialized_to_hex
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QShowEvent
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.address_comparer import AddressComparer, FuzzyMatch
from bitcoin_safe.client import Client
from bitcoin_safe.execute_config import DEMO_MODE, IS_PRODUCTION
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.hist_list import ButtonInfoType, button_info
from bitcoin_safe.gui.qt.labeledit import WalletLabelAndCategoryEdit
from bitcoin_safe.gui.qt.my_treeview import needs_frequent_flag
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.packaged_tx_like import UiElements
from bitcoin_safe.gui.qt.qt_wallet import get_syncclients
from bitcoin_safe.gui.qt.tx_export import TxExport
from bitcoin_safe.gui.qt.tx_signing_steps import TxSigningSteps
from bitcoin_safe.gui.qt.tx_tools import TxTools
from bitcoin_safe.gui.qt.tx_util import advance_tip_for_addresses
from bitcoin_safe.gui.qt.ui_tx.toggle_button_group import ToggleButtonGroup
from bitcoin_safe.gui.qt.ui_tx.ui_tx_base import UITx_Base
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.warning_bars import PoisoningWarningBar
from bitcoin_safe.html_utils import html_f
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.labels import LabelType
from bitcoin_safe.tx import short_tx_id

from ....config import UserConfig
from ....mempool_manager import MempoolManager
from ....psbt_util import FeeInfo, PubKeyInfo, SimpleInput, SimplePSBT
from ....pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    Recipient,
    TransactionDetails,
    TxOut,
    get_prev_outpoints,
    robust_address_str_from_txout,
)
from ....signals import (
    UpdateFilter,
    UpdateFilterReason,
    WalletFunctions,
)
from ....signer import (
    AbstractSignatureImporter,
    SignatureImporterClipboard,
    SignatureImporterFile,
    SignatureImporterQR,
    SignatureImporterUSB,
    SignatureImporterWallet,
)
from ....wallet import (
    LOCAL_TX_LAST_SEEN,
    ToolsTxUiInfo,
    TxConfirmationStatus,
    TxStatus,
    Wallet,
    get_tx_details,
    get_wallets,
)
from ..util import (
    HLine,
    Message,
    MessageType,
    add_to_buttonbox,
    adjust_bg_color_for_darkmode,
    caught_exception_message,
    clear_layout,
    set_margins,
    set_no_margins,
    sort_id_to_icon,
)
from ..utxo_list import UtxoListWithToolbar
from .columns import BaseColumn, ColumnFee, ColumnInputs, ColumnRecipients, ColumnSankey

logger = logging.getLogger(__name__)


class PSBTAlreadyBroadcastedBar(NotificationBar):
    def __init__(self) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=True,
        )
        color = adjust_bg_color_for_darkmode(QColor("lightblue"))
        self.set_background_color(color)

        self.optionalButton.setVisible(False)

        self.setVisible(False)

    def set(self, wallet_tx_details: TransactionDetails | None, wallet: Wallet | None, data: Data):
        """Set."""
        if isinstance(data.data, bdk.Psbt) and wallet_tx_details and wallet:
            self.setHidden(False)
            self.icon_label.setText(
                self.tr("This transaction {txid} was already signed and is in wallet {wallet}").format(
                    txid=short_tx_id(wallet_tx_details.txid), wallet=html_f(wallet.id, bf=True)
                )
            )
            return
        if isinstance(data.data, bdk.Transaction) and wallet_tx_details and wallet:
            if serialized_to_hex(wallet_tx_details.transaction.serialize()) != serialized_to_hex(
                data.data.serialize()
            ):
                self.setHidden(False)
                self.icon_label.setText(
                    self.tr(
                        "This transaction {txid} exists is in wallet {wallet} and the serializations of both differ."
                    ).format(txid=short_tx_id(wallet_tx_details.txid), wallet=html_f(wallet.id, bf=True))
                )
                return

        self.setHidden(True)
        self.icon_label.setText("")


class UITx_Viewer(UITx_Base):
    signal_updated_content: SignalProtocol[Data] = cast(Any, pyqtSignal(Data))
    signal_edit_tx = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        fx: FX,
        widget_utxo_with_toolbar: UtxoListWithToolbar,
        network: bdk.Network,
        mempool_manager: MempoolManager,
        data: Data,
        client: Client | None = None,
        fee_info: FeeInfo | None = None,
        chain_position: bdk.ChainPosition | None = None,
        parent=None,
        focus_ui_element: UiElements = UiElements.none,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            fx=fx,
            parent=parent,
            config=config,
            wallet_functions=wallet_functions,
            mempool_manager=mempool_manager,
        )
        self.focus_ui_element = focus_ui_element
        self.data = data
        self.network = network
        self.fee_info = fee_info
        self.client = client
        self.utxo_list = widget_utxo_with_toolbar.utxo_list
        self.chain_position = chain_position
        self._forced_update = False
        self._pending_update = True

        ##################
        self.searchable_list = widget_utxo_with_toolbar.utxo_list

        # address_poisoning
        self.address_poisoning_warning_bar = PoisoningWarningBar(signals_min=self.signals)
        self._layout.addWidget(self.address_poisoning_warning_bar)

        # PSBTAlreadyBroadcastedBar
        self.psbt_already_broadcasted_bar = PSBTAlreadyBroadcastedBar()
        self._layout.addWidget(self.psbt_already_broadcasted_bar)

        # tx label
        self.container_label = QWidget(self)
        container_label_layout = QHBoxLayout(self.container_label)
        container_label_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.label_label = QLabel("")
        self.label_line_edit = WalletLabelAndCategoryEdit(
            wallet_functions=self.wallet_functions,
            get_label_ref=self.txid,
            label_type=LabelType.tx,
            parent=self,
            dismiss_label_on_focus_loss=False,
        )
        container_label_layout.addWidget(self.label_label)
        container_label_layout.addWidget(self.label_line_edit)
        self._layout.addWidget(self.container_label)

        # upper widget
        self.upper_widget = QWidget(self)
        self.upper_widget_layout = QHBoxLayout(self.upper_widget)
        set_no_margins(self.upper_widget_layout)
        self._layout.addWidget(self.upper_widget)
        self._layout.addWidget(HLine())

        # in out
        self.splitter = QSplitter()
        self.splitter.setObjectName(f"member of {self.__class__.__name__}")
        # button = QPushButton("Edit")
        # button.setFixedHeight(button.sizeHint().height())
        # button.setIcon(QIcon(icon_path("pen.svg")))
        # button.setIconSize(QSize(16, 16))  # 24x24 pixels
        # button.clicked.connect(lambda: self.edit())
        # self.tabs_inputs_outputs.set_top_right_widget(button)
        self.upper_widget_layout.addWidget(self.splitter)

        # inputs
        self.column_inputs = ColumnInputs(
            category_list=None,
            widget_utxo_with_toolbar=widget_utxo_with_toolbar,
            fx=self.fx,
        )
        set_margins(
            self.column_inputs._layout,
            {
                Qt.Edge.LeftEdge: 0,
            },
        )
        self.splitter.addWidget(self.column_inputs)

        # outputs
        self.column_recipients = ColumnRecipients(
            fx=fx, wallet_functions=self.wallet_functions, allow_edit=False
        )
        set_margins(
            self.column_recipients._layout,
            {
                Qt.Edge.LeftEdge: 0,
            },
        )
        self.recipients = self.column_recipients.recipients
        self.splitter.addWidget(self.column_recipients)

        self.header_button_group = ToggleButtonGroup(self)

        # sankey
        self.column_sankey = ColumnSankey(wallet_functions=self.wallet_functions, fx=self.fx, parent=self)
        set_margins(
            self.column_sankey._layout,
            {
                Qt.Edge.LeftEdge: 0,
            },
        )
        self.splitter.addWidget(self.column_sankey)

        # fee_rate
        self.column_fee = ColumnFee(
            wallet_functions=self.wallet_functions,
            mempool_manager=self.mempool_manager,
            fx=fx,
            fee_info=fee_info,
            allow_edit=False,
            is_viewer=True,
            tx_status=self.get_tx_status(chain_position=chain_position),
        )
        self.column_fee.header_widget.h_laylout.insertWidget(0, self.header_button_group)
        self.splitter.addWidget(self.column_fee)

        self.splitter.setSizes([1, 10, 1, 1])
        self.splitter.setCollapsible(self.splitter.indexOf(self.column_inputs), True)
        self.splitter.setCollapsible(self.splitter.indexOf(self.column_recipients), False)
        self.splitter.setCollapsible(self.splitter.indexOf(self.column_sankey), True)
        self.splitter.setCollapsible(self.splitter.indexOf(self.column_fee), False)
        # # No stretch: this pane won't grow or shrink
        self.splitter.setStretchFactor(self.splitter.indexOf(self.column_inputs), 2)
        self.splitter.setStretchFactor(self.splitter.indexOf(self.column_recipients), 1)
        self.splitter.setStretchFactor(self.splitter.indexOf(self.column_sankey), 1)
        self.splitter.setStretchFactor(self.splitter.indexOf(self.column_fee), 0)

        self.set_tab_focus(UiElements.default if focus_ui_element == UiElements.none else focus_ui_element)

        # progress bar  import export  flow container
        self.tx_singning_steps_container = QWidget(self)
        self.tx_singning_steps_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tx_singning_steps_container_layout = QVBoxLayout(self.tx_singning_steps_container)
        set_no_margins(self.tx_singning_steps_container_layout)
        self._layout.addWidget(self.tx_singning_steps_container)
        self.tx_singning_steps: TxSigningSteps | None = None

        # # txid and block explorers
        # self.blockexplorer_group = BlockExplorerGroup(tx.txid(), layout=self.right_sidebar_layout)
        self.export_data_simple = TxExport(
            data=self.data,
            network=self.network,
            signals_min=self.signals,
            loop_in_thread=self.loop_in_thread,
            parent=self,
            sync_client=get_syncclients(wallet_functions=self.wallet_functions),
        )
        self._layout.addWidget(self.export_data_simple)

        # buttons

        # Create the QDialogButtonBox
        self.buttonBox = QDialogButtonBox()

        # Create custom buttons
        self.button_edit_tx = add_to_buttonbox(
            self.buttonBox,
            "",
            button_info(ButtonInfoType.edit).icon,
            on_clicked=partial(self.edit, None),
            role=QDialogButtonBox.ButtonRole.ResetRole,
        )
        self.button_rbf = add_to_buttonbox(
            self.buttonBox,
            "",
            button_info(ButtonInfoType.rbf).icon,
            on_clicked=self.rbf,
            role=QDialogButtonBox.ButtonRole.ResetRole,
        )
        self.button_cpfp_tx = add_to_buttonbox(
            self.buttonBox,
            "",
            button_info(ButtonInfoType.cpfp).icon,
            on_clicked=self.cpfp,
            role=QDialogButtonBox.ButtonRole.ResetRole,
        )
        self.button_back = add_to_buttonbox(
            self.buttonBox,
            "",
            icon_name=svg_tools.get_QIcon("bi--arrow-left-short.svg"),
            on_clicked=self.navigate_tab_history_backward,
            role=QDialogButtonBox.ButtonRole.ResetRole,
        )
        self.button_previous = add_to_buttonbox(
            self.buttonBox,
            "",
            None,
            on_clicked=self.go_to_previous_index,
            role=QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.button_next = add_to_buttonbox(
            self.buttonBox,
            "",
            None,
            on_clicked=self.go_to_next_index,
            role=QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.button_save_local_tx = add_to_buttonbox(
            self.buttonBox,
            "",
            "offline_tx.svg",
            on_clicked=self.save_local_tx,
            role=QDialogButtonBox.ButtonRole.NoRole,
        )
        self.button_send = add_to_buttonbox(
            self.buttonBox,
            "",
            "bi--send.svg",
            on_clicked=self.broadcast,
            role=QDialogButtonBox.ButtonRole.AcceptRole,
        )

        self._layout.addWidget(self.buttonBox)
        ##################

        self.button_send.setEnabled(self.data.data_type == DataType.Tx)

        self.updateUi()
        self.reload(UpdateFilter(refresh_all=True))
        self.fill_button_group()
        self.utxo_list.update_content()

        # signals
        self.signal_tracker.connect(self.signals.language_switch, self._on_lang_switch)
        # after the wallet loads the transactions, then i have to reload again to
        # ensure that the linking warning bar appears (needs all tx loaded)
        self.signal_tracker.connect(self.signals.any_wallet_updated, self.reload)
        self.signals.currency_switch.connect(self.update_all_totals)
        self.utxo_list.signal_finished_update.connect(self.update_all_totals)
        self.column_fee.fee_group.mempool_buttons.signal_rbf_icon.connect(self._on_rbf_icon)
        self.column_fee.fee_group.mempool_buttons.signal_cpfp_icon.connect(self._on_cpfp_icon)
        self.column_fee.fee_group.mempool_buttons.signal_edit_with_fee_icon.connect(
            self._on_edit_with_fee_icon
        )

    def _on_lang_switch(self):
        """On lang switch."""
        self.updateUi()
        # this must be after  updateUi because it takes the button text from other elements
        self.fill_button_group()

    def _on_edit_with_fee_icon(self, index: int) -> None:
        """On edit with fee icon."""
        rate = self.mempool_manager.median_block_fee_rate(
            index, decimal_precision=self.column_fee.fee_group.mempool_buttons.decimal_precision
        )
        self.edit(new_fee_rate=rate)

    def _on_rbf_icon(self, index: int) -> None:
        """On rbf icon."""
        rate = self.mempool_manager.median_block_fee_rate(
            index, decimal_precision=self.column_fee.fee_group.mempool_buttons.decimal_precision
        )
        self.rbf(new_fee_rate=rate)

    def _on_cpfp_icon(self, index: int) -> None:
        """On cpfp icon."""
        rate = self.mempool_manager.median_block_fee_rate(
            index, decimal_precision=self.column_fee.fee_group.mempool_buttons.decimal_precision
        )
        self.cpfp(fee_rate=rate)

    def update_recipients_totals(self):
        """Update recipients totals."""
        amount = self._get_total_non_change_output_amount(
            self.recipients.recipients,
        )
        self.column_recipients.totals.set_amount(amount)
        self.column_sankey.totals.set_amount(amount)

    def get_total(self) -> int | None:
        """Get total."""
        fee_info = self.fee_info if self.fee_info else self._fetch_cached_feeinfo(self.txid())
        fee_amount = None

        if fee_info and not fee_info.fee_amount_is_estimated:
            fee_amount = fee_info.fee_amount

        if isinstance(self.data.data, bdk.Psbt):
            fee_amount = self.data.data.fee()

        if fee_amount is not None:
            outputs = sum(txout.value.to_sat() for txout in self.extract_tx().output())
            return outputs + fee_amount

        return None

    def update_sending_source_totals(self):
        """Update sending source totals."""
        total = self.get_total()
        self.column_inputs.totals.set_amount(total)
        self.column_sankey.totals.set_amount(total, alignment=Qt.Edge.LeftEdge)

    def update_all_totals(self):
        """Update all totals."""
        self.update_sending_source_totals()
        self.update_recipients_totals()
        self.column_fee.updateUi()

    def fill_button_group(self):
        """Fill button group."""
        self.header_button_group.clear()
        if not IS_PRODUCTION and not DEMO_MODE:
            button = QPushButton()
            button.setText("refresh")
            button.clicked.connect(partial(self.reload, UpdateFilter(refresh_all=True)))
            self.header_button_group.addButton(button)

        for i in range(self.splitter.count()):
            widget = self.splitter.widget(i)
            if not isinstance(widget, BaseColumn) or not widget.is_available():
                continue
            if isinstance(widget, ColumnFee):
                continue
            button = QPushButton()
            button.setText(widget.header_widget.label_title.text())
            button.setIcon(svg_tools.get_QIcon(widget.header_widget.icon_name))
            self.header_button_group.addButton(button)
            if not widget.isHidden():
                self.header_button_group.setCurrentButton(button)
            button.clicked.connect(partial(self.focus_tab, widget))

    def focus_tab(self, focus_widget: BaseColumn):
        """Focus tab."""
        for i in range(self.splitter.count()):
            widget = self.splitter.widget(i)
            if not isinstance(widget, BaseColumn):
                continue
            if isinstance(widget, ColumnFee):
                continue
            widget.setHidden(focus_widget != widget)
            if focus_widget == widget:
                self.header_button_group.setCurrentIndex(i)

        focus_widget.header_widget.h_laylout.insertWidget(0, self.header_button_group)
        focus_widget.header_widget.label_title.setVisible(False)
        focus_widget.header_widget.icon.setVisible(False)

        if focus_widget == self.column_sankey:
            self.update_all_totals()

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        edits: list[tuple[ButtonInfoType, QPushButton]] = [
            (ButtonInfoType.edit, self.button_edit_tx),
            (ButtonInfoType.cpfp, self.button_cpfp_tx),
            (ButtonInfoType.rbf, self.button_rbf),
        ]
        for info_type, edit in edits:
            edit.setText(button_info(info_type).text)
            edit.setToolTip(button_info(info_type).tooltip)

        self.button_back.setText(self.tr("Back"))
        self.button_previous.setText(self.tr("Previous step"))
        self.button_next.setText(self.tr("Next step"))
        self.button_send.setText(self.tr("Send"))
        self.button_send.setToolTip("Broadcasts the transaction to the bitcoin network.")
        self.label_label.setText(self.tr("Label: "))
        self.button_save_local_tx.setText(self.tr("Save in wallet"))
        self.address_poisoning_warning_bar.updateUi()
        self.column_inputs.updateUi()
        self.column_recipients.updateUi()
        self.column_fee.updateUi()
        self.column_sankey.updateUi()
        self.column_fee.header_widget.syncWith(
            self.column_inputs.header_widget,
            self.column_recipients.header_widget,
            self.column_sankey.header_widget,
        )
        self.export_data_simple.updateUi()
        self.update_all_totals()

    def save_local_tx(self):
        """Save local tx."""
        self.signals.apply_txs_to_wallets.emit([self.extract_tx()], LOCAL_TX_LAST_SEEN)

    def extract_tx(self) -> bdk.Transaction:
        """Extract tx."""
        if self.data.data_type == DataType.Tx:
            if not isinstance(self.data.data, bdk.Transaction):
                raise Exception(f"{self.data.data} is not of type bdk.Transaction")
            return self.data.data
        if self.data.data_type == DataType.PSBT:
            if not isinstance(self.data.data, bdk.Psbt):
                raise Exception(f"{self.data.data} is not of type bdk.Psbt")
            return self.data.data.extract_tx()
        raise Exception(f"invalid data type {self.data.data}")

    def _step_allows_forward(self, index: int) -> bool:
        """Step allows forward."""
        if not self.tx_singning_steps:
            return False
        if index == self.tx_singning_steps.count() - 1:
            return False
        return index in self.tx_singning_steps.sub_indices

    def _step_allows_backward(self, index: int) -> bool:
        """Step allows backward."""
        if not self.tx_singning_steps:
            return False
        if index == 0:
            return False
        return index - 1 in self.tx_singning_steps.sub_indices

    def set_next_prev_button_enabledness(self):
        """Set next prev button enabledness."""
        if not self.tx_singning_steps:
            return
        next_enabled = self._step_allows_forward(self.tx_singning_steps.current_index())
        prev_enabled = self._step_allows_backward(self.tx_singning_steps.current_index())
        self.button_next.setEnabled(next_enabled)
        self.button_previous.setEnabled(prev_enabled)
        self.button_next.setHidden(not next_enabled and not prev_enabled)
        self.button_previous.setHidden(not next_enabled and not prev_enabled)

    def navigate_tab_history_backward(self) -> None:
        """Return to the previously active tab."""

        self.signals.tab_history_backward.emit()

    def go_to_next_index(self) -> None:
        """Go to next index."""
        if not self.tx_singning_steps:
            return
        self.tx_singning_steps.go_to_next_index()

        self.set_next_prev_button_enabledness()

    def go_to_previous_index(self) -> None:
        """Go to previous index."""
        if not self.tx_singning_steps:
            return
        self.tx_singning_steps.go_to_previous_index()

        self.set_next_prev_button_enabledness()

    def cpfp(
        self, fee_rate: float | None = None, target_total_unconfirmed_fee_rate: float | None = None
    ) -> None:
        """Cpfp."""
        tx = self.extract_tx()
        tx_details, wallet = get_tx_details(
            txid=str(tx.compute_txid()), wallet_functions=self.wallet_functions
        )
        if not wallet or not tx_details:
            return
        TxTools.cpfp_tx(
            tx_details=tx_details,
            wallet=wallet,
            wallet_functions=self.wallet_functions,
            fee_rate=fee_rate,
            target_total_unconfirmed_fee_rate=target_total_unconfirmed_fee_rate,
            parent=self,
        )

    def _infos_for_edit_or_rbf(self, new_fee_rate: float | None = None):
        """Infos for edit or rbf."""
        tx = self.extract_tx()
        wallets = get_wallets(self.wallet_functions)
        txinfos = ToolsTxUiInfo.from_tx(tx, self.fee_info, self.network, wallets)
        if new_fee_rate is not None:
            txinfos.fee_rate = new_fee_rate

        txid = tx.compute_txid()
        tx_details, wallet = get_tx_details(txid=str(txid), wallet_functions=self.wallet_functions)

        if not wallet and txinfos.main_wallet_id:
            wallet = self.wallet_functions.get_wallets().get(txinfos.main_wallet_id)
        return txid, wallet, tx_details, txinfos

    def edit(self, new_fee_rate: float | None = None) -> None:
        """Edit."""
        txid, wallet, tx_details, txinfos = self._infos_for_edit_or_rbf(new_fee_rate=new_fee_rate)

        if not wallet:
            Message(
                self.tr("Wallet of transaction inputs could not be found"),
                type=MessageType.Error,
                parent=self,
            )
            return

        tx_status = TxStatus.from_wallet(txid=txid, wallet=wallet)
        if tx_details and tx_status.is_local():
            Message(
                self.tr("Please remove the existing local transaction of the wallet first."),
                type=MessageType.Error,
                parent=self,
            )
        else:
            TxTools.edit_tx(
                replace_tx=tx_details,
                txinfos=txinfos,
                tx_status=tx_status,
                wallet_functions=self.wallet_functions,
            )

    def rbf(self, new_fee_rate: float | None = None) -> None:
        """Rbf."""
        txid, wallet, tx_details, txinfos = self._infos_for_edit_or_rbf(new_fee_rate=new_fee_rate)

        if not wallet and txinfos.main_wallet_id:
            wallet = self.wallet_functions.get_wallets().get(txinfos.main_wallet_id)

        if not wallet:
            Message(
                self.tr("Wallet of transaction inputs could not be found"),
                type=MessageType.Error,
                parent=self,
            )
            return

        if not tx_details:
            Message(
                self.tr("Not all necessary transaction details are available for RBF"),
                type=MessageType.Error,
                parent=self,
            )
            return

        tx_status = TxStatus.from_wallet(txid=txid, wallet=wallet)
        TxTools.rbf_tx(
            replace_tx=tx_details.transaction,
            txinfos=txinfos,
            tx_status=tx_status,
            wallet_functions=self.wallet_functions,
        )

    def showEvent(self, a0: QShowEvent | None) -> None:
        """ShowEvent."""
        super().showEvent(a0)
        if a0 and a0.isAccepted() and self._pending_update:
            self._forced_update = True
            self.reload(UpdateFilter(refresh_all=True))
            self._forced_update = False

    def maybe_defer_update(self) -> bool:
        """Returns whether we should defer an update/refresh."""
        defer = (
            not self._forced_update
            and not self.isVisible()
            and not needs_frequent_flag(self.get_tx_status(chain_position=self.chain_position))
        )
        # side-effect: if we decide to defer update, the state will become stale:
        self._pending_update = defer
        if not defer:
            self._forced_update = False
        return defer

    def reload(self, update_filter: UpdateFilter) -> None:
        # update the tab icons no matter what, since the chain_height can advance,
        # needing a change in the icon
        """Reload."""
        self.set_tab_properties(chain_position=self.chain_position)

        if self.maybe_defer_update():
            return

        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.outpoints:
            should_update = True
        if (
            should_update
            or update_filter.reason == UpdateFilterReason.ChainHeightAdvanced
            and self.get_tx_status(chain_position=self.chain_position).do_icon_check_on_chain_height_change()
        ):
            should_update = True
        if (
            should_update
            or update_filter.reason == UpdateFilterReason.TransactionChange
            and self.txid() in update_filter.txids
        ):
            should_update = True

        if not should_update:
            return
        logger.debug(f"{self.__class__.__name__} update_with_filter")

        if self.data.data_type == DataType.PSBT:
            self.set_psbt(self.data.data, fee_info=self.fee_info)
            if isinstance(self.data.data, bdk.Psbt):
                result = self.data.data.finalize()
                finalized_tx = result.psbt.extract_tx() if result.could_finalize else None
                if finalized_tx:
                    assert finalized_tx.compute_txid() == self.data.data.extract_tx().compute_txid(), (
                        "error. The txid should not be changed during finalizing/reloading"
                    )
                    self.set_tx(
                        finalized_tx,
                        fee_info=self.fee_info,
                        chain_position=self.chain_position,
                    )
                    return

        elif self.data.data_type == DataType.Tx:
            self.set_tx(
                self.data.data,
                fee_info=self.fee_info,
                chain_position=self.chain_position,
            )

    def set_tab_properties(self, chain_position: bdk.ChainPosition | None):
        """Set tab properties."""
        title = ""
        icon_text = ""
        txid = self.txid()
        tooltip = ""
        if self.data.data_type == DataType.PSBT and isinstance(self.data.data, bdk.Psbt):
            title = self.tr("PSBT {txid}").format(txid=short_tx_id(txid))
            tooltip = self.tr("PSBT {txid}").format(txid=txid)
            icon_text = "bi--qr-code.svg"
        elif self.data.data_type == DataType.Tx and isinstance(self.data.data, bdk.Transaction):
            title = self.tr("Transaction {txid}").format(txid=short_tx_id(txid))
            tooltip = self.tr("Transaction {txid}").format(txid=txid)
            status = self.get_tx_status(chain_position=chain_position)
            icon_text = sort_id_to_icon(status.sort_id())

        if title or icon_text or tooltip:
            self.signals.signal_set_tab_properties.emit(self, title, icon_text, tooltip)

    def txid(self) -> str:
        """Txid."""
        return str(self.extract_tx().compute_txid())

    def _get_height(self) -> int | None:
        """Get height."""
        for wallet in get_wallets(self.wallet_functions):
            return wallet.get_height()
        return None

    def _broadcast(self, tx: bdk.Transaction) -> bool:
        """Broadcast."""
        if self.client:
            try:
                self.client.broadcast(tx)
                self.signals.signal_broadcast_tx.emit(tx)
                return True
            except Exception as e:
                caught_exception_message(
                    e,
                    title=(
                        self.tr("Invalid Signatures")
                        if "non-mandatory-script-verify-flag" in str(e)
                        else None
                    ),
                    parent=self,
                )
        else:
            Message(
                self.tr(
                    "Please open a wallet first to broadcast the transaction.\nOr you can broadcast via {url}"
                ).format(url="https://blockstream.info/tx/push"),
                type=MessageType.Error,
                parent=self,
            )

        return False

    def _set_blockchain(self):
        """Set blockchain."""
        for wallet in get_wallets(self.wallet_functions):
            if wallet.client:
                self.client = wallet.client
                logger.error(f"Using {self.client} from wallet {wallet.id}")

    def broadcast(self) -> None:
        """Broadcast."""
        if not self.data.data_type == DataType.Tx:
            return
        if not isinstance(self.data.data, bdk.Transaction):
            logger.error("data is not of type bdk.Transaction and cannot be broadcastet")
            return
        tx = self.data.data

        if not self.client:
            self._set_blockchain()

        logger.debug(f"broadcasting tx {str(tx.compute_txid())[:4]=}")
        success = self._broadcast(tx)
        if success:
            logger.info(f"Successfully broadcasted tx {str(tx.compute_txid())[:4]=}")

    def enrich_simple_psbt_with_wallet_data(self, simple_psbt: SimplePSBT) -> SimplePSBT:
        """Enrich simple psbt with wallet data."""

        def get_keystore(fingerprint: str, keystores: list[KeyStore]) -> KeyStore | None:
            """Get keystore."""
            for keystore in keystores:
                if keystore.fingerprint == fingerprint:
                    return keystore
            return None

        # collect all wallets that have input utxos
        inputs: list[bdk.TxIn] = self.extract_tx().input()

        outpoint_dict = {
            outpoint_str: (python_utxo, wallet)
            for wallet in get_wallets(self.wallet_functions)
            for outpoint_str, python_utxo in wallet.get_all_txos_dict().items()
        }

        # fill fingerprints, if not available
        for this_input, simple_input in zip(inputs, simple_psbt.inputs, strict=False):
            outpoint_str = str(this_input.previous_output)
            if outpoint_str not in outpoint_dict:
                continue
            python_utxo, wallet = outpoint_dict[outpoint_str]

            simple_input.wallet_id = wallet.id
            simple_input.m_of_n = wallet.get_mn_tuple()

            if not simple_input.pubkeys:
                # fill with minimal info
                simple_input.pubkeys = [
                    PubKeyInfo(fingerprint=keystore.fingerprint) for keystore in wallet.keystores
                ]

            # fill additional info (label) if available
            for pubkey in simple_input.pubkeys:
                keystore = get_keystore(pubkey.fingerprint, wallet.keystores)
                if not keystore:
                    continue
                pubkey.label = keystore.label

        return simple_psbt

    def get_wallet_inputs(self, simple_psbt: SimplePSBT) -> dict[str, list[SimpleInput]]:
        """structures the inputs into categories, usually wallet_ids,
        such that all the inputs are sure to belong to 1 wallet"""
        wallet_inputs: dict[str, list[SimpleInput]] = {}
        for i, _input in enumerate(simple_psbt.inputs):
            if _input.wallet_id and _input.m_of_n:
                id = _input.wallet_id
            elif _input.pubkeys:
                id = ", ".join(
                    sorted(
                        [(pubkey.fingerprint or pubkey.pubkey or pubkey.label) for pubkey in _input.pubkeys]
                    )
                )
            else:
                id = f"Input {i}"

            inputs = wallet_inputs.setdefault(id, [])
            inputs.append(_input)

        return wallet_inputs

    def get_combined_signature_importers(self, psbt: bdk.Psbt) -> dict[str, list[AbstractSignatureImporter]]:
        """Get combined signature importers."""
        signature_importers: dict[str, list[AbstractSignatureImporter]] = {}

        def get_signing_fingerprints_of_wallet(wallet: Wallet) -> set[str]:
            # check which keys the wallet can sign

            """Get signing fingerprints of wallet."""
            wallet_signing_fingerprints = set(
                [keystore.fingerprint for keystore in wallet.keystores if keystore.mnemonic]
            )
            return wallet_signing_fingerprints

        def get_wallets_with_seed(fingerprints: list[str]) -> list[Wallet]:
            """Get wallets with seed."""
            result = []
            for wallet in wallets:
                signing_fingerprints_of_wallet = get_signing_fingerprints_of_wallet(wallet)
                if set(fingerprints).intersection(signing_fingerprints_of_wallet):
                    if wallet not in result:
                        result.append(wallet)
            return result

        def get_pubkey_dict(pubkeys_of_inp: list[list[PubKeyInfo]]) -> dict[str, PubKeyInfo]:
            """Get pubkey dict."""
            pubkeys = {}
            for _pubkeys in pubkeys_of_inp:
                for _pubkey in _pubkeys:
                    if _pubkey.fingerprint not in pubkeys:
                        pubkeys[_pubkey.fingerprint] = _pubkey
            return pubkeys

        simple_psbt = SimplePSBT.from_psbt(psbt)
        simple_psbt = self.enrich_simple_psbt_with_wallet_data(simple_psbt)

        wallet_inputs = self.get_wallet_inputs(simple_psbt)

        wallets: list[Wallet] = get_wallets(self.wallet_functions)

        for wallet_id, inputs in wallet_inputs.items():
            if not inputs:
                continue
            m, n = inputs[0].get_estimated_m_of_n()

            pubkeys_with_signature = get_pubkey_dict([inp.get_pub_keys_with_signature() for inp in inputs])
            pubkeys_without_signature = get_pubkey_dict(
                [inp.get_pub_keys_without_signature() for inp in inputs]
            )

            # only add a maximum of m *(all_signature_importers) for each wallet
            for i in range(m):
                signer_list = signature_importers.setdefault(f"{wallet_id}.{i}", [])
                if pubkeys_with_signature:
                    fingerprint, pubkey_info = pubkeys_with_signature.popitem()

                    signatures = {}
                    for inp in inputs:
                        if (
                            pubkey_info.pubkey
                            and (sig := inp.partial_sigs.get(pubkey_info.pubkey))
                            and inp in simple_psbt.inputs
                        ):
                            signatures[simple_psbt.inputs.index(inp)] = sig

                    signer_list.append(
                        SignatureImporterFile(
                            self.network,
                            signature_available=True,
                            signatures=signatures,
                            key_label=fingerprint,
                            label=self.tr("Import file"),
                            close_all_video_widgets=self.signals.close_all_video_widgets,
                            loop_in_thread=self.loop_in_thread,
                        )
                    )
                    continue

                # check if any wallet has keys for this fingerprint
                for wallet_with_seed in get_wallets_with_seed(
                    [fingerprint for fingerprint in pubkeys_without_signature.keys()]
                ):
                    if DEMO_MODE:
                        break
                    signer_list.append(
                        SignatureImporterWallet(
                            wallet_with_seed,
                            self.network,
                            signature_available=False,
                            key_label=wallet_id,
                            loop_in_thread=self.loop_in_thread,
                            close_all_video_widgets=self.signals.close_all_video_widgets,
                        )
                    )
                    # 1 seed signer is enough
                    break

                classes: list[type[AbstractSignatureImporter]] = [
                    SignatureImporterQR,
                    SignatureImporterFile,
                    SignatureImporterClipboard,
                    SignatureImporterUSB,
                ]
                for cls in classes:
                    signer_list.append(
                        cls(
                            self.network,
                            signature_available=False,
                            key_label=wallet_id,
                            loop_in_thread=self.loop_in_thread,
                            close_all_video_widgets=self.signals.close_all_video_widgets,
                        )
                    )
        # connect signals
        for importers in signature_importers.values():
            for importer in importers:
                importer.signal_signature_added.connect(self.import_trusted_psbt)
                importer.signal_final_tx_received.connect(self.tx_received)
        return signature_importers

    def update_tx_progress(self) -> TxSigningSteps | None:
        """Update tx progress."""
        if self.data.data_type != DataType.PSBT:
            return None
        if not isinstance(self.data.data, bdk.Psbt):
            logger.error("data is not of type bdk.Psbt")
            return None

        # this approach to clearning the layout
        # and then recreating the ui object is prone
        # to problems with multithreading.
        clear_layout(self.tx_singning_steps_container_layout)

        signature_importers = self.get_combined_signature_importers(self.data.data)

        tx_singning_steps = TxSigningSteps(
            signature_importer_dict=signature_importers,
            psbt=self.data.data,
            network=self.network,
            wallet_functions=self.wallet_functions,
            loop_in_thread=self.loop_in_thread,
        )

        self.tx_singning_steps_container_layout.addWidget(tx_singning_steps)
        return tx_singning_steps

    def tx_received(self, tx: bdk.Transaction) -> None:
        """Tx received."""
        if self.data.data_type != DataType.PSBT:
            return
        if not isinstance(self.data.data, bdk.Psbt):
            logger.error("data is not of type bdk.Psbt")
            return

        if self.data.data and tx.compute_txid() != self.data.data.extract_tx().compute_txid():
            Message(
                self.tr("The txid of the signed psbt doesnt match the original txid"),
                type=MessageType.Error,
                parent=self,
            )
            return

        self.set_tx(
            tx,
        )

    def _get_any_signature_importer(self) -> AbstractSignatureImporter | None:
        """Get any signature importer."""
        if not self.tx_singning_steps:
            return None
        for signature_importers in self.tx_singning_steps.signature_importer_dict.values():
            for signature_importer in signature_importers:
                return signature_importer
        return None

    def import_untrusted_psbt(self, import_psbt: bdk.Psbt) -> None:
        """Import untrusted psbt."""
        if isinstance(self.data.data, bdk.Psbt) and (
            signature_importer := self._get_any_signature_importer()
        ):
            signature_importer.handle_data_input(
                original_psbt=self.data.data, data=Data.from_psbt(psbt=import_psbt, network=self.network)
            )
        elif isinstance(self.data.data, bdk.Transaction):
            logger.info(
                "Will not open the tx if the transaction, "
                "since we cannot verify if all signatures are present"
            )
        else:
            logger.warning("Cannot update the psbt. Unclear if more signatures were added")

    def import_trusted_psbt(self, import_psbt: bdk.Psbt) -> None:
        """Import trusted psbt."""
        simple_psbt = SimplePSBT.from_psbt(import_psbt)

        tx = import_psbt.extract_tx()

        if all([inp.is_fully_signed() for inp in simple_psbt.inputs]):
            self.set_tx(
                tx,
            )
        else:
            self.set_psbt(import_psbt)

    def is_in_mempool(self, txid: str) -> bool:
        """Is in mempool."""
        wallets = get_wallets(self.wallet_functions)
        for wallet in wallets:
            if wallet.is_in_mempool(txid):
                return True
        return False

    def _set_warning_bars(
        self,
        outpoints: list[OutPoint],
        recipient_addresses: list[str],
        tx_status: TxStatus,
    ):
        """Set warning bars."""
        super()._set_warning_bars(
            outpoints=outpoints, recipient_addresses=recipient_addresses, tx_status=tx_status
        )
        self.set_poisoning_warning_bar(outpoints=outpoints, recipient_addresses=recipient_addresses)
        self.update_high_fee_warning_label(confirmation_status=tx_status.confirmation_status)
        self.high_fee_rate_warning_label.update_fee_rate_warning(
            confirmation_status=tx_status.confirmation_status,
            fee_rate=self.fee_info.fee_rate() if self.fee_info else None,
            max_reasonable_fee_rate=self.mempool_manager.max_reasonable_fee_rate(),
        )

    def update_high_fee_warning_label(self, confirmation_status: TxConfirmationStatus):
        """Update high fee warning label."""
        if confirmation_status != TxConfirmationStatus.LOCAL:
            self.high_fee_warning_label.setVisible(False)
            return

        self._update_high_fee_warning_label(
            recipients=self.recipients,
            fee_info=self.fee_info,
            tx_status=self.column_fee.fee_group.mempool_buttons.tx_status,
        )

    def set_poisoning_warning_bar(self, outpoints: list[OutPoint], recipient_addresses: list[str]):
        # warn if multiple categories are combined
        """Set poisoning warning bar."""
        wallets: list[Wallet] = list(self.wallet_functions.get_wallets.emit().values())

        all_addresses = set(recipient_addresses)
        for wallet in wallets:
            addresses = [wallet.get_address_of_outpoint(outpoint) for outpoint in outpoints]
            for address in addresses:
                if not address:
                    continue
                all_addresses.add(address)

        async def do() -> list[tuple[str, str, FuzzyMatch]]:
            """Do."""
            start_time = time()
            poisonous_matches = AddressComparer.poisonous(all_addresses)
            logger.debug(
                f"AddressComparer.poisonous {len(poisonous_matches)} results in {time() - start_time}s"
            )
            return poisonous_matches

        def on_done(poisonous_matches: list[tuple[str, str, FuzzyMatch]] | None) -> None:
            """On done."""
            if not poisonous_matches:
                return
            logger.debug(f"finished AddressComparer, found {len(poisonous_matches)=}")

        def on_success(poisonous_matches: list[tuple[str, str, FuzzyMatch]] | None) -> None:
            """On success."""
            if not poisonous_matches:
                return
            self.address_poisoning_warning_bar.set_poisonous_matches(poisonous_matches)

        def on_error(packed_error_info: ExcInfo | None) -> None:
            """On error."""
            logger.error(f"AddressComparer error {packed_error_info}")

        self.loop_in_thread.run_task(
            do(),
            on_done=on_done,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}set_poisoning_warning_bar",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def calc_finalized_tx_fee_info(self, tx: bdk.Transaction, tx_has_final_size: bool) -> FeeInfo | None:
        "This only should be done for tx, not psbt, since the PSBT.extract_tx size is too low"
        wallets = get_wallets(self.wallet_functions)
        # try via tx details
        for wallet_ in wallets:
            txdetails = wallet_.get_tx(str(tx.compute_txid()))
            if txdetails and txdetails.fee:
                return FeeInfo(
                    fee_amount=txdetails.fee,
                    vsize=tx.vsize(),
                    vsize_is_estimated=False,
                    fee_amount_is_estimated=False,
                )

        #  try via utxos
        pythonutxo_dict: dict[str, PythonUtxo] = {}  # outpoint_str:PythonUTXO
        for wallet_ in wallets:
            pythonutxo_dict.update(wallet_.get_all_txos_dict(include_not_mine=True))

        total_input_value = 0
        for outpoint in get_prev_outpoints(tx):
            python_txo = pythonutxo_dict.get(str(outpoint))
            if not python_txo:
                # ALL inputs must be known with value! Otherwise no fee can be calculated
                return None
            if python_txo.txout.value is None:
                return None
            total_input_value += python_txo.value

        total_output_value = sum(txout.value.to_sat() for txout in tx.output())
        fee_amount = total_input_value - total_output_value
        return FeeInfo(
            fee_amount=fee_amount,
            vsize=tx.vsize(),
            fee_amount_is_estimated=False,
            vsize_is_estimated=not tx_has_final_size,
        )

    def get_chain_position(self, txid: str) -> bdk.ChainPosition | None:
        """Get chain position."""
        for wallet in get_wallets(self.wallet_functions):
            tx_details = wallet.get_tx(txid)
            if tx_details:
                return tx_details.chain_position
        return None

    def set_tx(
        self,
        tx: bdk.Transaction,
        fee_info: FeeInfo | None = None,
        chain_position: bdk.ChainPosition | None = None,
    ) -> None:
        """Set tx."""
        self.data = Data.from_tx(tx, network=self.network)
        fee_info = fee_info if fee_info else self._fetch_cached_feeinfo(str(tx.compute_txid()))
        if fee_info is None or fee_info.any_is_estimated():
            fee_info = self.calc_finalized_tx_fee_info(tx, tx_has_final_size=True)
        self.fee_info = fee_info

        if chain_position is None or isinstance(chain_position, bdk.ChainPosition.UNCONFIRMED):
            chain_position = self.get_chain_position(str(tx.compute_txid()))
        self.chain_position = chain_position

        tx_status = self.get_tx_status(chain_position=chain_position)

        tx_details, _wallet = get_tx_details(txid=self.txid(), wallet_functions=self.wallet_functions)

        self.column_fee.fee_group.set_fee_infos(
            fee_info=fee_info,
            tx_status=tx_status,
            can_rbf_safely=bool(
                tx_details and TxTools.can_rbf_safely(tx=tx_details.transaction, tx_status=tx_status)
            ),
        )

        if fee_info is not None:
            self.handle_cpfp(tx=tx, this_fee_info=fee_info, chain_position=chain_position)

        outputs = [TxOut.from_bdk(txout) for txout in tx.output()]
        advance_tip_for_addresses(
            addresses=[
                robust_address_str_from_txout(o, network=self.network, on_error_return_hex=False)
                for o in outputs
            ],
            wallet_functions=self.wallet_functions,
        )

        self.recipients.recipients = [
            Recipient(
                address=robust_address_str_from_txout(output, self.network),
                amount=output.value.to_sat(),
            )
            for output in outputs
        ]
        self.set_visibility(chain_position=chain_position)
        self.set_psbt_already_broadcasted_bar()
        self.set_tab_properties(chain_position=chain_position)
        self.update_all_totals()
        self.export_data_simple.set_data(
            data=self.data, sync_client=get_syncclients(wallet_functions=self.wallet_functions)
        )

        self._set_warning_bars(
            outpoints=[OutPoint.from_bdk(inp.previous_output) for inp in tx.input()],
            recipient_addresses=[recipient.address for recipient in self.recipients.recipients],
            tx_status=tx_status,
        )
        self.set_sankey(tx, fee_info=fee_info, txo_dict=self._get_python_txos())
        self.label_line_edit.updateUi()
        self.label_line_edit.autofill_label_and_category()
        self.container_label.setHidden(True)
        self.signal_updated_content.emit(self.data)

    def _get_python_txos(self):
        """Get python txos."""
        txo_dict: dict[str, PythonUtxo] = {}  # outpoint_str:PythonUTXO
        for wallet_ in get_wallets(self.wallet_functions):
            txo_dict.update(wallet_.get_all_txos_dict(include_not_mine=True))
        return txo_dict

    def set_sankey(
        self,
        tx: bdk.Transaction,
        fee_info: FeeInfo | None = None,
        txo_dict: dict[str, PythonUtxo] | None = None,
    ):
        """Set sankey."""

        async def do() -> bool:
            """Do."""
            try:
                return self.column_sankey.sankey_bitcoin.set_tx(tx, fee_info=fee_info, txo_dict=txo_dict)
            except Exception as e:
                logger.warning(str(e))
            return False

        def on_done(success: bool | None) -> None:
            """On done."""
            pass

        def on_success(success: bool | None) -> None:
            """On success."""
            self.fill_button_group()
            if not success:
                self.set_tab_focus(UiElements.default)

        def on_error(packed_error_info: ExcInfo | None) -> None:
            """On error."""
            logger.warning(str(packed_error_info))

        self.loop_in_thread.run_task(
            do(),
            on_done=on_done,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}set_sankey",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def set_tab_focus(self, focus_ui_element: UiElements):
        """Set tab focus."""
        self.focus_ui_element = focus_ui_element
        if self.focus_ui_element == UiElements.default:
            self.focus_tab(self.column_recipients)
        if self.focus_ui_element == UiElements.diagram:
            self.focus_tab(self.column_sankey)

        self.focus_ui_element = UiElements.none

    def get_tx_status(self, chain_position: bdk.ChainPosition | None) -> TxStatus:
        """Get tx status."""
        tx = self.extract_tx()
        return TxStatus(
            tx=tx,
            chain_position=chain_position,
            get_height=self._get_robust_height,
            fallback_confirmation_status=(
                TxConfirmationStatus.PSBT
                if self.data.data_type == DataType.PSBT
                else TxConfirmationStatus.LOCAL
            ),
        )

    def set_visibility(self, chain_position: bdk.ChainPosition | None) -> None:
        """Set visibility."""
        is_psbt = self.data.data_type == DataType.PSBT
        self.export_data_simple.setVisible(not is_psbt)
        self.tx_singning_steps_container.setVisible(is_psbt)

        tx_status = self.get_tx_status(chain_position=chain_position)
        tx_details, wallet = get_tx_details(txid=self.txid(), wallet_functions=self.wallet_functions)

        show_send = bool(tx_status.can_do_initial_broadcast() and self.data.data_type == DataType.Tx)
        logger.debug(
            f"set_visibility {show_send=} {tx_status.can_do_initial_broadcast()=} {self.data.data_type=}"
        )
        self.button_save_local_tx.setVisible(show_send and not tx_status.is_in_mempool())
        self.button_send.setEnabled(show_send)
        self.button_next.setVisible(self.data.data_type == DataType.PSBT)
        self.button_previous.setVisible(self.data.data_type == DataType.PSBT)

        edit_button_visible = TxTools.can_edit_safely(tx_status=tx_status)
        self.button_edit_tx.setVisible(edit_button_visible)
        # having a back button next to the edit button is confusing
        self.button_back.setVisible(not edit_button_visible)

        self.button_rbf.setVisible(
            bool(tx_details and TxTools.can_rbf_safely(tx=tx_details.transaction, tx_status=tx_status))
        )
        self.button_cpfp_tx.setVisible(
            TxTools.can_cpfp(tx_status=tx_status, wallet_functions=self.wallet_functions)
        )
        self.set_next_prev_button_enabledness()

    def _fetch_cached_feeinfo(self, txid: str) -> FeeInfo | None:
        """Fetch cached feeinfo."""
        if isinstance(self.data.data, bdk.Psbt) and self.data.data.extract_tx().compute_txid() == txid:
            return self.fee_info
        elif isinstance(self.data.data, bdk.Transaction) and self.data.data.compute_txid() == txid:
            return self.fee_info
        return None

    def set_psbt(self, psbt: bdk.Psbt, fee_info: FeeInfo | None = None) -> None:
        """_summary_

        Args:
            psbt (bdk.Psbt): _description_
            fee_rate (_type_, optional): This is the exact fee_rate chosen in txbuilder. If not given it has
                                        to be estimated with estimate_segwit_tx_size_from_psbt.
        """
        # check if any new signatures were added. If not tell the user

        self.data = Data.from_psbt(psbt, network=self.network)
        tx = psbt.extract_tx()
        txid = str(tx.compute_txid())
        fee_info = fee_info if fee_info else self._fetch_cached_feeinfo(txid)
        tx_status = self.get_tx_status(chain_position=None)
        # do not use calc_fee_info here, because calc_fee_info is for final tx only.

        # if still no fee_info  available, then estimate it
        if fee_info is None:
            fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)

        self.fee_info = fee_info

        self.column_fee.fee_group.set_fee_infos(
            fee_info=fee_info,
            tx_status=tx_status,
            can_rbf_safely=False,  # Since RBF doesnt apply for PSBT
        )

        outputs = [TxOut.from_bdk(txout) for txout in tx.output()]
        advance_tip_for_addresses(
            addresses=[
                robust_address_str_from_txout(o, network=self.network, on_error_return_hex=False)
                for o in outputs
            ],
            wallet_functions=self.wallet_functions,
        )

        self.recipients.recipients = [
            Recipient(
                address=robust_address_str_from_txout(output, self.network),
                amount=output.value.to_sat(),
            )
            for output in outputs
        ]

        self.tx_singning_steps = self.update_tx_progress()
        self.set_visibility(None)
        self.set_psbt_already_broadcasted_bar()
        self.set_tab_properties(chain_position=None)
        self.update_all_totals()
        self.handle_cpfp(tx=psbt.extract_tx(), this_fee_info=fee_info, chain_position=None)
        self._set_warning_bars(
            outpoints=[OutPoint.from_bdk(inp.previous_output) for inp in tx.input()],
            recipient_addresses=[recipient.address for recipient in self.recipients.recipients],
            tx_status=tx_status,
        )
        txo_dict = SimplePSBT.from_psbt(psbt).outpoints_as_python_utxo_dict(self.network)
        txo_dict.update(self._get_python_txos())
        self.set_sankey(tx, fee_info=fee_info, txo_dict=txo_dict)
        self.container_label.setHidden(True)
        self.signal_updated_content.emit(self.data)

    def set_psbt_already_broadcasted_bar(self):
        """Set psbt already broadcasted bar."""
        tx, wallet = get_tx_details(self.txid(), wallet_functions=self.wallet_functions)
        self.psbt_already_broadcasted_bar.set(wallet_tx_details=tx, wallet=wallet, data=self.data)

    def handle_cpfp(
        self, tx: bdk.Transaction, this_fee_info: FeeInfo, chain_position: bdk.ChainPosition | None
    ) -> None:
        """Handle cpfp."""
        parent_txids = set(str(txin.previous_output.txid) for txin in tx.input())
        self.set_cpfp_labels(
            parent_txids=parent_txids,
            this_fee_info=this_fee_info,
            fee_group=self.column_fee.fee_group,
            chain_position=chain_position,
        )

    def close(self):
        """Close."""
        self.column_sankey.close()
        self.column_recipients.close()
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setVisible(False)
        self.setParent(None)
        return super().close()
