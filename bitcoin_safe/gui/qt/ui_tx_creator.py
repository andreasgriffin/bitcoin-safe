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
from typing import Any, Dict, List, Optional, Tuple

import bdkpython as bdk
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.execute_config import GENERAL_RBF_AVAILABLE
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.block_change_signals import BlockChangesSignals
from bitcoin_safe.gui.qt.dialogs import question_dialog
from bitcoin_safe.gui.qt.fee_group import FeeGroup
from bitcoin_safe.gui.qt.spinning_button import SpinningButton
from bitcoin_safe.gui.qt.ui_tx_base import UITx_Base
from bitcoin_safe.gui.qt.warning_bars import LinkingWarningBar
from bitcoin_safe.signal_tracker import SignalTools
from bitcoin_safe.typestubs import TypedPyQtSignal

from ...config import MIN_RELAY_FEE, UserConfig
from ...mempool import MempoolData, TxPrio
from ...psbt_util import FeeInfo
from ...pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    TransactionDetails,
    UtxosForInputs,
    python_utxo_balance,
)
from ...signals import Signals, TypedPyQtSignalNo, UpdateFilter, UpdateFilterReason
from ...tx import TxUiInfos, calc_minimum_rbf_fee_info
from ...util import clean_list, format_fee_rate, time_logger
from ...wallet import ToolsTxUiInfo, TxConfirmationStatus, Wallet, get_wallets
from .category_list import CategoryList
from .dialog_import import ImportDialog
from .my_treeview import MyItemDataRole
from .nLockTimePicker import nLocktimePicker
from .recipients import Recipients, RecipientTabWidget, RecipientWidget
from .util import Message, MessageType
from .utxo_list import UTXOList, UtxoListWithToolbar

logger = logging.getLogger(__name__)


