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
from typing import Any, Dict, List, Set, Tuple

import bdkpython as bdk
import numpy as np
from bitcoin_safe_lib.gui.qt.satoshis import format_fee_rate
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalTools, SignalTracker
from bitcoin_safe_lib.util import clean_list, time_logger
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QDialogButtonBox, QHBoxLayout, QSplitter, QWidget

from bitcoin_safe.execute_config import GENERAL_RBF_AVAILABLE
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.block_change_signals import BlockChangesSignals
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.gui.qt.category_manager.category_list import CategoryList
from bitcoin_safe.gui.qt.dialogs import question_dialog
from bitcoin_safe.gui.qt.spinning_button import SpinningButton
from bitcoin_safe.gui.qt.ui_tx.columns import ColumnFee, ColumnInputs, ColumnRecipients
from bitcoin_safe.gui.qt.ui_tx.ui_tx_base import UITx_Base
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.warning_bars import LinkingWarningBar
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.typestubs import TypedPyQtSignal

from ....config import MIN_RELAY_FEE, UserConfig
from ....mempool_manager import MempoolManager, TxPrio
from ....psbt_util import FeeInfo
from ....pythonbdk_types import OutPoint, PythonUtxo, TransactionDetails, UtxosForInputs
from ....signals import Signals, TypedPyQtSignalNo, UpdateFilter, UpdateFilterReason
from ....tx import TxUiInfos, calc_minimum_rbf_fee_info
from ....wallet import (
    ToolsTxUiInfo,
    TxConfirmationStatus,
    TxStatus,
    Wallet,
    get_tx_details,
    get_wallets,
)
from ..dialog_import import ImportDialog
from ..my_treeview import MyItemDataRole
from ..util import HLine, Message, MessageType
from ..utxo_list import UTXOList, UtxoListWithToolbar
from .recipients import RecipientBox, RecipientWidget

logger = logging.getLogger(__name__)


class UITx_Creator(UITx_Base, BaseSaveableClass):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        UtxoListWithToolbar.__name__: UtxoListWithToolbar,
        CategoryList.__name__: CategoryList,
        TxUiInfos.__name__: TxUiInfos,
    }

    signal_input_changed: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_create_tx: TypedPyQtSignal[TxUiInfos] = pyqtSignal(TxUiInfos)  # type: ignore

    def __init__(
        self,
        mempool_manager: MempoolManager,
        fx: FX,
        config: UserConfig,
        signals: Signals,
        wallet_id: str = "",
        category_core: CategoryCore | None = None,
        opportunistic_coin_select: bool = False,
        manual_coin_select: bool = False,
        tx_ui_infos: TxUiInfos | None = None,
        category_list: CategoryList | None = None,
        utxo_list_with_toolbar: UtxoListWithToolbar | None = None,
        parent=None,
    ) -> None:
        super().__init__(
            config=config, fx=fx, signals=signals, mempool_manager=mempool_manager, parent=parent
        )
        self.wallet: Wallet | None = category_core.wallet if category_core else None
        self._was_shown = False
        self.wallet_id = wallet_id
        self.initial_tx_ui_infos = tx_ui_infos
        self._signal_tracker_wallet_signals = SignalTracker()

        if category_list:
            self.category_list = category_list
            category_list.set_category_core(category_core=category_core)
        else:
            self.category_list = CategoryList(
                config=self.config,
                category_core=category_core,
                signals=signals,
                hidden_columns=(
                    [
                        CategoryList.Columns.COLOR,
                        CategoryList.Columns.TXO_BALANCE,
                        CategoryList.Columns.TXO_COUNT,
                        CategoryList.Columns.ADDRESS_COUNT,
                    ]
                ),
            )
        self.category_list.setDragEnabled(False)
        self.category_list.setAcceptDrops(False)

        if utxo_list_with_toolbar:
            self.utxo_list = utxo_list_with_toolbar.utxo_list
            self.utxo_list_with_toolbar = utxo_list_with_toolbar
        else:
            self.utxo_list = UTXOList(
                config=self.config,
                signals=self.signals,
                outpoints=[],
                fx=self.fx,
                hidden_columns=(
                    [
                        UTXOList.Columns.OUTPOINT,
                        UTXOList.Columns.WALLET_ID,
                        UTXOList.Columns.FIAT_BALANCE,
                    ]
                ),
                sort_column=UTXOList.Columns.STATUS,
                sort_order=Qt.SortOrder.AscendingOrder,
            )

            self.utxo_list_with_toolbar = UtxoListWithToolbar(self.utxo_list, self.config, parent=self)

        self.additional_outpoints: List[OutPoint] = []
        self.utxo_list.outpoints = self.get_outpoints()
        self.replace_tx: bdk.Transaction | None = None

        self.searchable_list = self.utxo_list

        self.outer_widget_sub = QWidget()
        self.outer_widget_sub_layout = QHBoxLayout(self.outer_widget_sub)
        self.outer_widget_sub_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self._layout.addWidget(self.outer_widget_sub)

        self.splitter = QSplitter()
        self.outer_widget_sub_layout.addWidget(self.splitter)

        #     return self.tabs_inputs
        self.column_inputs = ColumnInputs(
            category_list=self.category_list,
            widget_utxo_with_toolbar=self.utxo_list_with_toolbar,
            fx=self.fx,
            parent=self,
        )
        self.column_inputs.checkBox_auto_opportunistic_coin_select.clicked.connect(
            self.on_checkBox_opportunistic_coin_select
        )
        self.splitter.addWidget(self.column_inputs)

        self.column_recipients = ColumnRecipients(fx=fx, signals=self.signals, parent=self)
        self._cache_last_category: str | None = None
        self.recipients = self.column_recipients.recipients

        self.recipients.signal_clicked_send_max_button.connect(self.on_signal_amount_changed)

        self.column_fee = ColumnFee(
            signals=signals,
            mempool_manager=mempool_manager,
            fx=fx,
            parent=self,
            enable_approximate_fee_label=False,
            tx_status=self.get_tx_status(),
        )

        self.button_box = QDialogButtonBox()
        self.button_ok = SpinningButton(
            "",
            enable_signal=(
                _wallet_signal.finished_psbt_creation
                if self.wallet and (_wallet_signal := self.signals.wallet_signals.get(self.wallet.id))
                else None
            ),
            enabled_icon=svg_tools.get_QIcon("checkmark.svg"),
        )
        self.button_box.addButton(self.button_ok, QDialogButtonBox.ButtonRole.AcceptRole)
        if self.button_ok:
            self.button_ok.setDefault(True)
            self.button_ok.clicked.connect(self.create_tx)

        self.button_clear = self.button_box.addButton(QDialogButtonBox.StandardButton.Reset)
        if self.button_clear:
            self.button_clear.clicked.connect(self.clear_ui)

        self._layout.addWidget(HLine())
        self._layout.addWidget(self.button_box)

        self.splitter.addWidget(self.column_recipients)
        self.splitter.addWidget(self.column_fee)
        # Make sure it never collapses:
        self.splitter.setSizes([1, 10, 1])
        self.splitter.setCollapsible(self.splitter.indexOf(self.column_inputs), True)
        self.splitter.setCollapsible(self.splitter.indexOf(self.column_recipients), False)
        self.splitter.setCollapsible(self.splitter.indexOf(self.column_fee), False)
        # # No stretch: this pane won't grow or shrink
        self.splitter.setStretchFactor(self.splitter.indexOf(self.column_inputs), 2)
        self.splitter.setStretchFactor(self.splitter.indexOf(self.column_recipients), 1)
        self.splitter.setStretchFactor(self.splitter.indexOf(self.column_fee), 0)

        self.column_inputs.checkBox_auto_opportunistic_coin_select.setChecked(opportunistic_coin_select)
        self.column_inputs.checkBox_manual_coin_select.setChecked(manual_coin_select)

        self.set_category_core(category_core=category_core)
        self.updateUi()
        self.set_utxo_list_visible(manual_coin_select)

        # signals
        self.column_inputs.checkBox_manual_coin_select.checkStateChanged.connect(
            self.coin_selection_checkbox_state_change
        )
        self.mempool_manager.signal_data_updated.connect(self.update_fee_rate_to_mempool)
        self.utxo_list.signal_selection_changed.connect(self.on_input_changed)
        self.recipients.signal_amount_changed.connect(self.on_signal_amount_changed)
        self.recipients.signal_added_recipient.connect(self.on_recipients_added)
        self.recipients.signal_removed_recipient.connect(self.on_recipients_removed)
        self.category_list.signal_selection_changed.connect(self.on_category_selection_changed)
        self.column_fee.fee_group.signal_fee_rate_change.connect(self.on_fee_rate_change)
        self.signals.language_switch.connect(self.updateUi)
        self.signals.currency_switch.connect(self.update_all_totals)

        # must be after setting signals, to trigger signals when adding a recipient
        self.recipients.add_recipient()

    def dump(self) -> Dict[str, Any]:
        d = super().dump()
        d["wallet_id"] = self.wallet_id
        d["opportunistic_coin_select"] = (
            self.column_inputs.checkBox_auto_opportunistic_coin_select.isChecked()
        )
        d["manual_coin_select"] = self.column_inputs.checkBox_manual_coin_select.isChecked()
        d["utxo_list_with_toolbar"] = self.utxo_list_with_toolbar
        d["category_list"] = self.category_list
        d["tx_ui_infos"] = self.get_tx_ui_infos()
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None):
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def set_category_core(self, category_core: CategoryCore | None):
        self._signal_tracker_wallet_signals.disconnect_all()
        if category_core and self.wallet_id and category_core.wallet.id != self.wallet_id:
            raise ValueError(
                f"Cannot set a different wallet than {self.wallet_id} to prevent inconsistencies"
            )
        self.category_list.set_category_core(category_core)
        self.wallet = category_core.wallet if category_core else None
        if self.wallet and (_wallet_signals := self.signals.wallet_signals.get(self.wallet.id)):
            self._signal_tracker_wallet_signals.connect(_wallet_signals.updated, self.update_with_filter)

        if self.wallet and (_wallet_signal := self.signals.wallet_signals.get(self.wallet.id)):
            self.button_ok.set_enable_signal(enable_signal=(_wallet_signal.finished_psbt_creation))

    def get_tx_status(self) -> TxStatus:
        return TxStatus(
            tx=None,
            chain_position=None,
            get_height=self._get_robust_height,
            fallback_confirmation_status=(TxConfirmationStatus.DRAFT),
        )

    def on_input_changed(self):
        fee_rate = self.column_fee.fee_group.spin_fee_rate.value()
        # set max values
        fee_info = self.estimate_fee_info(fee_rate=fee_rate)
        self.reapply_max_amounts(fee_amount=fee_info.fee_amount)
        self.column_fee.fee_group.set_fee_info(
            fee_info=fee_info,
        )

        if self.column_inputs.checkBox_manual_coin_select.isChecked():
            selected_categories = set([c.category for c in self.category_list.get_selected_category_infos()])
            self.utxo_list.set_filter_categories(selected_categories if selected_categories else None)

        tx_ui_infos = self.get_tx_ui_infos()

        # update fee infos (dependent on output amounts)
        self.update_opportunistic_checkbox()
        self.high_fee_rate_warning_label.update_fee_rate_warning(
            fee_rate=fee_rate,
            max_reasonable_fee_rate=self.mempool_manager.max_reasonable_fee_rate(),
            confirmation_status=TxConfirmationStatus.LOCAL,
        )
        self.handle_cpfp(txinfos=tx_ui_infos)
        self.update_sending_source_totals()
        self.update_recipients_totals()

        self._set_warning_bars(
            outpoints=list(tx_ui_infos.utxo_dict.keys()),
            recipient_addresses=[recipient.address for recipient in self.recipients.recipients],
            tx_status=self.get_tx_status(),
        )

    def _set_warning_bars(
        self, outpoints: List[OutPoint], recipient_addresses: List[str], tx_status: TxStatus
    ):
        super()._set_warning_bars(
            outpoints=outpoints, recipient_addresses=recipient_addresses, tx_status=tx_status
        )
        self.update_high_fee_warning_label()

    def showEvent(self, a0: QShowEvent | None):
        if not self._was_shown:
            self._was_shown = True
            if self.initial_tx_ui_infos:
                self.set_ui(tx_ui_infos=self.initial_tx_ui_infos)
            else:
                self.clear_ui()

        super().showEvent(a0)

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
        self.on_input_changed_and_categories()
        self.utxo_list.set_outpoints(self.get_outpoints())

    def update_recipients_totals(self):
        amount = self._get_total_non_change_output_amount(
            self.recipients.recipients,
        )
        self.column_recipients.totals.set_amount(amount)

    def update_sending_source_totals(self):
        selected_values = (
            self.utxo_list.get_selected_values()
            if self.column_inputs.checkBox_manual_coin_select.isChecked()
            else self.category_list.get_selected_values()
        )
        amount = sum(selected_values)
        self.column_inputs.totals.set_amount(amount)

    def update_all_totals(self):
        self.update_sending_source_totals()
        self.update_recipients_totals()
        self.column_fee.updateUi()

    def updateUi(self) -> None:
        super().updateUi()
        # translations
        self.column_inputs.updateUi()
        self.column_recipients.updateUi()
        self.column_fee.updateUi()
        self.button_ok.setText(self.tr("Create"))

        # non-output dependent  values
        self.update_opportunistic_checkbox()
        self.update_all_totals()
        self.column_fee.header_widget.syncWith(
            self.column_inputs.header_widget, self.column_recipients.header_widget
        )

    def update_opportunistic_checkbox(self):
        opportunistic_merging_threshold = self.opportunistic_merging_threshold()
        self.column_inputs.checkBox_auto_opportunistic_coin_select.setText(
            self.tr("Reduce future fees by merging UTXOs below {rate}").format(
                rate=format_fee_rate(opportunistic_merging_threshold, self.config.network)
            )
        )
        self.column_inputs.checkBox_auto_opportunistic_coin_select.setToolTip(
            self.tr(
                "Additional inputs may be added \nbelow {rate} to consolidate UTXOs and reduce future fees"
            ).format(rate=format_fee_rate(opportunistic_merging_threshold, self.config.network))
        )

    def on_signal_clicked_send_max_button(self, recipient_widget: RecipientWidget):
        self.on_input_changed()

    def on_signal_address_text_changed(self, recipient_widget: RecipientWidget):
        self.update_categories()

    def clear_utxo_list_selection(self):
        self.utxo_list.select_rows([], self.utxo_list.key_column, role=MyItemDataRole.ROLE_KEY)

    def on_category_selection_changed(self):
        if self.column_inputs.checkBox_auto_opportunistic_coin_select.isChecked():
            self.coin_selection_checkbox_state_change()
        else:
            self.on_input_changed_and_categories()  # this hides rows in utxo_list
            self.utxo_list.restrict_selection_to_non_hidden_rows()

    def on_recipients_added(self, recipient_tab_widget: RecipientBox):
        recipient_tab_widget.signal_clicked_send_max_button.connect(self.on_signal_clicked_send_max_button)
        recipient_tab_widget.signal_address_text_changed.connect(self.on_signal_address_text_changed)
        self.on_input_changed_and_categories()

    def on_recipients_removed(self, recipient_box: RecipientBox):
        self.on_input_changed_and_categories()

    def on_signal_amount_changed(self, recipient_widget: Any):
        self.on_input_changed()

    def on_input_changed_and_categories(self):
        self.on_input_changed()
        self.update_categories()

    def update_high_fee_warning_label(self):
        fee_rate = self.column_fee.fee_group.spin_fee_rate.value()
        fee_info = self.estimate_fee_info(fee_rate)
        self._update_high_fee_warning_label(
            recipients=self.recipients, fee_info=fee_info, tx_status=self.get_tx_status()
        )

    def update_categories(self):
        if not self.wallet:
            return
        tx_ui_infos = self.get_tx_ui_infos()

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
        assigned_addresses = self.wallet.set_addresses_category_if_unused(
            recipient_category=recipient_category, addresses=addresses
        )

        self._set_warning_bars(
            outpoints=list(tx_ui_infos.utxo_dict.keys()),
            recipient_addresses=[recipient.address for recipient in self.recipients.recipients],
            tx_status=self.get_tx_status(),
        )

        self.signals.wallet_signals[self.wallet.id].updated.emit(
            UpdateFilter(addresses=assigned_addresses, reason=UpdateFilterReason.UnusedAddressesCategorySet)
        )

    def reset_fee_rate(self) -> None:
        self.column_fee.fee_group.set_spin_fee_value(self.mempool_manager.get_prio_fee_rates()[TxPrio.low])

    def clear_ui(self) -> None:
        if not self.wallet:
            return
        with BlockChangesSignals([self.utxo_list]):
            self.additional_outpoints.clear()
            self.utxo_list.set_outpoints(self.get_outpoints())
            self.set_ui(TxUiInfos())
            self.reset_fee_rate()
            self.utxo_list.update_content()
        self.category_list.select_row_by_clipboard(
            self.wallet.labels.get_default_category(), scroll_to_last=True
        )
        self.on_input_changed_and_categories()

    def create_tx(self) -> None:
        if not self.wallet:
            return
        if (
            not self.column_inputs.checkBox_manual_coin_select.isChecked()
            and not self.category_list.get_selected_keys()
        ):
            Message(
                self.tr("Please select an input category on the left, that fits the transaction recipients.")
            )
            self.signals.wallet_signals[self.wallet.id].finished_psbt_creation.emit()
            return

        tx_ui_infos = self.get_tx_ui_infos()
        wallets = get_wallets(self.signals)

        # warn if multiple categories are combined
        category_dict = self.get_category_dict_of_addresses(
            [utxo.address for utxo in tx_ui_infos.utxo_dict.values()], wallets=wallets
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

        self.signal_create_tx.emit(tx_ui_infos)

    def update_fee_rate_to_mempool(self) -> None:
        "Do this only ONCE after the mempool data is fetched"
        if self.column_fee.fee_group.spin_fee_rate.value() == MIN_RELAY_FEE:
            self.reset_fee_rate()
        self.mempool_manager.signal_data_updated.disconnect(self.update_fee_rate_to_mempool)

    def get_outpoints(self) -> List[OutPoint]:
        if not self.wallet:
            return []
        return [utxo.outpoint for utxo in self.wallet.get_all_utxos()] + self.additional_outpoints

    def on_checkBox_opportunistic_coin_select(self):
        self.coin_selection_checkbox_state_change()

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
            self.utxo_list.select_rows(
                outpoints, self.utxo_list.key_column, role=MyItemDataRole.ROLE_KEY, scroll_to_last=True
            )

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
        fee_rate = self.wallet.get_ema_fee_rate() if self.wallet else MIN_RELAY_FEE

        if self.mempool_manager.get_prio_fee_rates()[TxPrio.high] >= 10 * MIN_RELAY_FEE:
            # assume, fee_rate = 5 sat/vb.
            # And the mempool is empty. Then enevn the high prio fee rate is 1 sat/vb.
            # the opportunistic_merging_threshold should remain at 5 sat/vB.
            #
            # However if we are in a high fee environment,
            # then the opportunistic_merging should only occur if we are <=  low prio fee rate
            fee_rate = min(fee_rate, self.mempool_manager.get_prio_fee_rates()[TxPrio.low])
        return fee_rate

    def _select_minimum_number_utxos_no_fee(
        self, utxos_for_input: UtxosForInputs, send_value: int
    ) -> UtxosForInputs:
        if utxos_for_input.spend_all_utxos or not utxos_for_input.utxos:
            return utxos_for_input

        utxo_values = np.array([utxo.txout.value for utxo in utxos_for_input.utxos])
        sort_filter: List[int] = (np.argsort(utxo_values)[::-1]).tolist()  # type: ignore

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
            fee_rate = self.column_fee.fee_group.spin_fee_rate.value()

        txinfos = self.get_tx_ui_infos()

        utxos_for_input = self._select_minimum_number_utxos_no_fee(
            UtxosForInputs(list(txinfos.utxo_dict.values()), spend_all_utxos=txinfos.spend_all_utxos),
            send_value=sum(sent_values),
        )

        num_inputs = max(1, len(utxos_for_input.utxos))  # assume all inputs come from this wallet
        fee_info = FeeInfo.estimate_from_num_inputs(
            fee_rate,
            input_mn_tuples=[
                self.wallet.get_mn_tuple() if self.wallet else (1, 1) for i in range(num_inputs)
            ],
            num_outputs=num_outputs,
        )
        return fee_info

    def get_tx_ui_infos(self, use_categories: bool | None = None) -> TxUiInfos:
        infos = TxUiInfos()
        if not self.wallet:
            return infos

        infos.replace_tx = self.replace_tx

        use_categories = (
            use_categories
            if isinstance(use_categories, bool)
            else bool(not self.column_inputs.checkBox_manual_coin_select.isChecked())
        )

        for recipient in self.recipients.recipients:
            infos.add_recipient(recipient)

        # logger.debug(
        #     f"set psbt builder fee_rate {self.column_fee.fee_group.spin_fee_rate.value()}"
        # )
        fee_rate = self.column_fee.fee_group.spin_fee_rate.value()
        infos.set_fee_rate(fee_rate)
        infos.opportunistic_merge_utxos = (
            self.column_inputs.checkBox_auto_opportunistic_coin_select.isChecked()
            and fee_rate <= self.opportunistic_merging_threshold()
        )

        wallets = [self.wallet] if use_categories else get_wallets(self.signals)

        if use_categories:
            ToolsTxUiInfo.fill_utxo_dict_from_categories(
                infos, [c.category for c in self.category_list.get_selected_category_infos()], wallets
            )

        if not use_categories:
            ToolsTxUiInfo.fill_txo_dict_from_outpoints(
                infos, self.utxo_list.get_selected_outpoints(), wallets
            )
            infos.spend_all_utxos = True

        infos.recipient_read_only = not self.recipients.allow_edit
        infos.utxos_read_only = not self.utxo_list.allow_edit or not self.column_inputs.isEnabled()
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
            if recipient_group_box.recipient_widget.send_max_checkbox.isChecked()
        ]
        total_change_amount = max(0, self.get_total_change_amount(include_max_checked=False) - fee_amount)
        for recipient_group_box in recipient_group_boxes_max_checked:
            self.set_max_amount(
                recipient_group_box, total_change_amount // len(recipient_group_boxes_max_checked)
            )

    def get_total_input_value(self) -> int:
        txinfos = self.get_tx_ui_infos()
        total_input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values() if utxo])
        return total_input_value

    def get_total_change_amount(self, include_max_checked=False) -> int:
        txinfos = self.get_tx_ui_infos()
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

    def set_max_amount(self, recipient_group_box: RecipientBox, max_amount: int) -> None:
        with BlockChangesSignals([recipient_group_box]):

            recipient_group_box.recipient_widget.amount = max_amount

    def coin_selection_checkbox_state_change(self) -> None:
        self.set_utxo_list_visible(bool(self.column_inputs.checkBox_manual_coin_select.isChecked()))

        tx_ui_infos = self.get_tx_ui_infos(use_categories=True)
        # only coin select if checkBox_reduce_future_fees
        # otherwise the suer wants to do it himself
        if (
            self.column_inputs.checkBox_manual_coin_select.isChecked()
            and tx_ui_infos.opportunistic_merge_utxos
        ):

            # take the coin selection from the category to the utxo tab (but only if one is selected)
            self.set_coin_selection_in_sent_tab(tx_ui_infos)
        else:
            self.clear_utxo_list_selection()

    def set_utxo_list_visible(self, value: bool):
        self.column_inputs.lower_widget_utxo_selection.setHidden(not value)
        if value:
            upper = self.category_list.sizeHint().height()
            self.column_inputs.v_splitter.setSizes([upper, max(upper, self.height() - upper)])

    def set_coin_selection_in_sent_tab(self, txinfos: TxUiInfos) -> None:
        if not self.wallet:
            return
        utxos_for_input = self.wallet.handle_opportunistic_merge_utxos(txinfos)

        utxo_names = [utxo.outpoint for utxo in utxos_for_input.utxos]
        self.utxo_list.select_rows(
            utxo_names, column=self.utxo_list.key_column, role=MyItemDataRole.ROLE_KEY, scroll_to_last=True
        )

    def handle_conflicting_utxo(self, txinfos: TxUiInfos) -> None:
        if not self.wallet:
            return
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
            txs_to_be_replaced: List[TransactionDetails] = []
            for utxo in conflicted_unconfirmed:
                if utxo.is_spent_by_txid:
                    txs_to_be_replaced += [
                        fulltx.tx
                        for fulltx in self.wallet.get_fulltxdetail_and_dependents(utxo.is_spent_by_txid)
                    ]

            fee_amount = sum([(_tx_details.fee or 0) for _tx_details in txs_to_be_replaced])

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
                assert txinfos.replace_tx, "No replace_tx available in bdk."
                replace_txid = txinfos.replace_tx.compute_txid()
                replace_tx_details, wallet = get_tx_details(txid=replace_txid, signals=self.signals)
                if not replace_tx_details:
                    logger.error(f"Could not get tx_details of {replace_txid=} for rbf")
                    return
                fee_info = FeeInfo.from_txdetails(replace_tx_details)

            if not fee_info:
                raise Exception("General RBF is currently not provided by bdk")

            min_rbf_fee_rate = calc_minimum_rbf_fee_info(
                fee_amount=fee_amount,
                new_tx_vsize=fee_info.vsize,
                mempool_manager=self.mempool_manager,
                fee_amount_is_estimated=False,
                vsize_is_estimated=fee_info.vsize_is_estimated,
            ).fee_rate()
            if not GENERAL_RBF_AVAILABLE:
                # the BumpFeeTxBuilder disallows the minimum rbf fee, and requires a slightly higer fee
                # the error message by BumpFeeTxBuilder is unfortunately completely wrong (and giving a >=2*minimum_rbf_fee_rate)
                min_rbf_fee_rate += 0.1

            txinfos.fee_rate = max(
                txinfos.fee_rate if txinfos.fee_rate is not None else MIN_RELAY_FEE, min_rbf_fee_rate
            )

            self.column_fee.fee_group.set_rbf_label(txinfos.fee_rate)
            self.column_fee.fee_group.set_fee_infos(fee_info=fee_info, tx_status=self.get_tx_status())

            self.add_outpoints([python_utxo.outpoint for python_utxo in txinfos.utxo_dict.values()])
        else:
            self.column_fee.fee_group.set_rbf_label(None)

    def handle_cpfp(self, txinfos: TxUiInfos) -> None:
        parent_txids = set()
        # only assume it can be cpfp if the utxos are selected --> spend_all_utxos=True
        if txinfos.spend_all_utxos:
            utxos = list(self.get_tx_ui_infos().utxo_dict.values())
            parent_txids = set(utxo.outpoint.txid for utxo in utxos)

        self.set_fee_group_cpfp_label(
            parent_txids=parent_txids,
            this_fee_info=self.estimate_fee_info(),
            fee_group=self.column_fee.fee_group,
            chain_position=None,
        )

    def set_ui(self, tx_ui_infos: TxUiInfos) -> None:
        self.handle_conflicting_utxo(txinfos=tx_ui_infos)
        self.handle_cpfp(tx_ui_infos)

        if tx_ui_infos.fee_rate:
            self.column_fee.fee_group.set_spin_fee_value(tx_ui_infos.fee_rate)

        # do first tab_changed, because it will set the utxo_list.select_rows
        if tx_ui_infos.hide_UTXO_selection is not None:
            self.column_inputs.checkBox_manual_coin_select.setChecked(not tx_ui_infos.hide_UTXO_selection)

        self.utxo_list.update_content()
        if tx_ui_infos.utxo_dict:
            # first select the correct categories

            categories: Set[str] = set()
            if self.wallet:
                for utxo in tx_ui_infos.utxo_dict.keys():
                    categories = categories.union(self.wallet.get_categories_for_txid(utxo.txid))
            self.category_list.select_rows(
                categories,
                column=self.category_list.key_column,
                role=MyItemDataRole.ROLE_CLIPBOARD_DATA,
                scroll_to_last=True,
            )

            # this if statement prevents empty selection on startup, when restoreing the
            # old tx_ui_infos  (which doesnt contain utxo_dict)
            self.utxo_list.select_rows(
                tx_ui_infos.utxo_dict.keys(),
                self.utxo_list.key_column,
                role=MyItemDataRole.ROLE_KEY,
                scroll_to_last=True,
            )

        if tx_ui_infos.hide_UTXO_selection:
            self.splitter.setSizes([0, 1, 1])

        # do the recipients after the utxo list setting. otherwise setting the uxtos,
        # will reduce the sent amount to what is maximally possible, by the selected utxos
        self.recipients.set_allow_edit(not tx_ui_infos.recipient_read_only)
        self.recipients.recipients = tx_ui_infos.recipients
        if not self.recipients.recipients:
            self.recipients.add_recipient()

        self.utxo_list.set_allow_edit(not tx_ui_infos.utxos_read_only)
        self.column_inputs.setEnabled(not tx_ui_infos.utxos_read_only)
        self.replace_tx = tx_ui_infos.replace_tx

    def close(self):
        self.signal_tracker.disconnect_all()
        self._signal_tracker_wallet_signals.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)

        self.category_list.close()
        self.utxo_list_with_toolbar.close()
        self.setParent(None)
        return super().close()