class UITx_Creator(UITx_Base):
    signal_input_changed: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_create_tx: TypedPyQtSignal[TxUiInfos] = pyqtSignal(TxUiInfos)  # type: ignore

    def __init__(
        self,
        wallet: Wallet,
        mempool_data: MempoolData,
        fx: FX,
        categories: List[str],
        widget_utxo_with_toolbar: UtxoListWithToolbar,
        utxo_list: UTXOList,
        config: UserConfig,
        signals: Signals,
        parent=None,
    ) -> None:
        super().__init__(config, signals, mempool_data, parent=parent)
        self.wallet = wallet
        self.categories = categories
        self.utxo_list = utxo_list
        self.widget_utxo_with_toolbar = widget_utxo_with_toolbar

        self.additional_outpoints: List[OutPoint] = []
        utxo_list.outpoints = self.get_outpoints()
        self.replace_tx: TransactionDetails | None = None

        self.searchable_list = utxo_list

        self.outer_widget_sub = QWidget()
        self.outer_widget_sub_layout = QHBoxLayout(self.outer_widget_sub)
        self.outer_widget_sub_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self._layout.addWidget(self.outer_widget_sub)

        self.splitter = QSplitter()
        self.outer_widget_sub_layout.addWidget(self.splitter)
        self.create_inputs_selector(self.splitter)

        self.widget_right_hand_side = QWidget()
        self.widget_right_hand_side_layout = QVBoxLayout(self.widget_right_hand_side)
        self.widget_right_hand_side_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.widget_right_top = QWidget(self)
        self.widget_right_top_layout = QHBoxLayout(self.widget_right_top)
        self.widget_right_top_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.widget_middle = QWidget(self)
        self.widget_middle_layout = QVBoxLayout(self.widget_middle)
        self.widget_right_top_layout.addWidget(self.widget_middle)
        self.widget_middle_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.balance_label = QLabel()
        font = QFont()
        font.setPointSize(12)
        self.balance_label.setFont(font)
        self._cache_last_category = None

        self.widget_middle_layout.addWidget(self.balance_label)

        self.recipients: Recipients = self.create_recipients(
            self.widget_middle_layout,
        )

        self.recipients.signal_clicked_send_max_button.connect(self.on_signal_amount_changed)
        self.recipients.add_recipient()

        self.fee_group = FeeGroup(
            mempool_data=mempool_data, fx=fx, config=self.config, enable_approximate_fee_label=False
        )
        self.widget_right_top_layout.addWidget(
            self.fee_group.groupBox_Fee, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.widget_right_hand_side_layout.addWidget(self.widget_right_top)

        self.button_box = QDialogButtonBox()
        ok_icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DialogOkButton)
        self.button_ok = SpinningButton(
            "",
            enable_signal=self.signals.wallet_signals[self.wallet.id].finished_psbt_creation,
            enabled_icon=ok_icon,
        )
        self.button_box.addButton(self.button_ok, QDialogButtonBox.ButtonRole.AcceptRole)
        if self.button_ok:
            self.button_ok.setDefault(True)
            self.button_ok.clicked.connect(self.create_tx)

        self.button_clear = self.button_box.addButton(QDialogButtonBox.StandardButton.Reset)
        if self.button_clear:
            self.button_clear.clicked.connect(self.clear_ui)

        self._layout.addWidget(self.button_box)

        self.splitter.addWidget(self.widget_right_hand_side)

        self.updateUi()
        self.tab_changed(0)

        # signals
        self.tabs_inputs.currentChanged.connect(self.tab_changed)
        self.mempool_data.signal_data_updated.connect(self.update_fee_rate_to_mempool)
        self.utxo_list.signal_selection_changed.connect(self.on_input_changed)
        self.recipients.signal_amount_changed.connect(self.on_signal_amount_changed)
        self.recipients.signal_added_recipient.connect(self.on_recipients_added)
        self.recipients.signal_removed_recipient.connect(self.on_recipients_removed)
        self.category_list.signal_tag_clicked.connect(self.on_category_list_clicked)
        self.signals.wallet_signals[self.wallet.id].updated.connect(self.update_with_filter)
        self.fee_group.signal_fee_rate_change.connect(self.on_fee_rate_change)
        self.signals.language_switch.connect(self.updateUi)

    def on_input_changed(self):
        fee_rate = self.fee_group.spin_fee_rate.value()
        # set max values
        fee_info = self.estimate_fee_info(fee_rate=fee_rate)
        self.reapply_max_amounts(fee_amount=fee_info.fee_amount)
        self.fee_group.set_fee_info(
            fee_info=fee_info,
        )

        # update fee infos (dependent on output amounts)
        self.update_high_fee_warning_label()
        self.update_opportunistic_checkbox()
        self.high_fee_rate_warning_label.update_fee_rate_warning(
            fee_rate=fee_rate,
            max_reasonable_fee_rate=self.mempool_data.max_reasonable_fee_rate(),
            confirmation_status=TxConfirmationStatus.LOCAL,
        )
        self.handle_cpfp()

    def on_fee_rate_change(self, fee_rate: float) -> None:
        self.on_input_changed()

    @time_logger
    def update_with_filter(self, update_filter: UpdateFilter) -> None:
        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.outpoints:
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter")
        self.update_balance_label()
        self.on_input_changed_and_categories()
        self.utxo_list.set_outpoints(self.get_outpoints())

    def updateUi(self) -> None:
        # translations
        self.label_select_input_categories.setText(self.tr("Select a category that fits the recipient best"))
        self.checkBox_reduce_future_fees.setText(self.tr("Reduce future fees\nby merging address balances"))
        self.tabs_inputs.setTabText(
            self.tabs_inputs.indexOf(self.tab_inputs_categories), self.tr("Send Category")
        )
        self.tabs_inputs.setTabText(self.tabs_inputs.indexOf(self.tab_inputs_utxos), self.tr("Advanced"))
        self.button_add_utxo.setText(self.tr("Add foreign UTXOs"))
        self.button_ok.setText(self.tr("Create"))

        # infos and warnings
        self.update_balance_label()

        # non-output dependent  values
        self.update_opportunistic_checkbox()
        self.fee_group.updateUi()

    def update_opportunistic_checkbox(self):
        fee_rate = self.fee_group.spin_fee_rate.value()

        opportunistic_merging_threshold = self.opportunistic_merging_threshold()
        self.checkBox_reduce_future_fees.setChecked(
            self.wallet.auto_opportunistic_coin_select and (fee_rate <= opportunistic_merging_threshold)
        )
        self.checkBox_reduce_future_fees.setToolTip(
            self.tr("This checkbox automatically checks \nbelow {rate}").format(
                rate=format_fee_rate(opportunistic_merging_threshold, self.config.network)
            )
        )

    def update_balance_label(self):
        balance = self.wallet.get_balance()
        display_balance = self.signals.wallet_signals[self.wallet.id].get_display_balance.emit()
        if display_balance:
            balance = display_balance

        # balance label
        self.balance_label.setText(balance.format_short(network=self.config.network))

    def on_signal_clicked_send_max_button(self, recipient_widget: RecipientWidget):
        self.on_input_changed()

    def on_category_list_clicked(self, tag: str):
        self.on_input_changed_and_categories()

    def on_recipients_added(self, recipient_tab_widget: RecipientTabWidget):
        recipient_tab_widget.signal_clicked_send_max_button.connect(self.on_signal_clicked_send_max_button)
        self.on_input_changed_and_categories()

    def on_recipients_removed(self, recipient_tab_widget: RecipientTabWidget):
        self.on_input_changed_and_categories()

    def on_signal_amount_changed(self, recipient_widget: Any):
        self.on_input_changed()

    def on_input_changed_and_categories(self):
        self.on_input_changed()
        self.update_categories()

    def update_high_fee_warning_label(self):
        fee_rate = self.fee_group.spin_fee_rate.value()
        fee_info = self.estimate_fee_info(fee_rate)

        total_non_change_output_amount = sum(
            [
                r.amount
                for r in self.recipients.recipients
                if not (self.wallet.is_my_address(r.address) and self.wallet.is_change(r.address))
            ]
        )
        self.high_fee_warning_label.set_fee_to_send_ratio(
            fee_info=fee_info,
            total_non_change_output_amount=total_non_change_output_amount,
            network=self.config.network,
            # if checked_max_amount, then the user might not notice a 0 output amount, and i better show a warning
            force_show_fee_warning_on_0_amont=any([r.checked_max_amount for r in self.recipients.recipients]),
            chain_position=None,
        )

    def update_categories(self):
        tx_ui_infos = self.get_ui_tx_infos()

        if not tx_ui_infos.utxo_dict:
            return

        addresses = clean_list(
            [
                recipient_group_box.address
                for recipient_group_box in self.recipients.get_recipient_group_boxes()
            ]
        )
        if not addresses:
            return
        recipient_category = self.wallet.determine_recipient_category(tx_ui_infos.utxo_dict.values())

        if recipient_category == self._cache_last_category:
            return

        self._cache_last_category = recipient_category
        self.wallet.set_psbt_output_categories(recipient_category=recipient_category, addresses=addresses)
        self.signals.wallet_signals[self.wallet.id].updated.emit(
            UpdateFilter(addresses=addresses, reason=UpdateFilterReason.TxCreator)
        )

    def reset_fee_rate(self) -> None:
        self.fee_group.set_spin_fee_value(self.mempool_data.get_prio_fee_rates()[TxPrio.low])

    def clear_ui(self) -> None:
        with BlockChangesSignals([self.utxo_list]):
            self.additional_outpoints.clear()
            self.utxo_list.set_outpoints(self.get_outpoints())
            self.set_ui(TxUiInfos())
            self.reset_fee_rate()
            self.utxo_list.update_content()
        self.tabs_inputs.setCurrentIndex(0)
        self.category_list.select_category(self.wallet.labels.get_default_category())
        self.on_input_changed_and_categories()

    def create_tx(self) -> None:
        if (
            self.tabs_inputs.currentWidget() == self.tab_inputs_categories
            and not self.category_list.get_selected()
        ):
            Message(
                self.tr("Please select an input category on the left, that fits the transaction recipients.")
            )
            self.signals.wallet_signals[self.wallet.id].finished_psbt_creation.emit()
            return

        ui_tx_infos = self.get_ui_tx_infos()
        wallets = get_wallets(self.signals)

        # warn if multiple categories are combined
        category_dict = self.get_category_dict_of_addresses(
            [utxo.address for utxo in ui_tx_infos.utxo_dict.values()], wallets=wallets
        )
        if len(category_dict) > 1:
            Message(
                LinkingWarningBar.get_warning_text(category_dict),
                type=MessageType.Warning,
            )
            if not question_dialog(
                self.tr("Do you want to continue, even though both coin categories become linkable?"),
                title="Category Linking",
            ):
                self.signals.wallet_signals[self.wallet.id].finished_psbt_creation.emit()
                return

        self.signal_create_tx.emit(ui_tx_infos)

    def update_fee_rate_to_mempool(self) -> None:
        "Do this only ONCE after the mempool data is fetched"
        if self.fee_group.spin_fee_rate.value() == MIN_RELAY_FEE:
            self.reset_fee_rate()
        self.mempool_data.signal_data_updated.disconnect(self.update_fee_rate_to_mempool)

    def get_outpoints(self) -> List[OutPoint]:
        return [utxo.outpoint for utxo in self.wallet.get_all_utxos()] + self.additional_outpoints

    def create_inputs_selector(self, splitter: QSplitter) -> None:

        self.tabs_inputs = QTabWidget(self)
        self.tabs_inputs.setMinimumWidth(200)
        self.tab_inputs_categories = QWidget(self)
        self.tabs_inputs.addTab(self.tab_inputs_categories, "")

        # tab categories
        self.verticalLayout_inputs = QVBoxLayout(self.tab_inputs_categories)
        self.label_select_input_categories = QLabel()
        self.label_select_input_categories.setWordWrap(True)
        self.checkBox_reduce_future_fees = QCheckBox(self.tab_inputs_categories)
        self.checkBox_reduce_future_fees.clicked.connect(self.on_checkBox_reduce_future_fees)
        self.checkBox_reduce_future_fees.setChecked(True)

        # Taglist
        self.category_list = CategoryList(
            self.signals.wallet_signals[self.wallet.id],
            immediate_release=False,
        )
        first_entry = self.category_list.item(0)
        if first_entry:
            first_entry.setSelected(True)
        self.verticalLayout_inputs.addWidget(self.label_select_input_categories)
        self.verticalLayout_inputs.addWidget(self.category_list)

        self.verticalLayout_inputs.addWidget(self.checkBox_reduce_future_fees)

        # tab utxos
        self.tab_inputs_utxos = QWidget(self)
        self.verticalLayout_inputs_utxos = QVBoxLayout(self.tab_inputs_utxos)
        self.tabs_inputs.addTab(self.tab_inputs_utxos, "")

        self.verticalLayout_inputs_utxos.addWidget(self.widget_utxo_with_toolbar)

        # utxo list
        self.button_add_utxo = QPushButton()
        if hasattr(bdk.TxBuilder(), "add_foreign_utxo"):
            self.button_add_utxo.clicked.connect(self.click_add_utxo)
            self.verticalLayout_inputs_utxos.addWidget(self.button_add_utxo)

        # nLocktime
        self.nlocktime_picker = nLocktimePicker()
        # TODO actiavte this as soon as https://docs.rs/bdk/latest/bdk/wallet/tx_builder/struct.TxBuilder.html#method.nlocktime is exposed in ffi
        self.nlocktime_picker.setHidden(True)
        self.verticalLayout_inputs_utxos.addWidget(self.nlocktime_picker)

        splitter.addWidget(self.tabs_inputs)

        # select the first one with !=0 balance
        # TODO:  this doesnt work however, because the wallet sync happens after this creation
        category_utxo_dict = self.wallet.get_category_python_utxo_dict()

        def get_idx_non_zero_category() -> Optional[int]:
            for i, category in enumerate(self.wallet.labels.categories):
                if python_utxo_balance(category_utxo_dict.get(category, [])) > 0:
                    return i
            return None

        if (idx_non_zero_category := get_idx_non_zero_category()) is not None and (
            _item := self.category_list.item(idx_non_zero_category)
        ):
            _item.setSelected(True)

    def on_checkBox_reduce_future_fees(self):
        if self.checkBox_reduce_future_fees.isChecked():
            self.wallet.auto_opportunistic_coin_select = True
        else:
            if question_dialog(
                "Do you want to deactivate auto-merging by default?",
                title="Deactivate by default?",
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ):
                self.wallet.auto_opportunistic_coin_select = False
            else:
                pass

    def add_outpoints(self, outpoints: List[OutPoint]) -> None:
        old_outpoints = self.get_outpoints()
        for outpoint in outpoints:
            if outpoint not in old_outpoints:
                self.additional_outpoints.append(outpoint)
        self.utxo_list.set_outpoints(self.get_outpoints())

    def click_add_utxo(self) -> None:
        def process_input(s: str) -> None:
            outpoints = [OutPoint.from_str(row.strip()) for row in s.strip().split("\n")]
            self.add_outpoints(outpoints)
            self.utxo_list.update_content()
            self.utxo_list.select_rows(outpoints, self.utxo_list.key_column, role=MyItemDataRole.ROLE_KEY)

        ImportDialog(
            self.config.network,
            on_open=process_input,
            window_title=self.tr("Add Inputs"),
            text_button_ok=self.tr("Load UTXOs"),
            text_instruction_label=self.tr(
                "Please paste UTXO here in the format  txid:outpoint\ntxid:outpoint"
            ),
            text_placeholder=self.tr("Please paste UTXO here"),
            close_all_video_widgets=self.signals.close_all_video_widgets,
        ).show()

    def opportunistic_merging_threshold(self) -> float:
        """Calculates the ema fee rate from past transactions.
        Then it lowers this to the low prio mempool fee rate
        (if the high prio fee rate it is 10x higher than the min relay fee).
        """
        fee_rate = self.wallet.get_ema_fee_rate()

        if self.mempool_data.get_prio_fee_rates()[TxPrio.high] >= 10 * MIN_RELAY_FEE:
            # assume, fee_rate = 5 sat/vb.
            # And the mempool is empty. Then enevn the high prio fee rate is 1 sat/vb.
            # the opportunistic_merging_threshold should remain at 5 sat/vB.
            #
            # However if we are in a high fee environment,
            # then the opportunistic_merging should only occur if we are <=  low prio fee rate
            fee_rate = min(fee_rate, self.mempool_data.get_prio_fee_rates()[TxPrio.low])
        return fee_rate

    def _select_minimum_number_utxos_no_fee(
        self, utxos_for_input: UtxosForInputs, send_value: int
    ) -> UtxosForInputs:
        if utxos_for_input.spend_all_utxos or not utxos_for_input.utxos:
            return utxos_for_input

        utxo_values = np.array([utxo.txout.value for utxo in utxos_for_input.utxos])
        sort_filter: List[int] = (np.argsort(utxo_values)[::-1]).tolist()

        selected_utxos: List[PythonUtxo] = []
        for i in sort_filter:
            utxo = utxos_for_input.utxos[i]
            selected_utxos.append(utxo)
            if sum([utxo.txout.value for utxo in selected_utxos]) >= send_value:
                break

        return UtxosForInputs(
            utxos=selected_utxos,
            included_opportunistic_merging_utxos=utxos_for_input.included_opportunistic_merging_utxos,
            spend_all_utxos=utxos_for_input.spend_all_utxos,
        )

    def estimate_fee_info(self, fee_rate: float | None = None) -> FeeInfo:
        sent_values = [r.amount for r in self.recipients.recipients]
        # one more output for the change
        num_outputs = len(sent_values) + 1
        if fee_rate is None:
            fee_rate = self.fee_group.spin_fee_rate.value()

        txinfos = self.get_ui_tx_infos()

        utxos_for_input = self._select_minimum_number_utxos_no_fee(
            UtxosForInputs(list(txinfos.utxo_dict.values()), spend_all_utxos=txinfos.spend_all_utxos),
            send_value=sum(sent_values),
        )

        num_inputs = max(1, len(utxos_for_input.utxos))  # assume all inputs come from this wallet
        fee_info = FeeInfo.estimate_from_num_inputs(
            fee_rate,
            input_mn_tuples=[self.wallet.get_mn_tuple() for i in range(num_inputs)],
            num_outputs=num_outputs,
        )
        return fee_info

    def get_ui_tx_infos(self, use_this_tab=None) -> TxUiInfos:
        infos = TxUiInfos()
        infos.replace_tx = self.replace_tx
        infos.opportunistic_merge_utxos = self.checkBox_reduce_future_fees.isChecked()

        for recipient in self.recipients.recipients:
            infos.add_recipient(recipient)

        # logger.debug(
        #     f"set psbt builder fee_rate {self.fee_group.spin_fee_rate.value()}"
        # )
        infos.set_fee_rate(self.fee_group.spin_fee_rate.value())

        if not use_this_tab:
            use_this_tab = self.tabs_inputs.currentWidget()

        wallets = [self.wallet] if use_this_tab == self.tab_inputs_categories else get_wallets(self.signals)

        if use_this_tab == self.tab_inputs_categories:
            ToolsTxUiInfo.fill_utxo_dict_from_categories(infos, self.category_list.get_selected(), wallets)

        if use_this_tab == self.tab_inputs_utxos:
            ToolsTxUiInfo.fill_txo_dict_from_outpoints(
                infos, self.utxo_list.get_selected_outpoints(), wallets
            )
            infos.spend_all_utxos = True
        return infos

    def get_global_xpub_dict(self, wallets: List[Wallet]) -> Dict[str, Tuple[str, str]]:
        return {
            keystore.xpub: (keystore.fingerprint, keystore.key_origin)
            for wallet in wallets
            for keystore in wallet.keystores
        }

    def reapply_max_amounts(self, fee_amount: int) -> None:
        recipient_group_boxes = self.recipients.get_recipient_group_boxes()
        for recipient_group_box in recipient_group_boxes:
            recipient_group_box.recipient_widget.amount_spin_box.set_warning_maximum(
                self.get_total_input_value()
            )

        recipient_group_boxes_max_checked = [
            recipient_group_box
            for recipient_group_box in recipient_group_boxes
            if recipient_group_box.recipient_widget.send_max_button.isChecked()
        ]
        total_change_amount = max(0, self.get_total_change_amount(include_max_checked=False) - fee_amount)
        for recipient_group_box in recipient_group_boxes_max_checked:
            self.set_max_amount(
                recipient_group_box, total_change_amount // len(recipient_group_boxes_max_checked)
            )

    def get_total_input_value(self) -> int:
        txinfos = self.get_ui_tx_infos()
        total_input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values() if utxo])
        return total_input_value

    def get_total_change_amount(self, include_max_checked=False) -> int:
        txinfos = self.get_ui_tx_infos()
        total_input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values() if utxo])

        total_output_value = sum(
            [
                recipient.amount
                for recipient in txinfos.recipients
                if (recipient.checked_max_amount and include_max_checked) or not recipient.checked_max_amount
            ]
        )  # this includes the old value of the spinbox

        total_change_amount = total_input_value - total_output_value
        return total_change_amount

    def set_max_amount(self, recipient_group_box: RecipientTabWidget, max_amount: int) -> None:
        with BlockChangesSignals([recipient_group_box]):

            recipient_group_box.recipient_widget.amount_spin_box.setValue(max_amount)

    def tab_changed(self, index: int) -> None:
        # pyqtSlot called when the current tab changes
        # print(f"Tab changed to index {index}")

        if index == 0:
            self.splitter.setSizes([200, 600])
        elif index == 1:
            self.splitter.setSizes([400, 600])

            # take the coin selection from the category to the utxo tab (but only if one is selected)
            self.set_coin_selection_in_sent_tab(self.get_ui_tx_infos(self.tab_inputs_categories))
        self.on_input_changed()

    def set_coin_selection_in_sent_tab(self, txinfos: TxUiInfos) -> None:
        utxos_for_input = self.wallet.handle_opportunistic_merge_utxos(txinfos)

        utxo_names = [utxo.outpoint for utxo in utxos_for_input.utxos]
        self.utxo_list.select_rows(utxo_names, column=self.utxo_list.key_column)

    def handle_conflicting_utxo(self, txinfos: TxUiInfos) -> None:
        ##################
        # detect and handle rbf
        conflicting_python_txos = self.wallet.get_conflicting_python_txos(txinfos.utxo_dict.keys())

        conflicting_txids = [
            conflicting_python_txo.is_spent_by_txid
            for conflicting_python_txo in conflicting_python_txos
            if conflicting_python_txo.is_spent_by_txid
        ]
        tx_details = [self.wallet.get_tx(conflicting_txid) for conflicting_txid in conflicting_txids]
        chain_positions = [tx.chain_position for tx in tx_details if tx]

        conflicting_confirmed = set(
            [
                conflicting_python_utxo
                for conflicting_python_utxo, chain_position in zip(conflicting_python_txos, chain_positions)
                if chain_position.is_confirmed()
            ]
        )
        if conflicting_confirmed:
            Message(
                self.tr("The inputs {inputs} conflict with these confirmed txids {txids}.").format(
                    inputs=[utxo.outpoint for utxo in conflicting_confirmed],
                    txids=[utxo.is_spent_by_txid for utxo in conflicting_confirmed],
                )
            )
        conflicted_unconfirmed = set(conflicting_python_txos) - conflicting_confirmed
        if conflicted_unconfirmed:
            # RBF is going on
            # these involved txs i can do rbf

            # for each conflicted_unconfirmed, get all roots and dependents
            dependents_to_be_replaced: List[TransactionDetails] = []
            for utxo in conflicted_unconfirmed:
                if utxo.is_spent_by_txid:
                    dependents_to_be_replaced += [
                        fulltx.tx
                        for fulltx in self.wallet.get_fulltxdetail_and_dependents(
                            utxo.is_spent_by_txid, include_root_tx=False
                        )
                    ]
            if dependents_to_be_replaced:
                Message(
                    self.tr(
                        "The unconfirmed dependent transactions {txids} will be removed by this new transaction you are creating."
                    ).format(txids=[dependent.txid for dependent in dependents_to_be_replaced])
                )

            # for each conflicted_unconfirmed, get all roots and dependents
            txs_to_be_replaced = []
            for utxo in conflicted_unconfirmed:
                if utxo.is_spent_by_txid:
                    txs_to_be_replaced += [
                        fulltx.tx
                        for fulltx in self.wallet.get_fulltxdetail_and_dependents(utxo.is_spent_by_txid)
                    ]

            fee_amount = sum([(tx_details.fee or 0) for tx_details in txs_to_be_replaced])

            # because BumpFeeTxBuilder cannot build tx with too low fee,
            # we have to raise errors, if fee cannot be calculated
            fee_info = None
            if GENERAL_RBF_AVAILABLE:
                try:
                    builder_infos = self.wallet.create_psbt(txinfos)
                    fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(builder_infos.psbt)
                except Exception:
                    pass
            else:
                assert txinfos.replace_tx, "No replace_tx provided"
                fee_info = FeeInfo.from_txdetails(txinfos.replace_tx)

            if not fee_info:
                raise Exception("General RBF is currently not provided by bdk")

            txinfos.fee_rate = calc_minimum_rbf_fee_info(
                fee_amount, fee_info.vsize, self.mempool_data
            ).fee_rate()
            if not GENERAL_RBF_AVAILABLE:
                # the BumpFeeTxBuilder disallows the minimum rbf fee, and requires a slightly higer fee
                # the error message by BumpFeeTxBuilder is unfortunately completely wrong (and giving a >=2*minimum_rbf_fee_rate)
                txinfos.fee_rate += 0.1

            self.fee_group.set_rbf_label(txinfos.fee_rate)
            self.fee_group.set_fee_infos(fee_info=fee_info, chain_position=None)

            self.add_outpoints([python_utxo.outpoint for python_utxo in txinfos.utxo_dict.values()])
        else:
            self.fee_group.set_rbf_label(None)

    def handle_cpfp(self) -> None:
        utxos = list(self.get_ui_tx_infos().utxo_dict.values())
        parent_txids = set(utxo.outpoint.txid for utxo in utxos)
        self.set_fee_group_cpfp_label(
            parent_txids=parent_txids,
            this_fee_info=self.estimate_fee_info(),
            fee_group=self.fee_group,
            chain_position=None,
        )

    def set_ui(self, txinfos: TxUiInfos) -> None:
        self.handle_conflicting_utxo(txinfos=txinfos)
        self.handle_cpfp()

        if txinfos.fee_rate:
            self.fee_group.set_spin_fee_value(txinfos.fee_rate)

        # do first tab_changed, because it will set the utxo_list.select_rows
        if not txinfos.hide_UTXO_selection:
            self.tab_changed(self.tabs_inputs.currentIndex())

        self.utxo_list.update_content()
        self.tabs_inputs.setCurrentWidget(self.tab_inputs_utxos)
        self.utxo_list.select_rows(
            txinfos.utxo_dict.keys(),
            self.utxo_list.key_column,
            role=MyItemDataRole.ROLE_KEY,
        )

        if txinfos.hide_UTXO_selection:
            self.splitter.setSizes([0, 1])

        # do the recipients after the utxo list setting. otherwise setting the uxtos,
        # will reduce the sent amount to what is maximally possible, by the selected utxos
        self.recipients.set_allow_edit(not txinfos.recipient_read_only)
        self.recipients.recipients = txinfos.recipients
        if not self.recipients.recipients:
            self.recipients.add_recipient()

        self.recipients.set_allow_edit(not txinfos.recipient_read_only)
        self.utxo_list.set_allow_edit(not txinfos.utxos_read_only)
        self.tabs_inputs.setEnabled(not txinfos.utxos_read_only)
        self.replace_tx = txinfos.replace_tx

    def close(self):
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)

        self.category_list.close()
        self.widget_utxo_with_toolbar.close()
        self.setParent(None)
        super().close()
