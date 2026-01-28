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

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import (
    Satoshis,
    format_fee_rate,
    format_fee_rate_splitted,
    unit_fee_str,
)
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.ui_tx.form_container import GridFormLayout
from bitcoin_safe.gui.qt.ui_tx.spinbox import FeerateSpinBox
from bitcoin_safe.gui.qt.ui_tx.totals_box import TotalsBox
from bitcoin_safe.gui.qt.ui_tx.util import get_cpfp_label, get_rbf_fee_label
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.html_utils import html_f, link
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import TransactionDetails
from bitcoin_safe.signals import WalletFunctions
from bitcoin_safe.wallet import TxConfirmationStatus, TxStatus

from ....config import FEE_RATIO_HIGH_WARNING, NO_FEE_WARNING_BELOW, UserConfig
from ....mempool_manager import MempoolManager, TxPrio
from ..icon_label import IconLabel
from ..util import (
    adjust_bg_color_for_darkmode,
    block_explorer_URL,
    open_website,
    set_margins,
    set_no_margins,
)
from .mempool_buttons import MempoolButtons, SmallTitleLabel

logger = logging.getLogger(__name__)

DOLLAR_FEE_MARK_RED = 100
BTC_FEE_MARK_RED = 100_000


class FeeRateWarningBar(NotificationBar):
    def __init__(self, network: bdk.Network) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=False,
        )
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("#FFDF00")))
        self.set_icon(svg_tools.get_QIcon("warning.svg"))
        self.network = network

        self.optionalButton.setVisible(False)

        self.setVisible(False)

    def setText(self, value: str | None):
        """SetText."""
        self.icon_label.setText(value if value else "")

    def update_fee_rate_warning(
        self,
        fee_rate: float | None,
        max_reasonable_fee_rate: float,
        confirmation_status: TxConfirmationStatus,
    ) -> None:
        """Update fee rate warning."""
        if (fee_rate is None) or (confirmation_status != TxConfirmationStatus.LOCAL):
            self.setVisible(False)
            return
        too_high = fee_rate > max_reasonable_fee_rate
        if fee_rate <= NO_FEE_WARNING_BELOW:
            too_high = False

        self.setVisible(too_high)
        if too_high:
            title = html_f(self.tr("High fee rate!"), bf=True)
            description = self.tr("The high priority mempool fee rate is {rate}").format(
                rate=format_fee_rate(
                    max_reasonable_fee_rate,
                    self.network,
                )
            )
            self.setText(title + " " + description)


class FeeWarningBar(NotificationBar):
    def __init__(self, network: bdk.Network, btc_symbol: str) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=False,
        )
        self.network = network
        self.btc_symbol = btc_symbol
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("#FFDF00")))
        self.set_icon(svg_tools.get_QIcon("warning.svg"))

        self.optionalButton.setVisible(False)

        self.setVisible(False)

    def setText(self, value: str | None):
        """SetText."""
        self.icon_label.setText(value if value else "")

    def set_fee_to_send_ratio(
        self,
        fee_info: FeeInfo | None,
        total_non_change_output_amount: int,
        network: bdk.Network,
        tx_status: TxStatus,
        force_show_fee_warning_on_0_amont=False,
    ) -> None:
        """Set fee to send ratio."""
        if not fee_info:
            self.setVisible(False)
            return

        if total_non_change_output_amount <= 0:
            # the == 0 case is relevant
            self.setVisible(force_show_fee_warning_on_0_amont)
            title = self.tr("{sent} is sent!").format(
                sent=Satoshis(total_non_change_output_amount, network=network).str_with_unit(
                    btc_symbol=self.btc_symbol
                )
            )
            description = html_f(
                self.tr("The transaction fee is:\n{fee}, and {sent} is sent!").format(
                    fee=Satoshis(fee_info.fee_amount, network).str_with_unit(btc_symbol=self.btc_symbol),
                    sent=Satoshis(total_non_change_output_amount, network=network).str_with_unit(
                        btc_symbol=self.btc_symbol
                    ),
                ),
                add_html_and_body=True,
            )
            self.setText(title + " " + description)
            return

        too_high = fee_info.fee_amount / total_non_change_output_amount > FEE_RATIO_HIGH_WARNING
        self.setVisible(
            too_high and (not tx_status.chain_position or not tx_status.chain_position.is_confirmed())
        )
        if too_high:
            s = (
                self.tr(
                    "The estimated transaction fee is: {fee}, which is {percent}% of the sending value {sent}"
                )
                if fee_info.fee_amount_is_estimated
                else self.tr("The transaction fee is: {fee}, which is {percent}% of the sending value {sent}")
            )
            description = s.format(
                fee=Satoshis(fee_info.fee_amount, network).str_with_unit(btc_symbol=self.btc_symbol),
                percent=round(fee_info.fee_amount / total_non_change_output_amount * 100),
                sent=Satoshis(total_non_change_output_amount, self.network).str_with_unit(
                    btc_symbol=self.btc_symbol
                ),
            )
            title = html_f(
                self.tr("High fee ratio: {ratio}%.").format(
                    ratio=round(fee_info.fee_amount / total_non_change_output_amount * 100)
                ),
                bf=True,
            )

            self.setText(title + " " + description)


class FeeGroup(QObject):
    signal_fee_rate_change = cast(SignalProtocol[[float]], pyqtSignal(float))

    def __init__(
        self,
        mempool_manager: MempoolManager,
        fx: FX,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        tx_status: TxStatus,
        fee_info: FeeInfo | None = None,
        allow_edit=True,
        is_viewer=False,
        fee_rate: float | None = None,
        decimal_precision: int = 1,
        enable_approximate_fee_label: bool = True,
        totals_box: TotalsBox | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.is_viewer = is_viewer
        self.fx = fx
        self.allow_edit = allow_edit
        self.config = config
        self.fee_info = fee_info
        self.enable_approximate_fee_label = enable_approximate_fee_label

        fee_rate = fee_rate if fee_rate else (mempool_manager.get_prio_fee_rates()[TxPrio.low])

        # add the groupBox_Fee
        self.groupBox_Fee = QGroupBox()
        self.groupBox_Fee_layout = QVBoxLayout(self.groupBox_Fee)
        self.groupBox_Fee.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.groupBox_Fee_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        set_margins(
            self.groupBox_Fee_layout,
            {
                Qt.Edge.TopEdge: 0,
            },
        )

        self.mempool_buttons = MempoolButtons(
            fee_rate=fee_rate,
            mempool_manager=mempool_manager,
            max_button_count=1 if tx_status.is_confirmed() else 4,
            decimal_precision=decimal_precision,
            tx_status=tx_status,
            wallet_functions=wallet_functions,
        )
        self.groupBox_Fee_layout.addWidget(self.mempool_buttons, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.form_widget = QWidget()
        self.form = GridFormLayout(self.form_widget)
        set_no_margins(self.form)
        self.groupBox_Fee_layout.addWidget(self.form_widget, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.rbf_fee_label = IconLabel()
        self.rbf_fee_label.textLabel.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.rbf_fee_label_currency = QLabel()
        self.rbf_fee_label.textLabel.setWordWrap(True)
        self.form.addRow(self.rbf_fee_label, self.rbf_fee_label_currency)

        self.cpfp_fee_label = IconLabel()
        self.cpfp_fee_label_currency = QLabel()
        self.cpfp_fee_label.textLabel.setWordWrap(True)
        self.cpfp_fee_label.textLabel.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.form.addRow(self.cpfp_fee_label, self.cpfp_fee_label_currency)

        self.form.set_row_visibility_of_widget(self.rbf_fee_label, visible=False)
        self.form.set_row_visibility_of_widget(self.cpfp_fee_label, visible=False)

        self.fee_rate_label = SmallTitleLabel()
        self.form.addWidget(
            self.fee_rate_label, self.form.count(), 0, 1, 2, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        self.approximate_fee_label = QLabel()
        self.form.addWidget(
            self.approximate_fee_label, self.form.count(), 0, 1, 2, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.spin_fee_rate = FeerateSpinBox(
            signal_currency_changed=wallet_functions.signals.currency_switch,
            signal_language_switch=wallet_functions.signals.language_switch,
        )
        self.spin_fee_rate.setReadOnly(not allow_edit)
        self.spin_fee_rate.setDecimals(decimal_precision)  # Set the number of decimal places
        if fee_rate is not None:
            self.set_spin_fee_value(fee_rate)
        self.update_spin_fee_range()

        self.spin_label = QLabel()
        self.spin_label.setText(unit_fee_str(self.config.network))
        self.form.addRow(
            self.spin_fee_rate,
            self.spin_label,
            label_alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignHCenter,
            field_alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignHCenter,
        )

        self.totals_box = totals_box if totals_box else TotalsBox(network=config.network, fx=fx)
        self.totals_box.c0.setHidden(True)
        self.totals_box.c1.setHidden(True)
        self.totals_box.c2.mark_fiat_red_when_exceeding = DOLLAR_FEE_MARK_RED
        if not totals_box:
            self.groupBox_Fee_layout.addWidget(self.totals_box, alignment=Qt.AlignmentFlag.AlignRight)
        self.fx.signal_data_updated.connect(self.updateUi)

        self.label_block_number = QLabel()
        self.label_block_number.setHidden(True)
        self.groupBox_Fee_layout.addWidget(self.label_block_number, alignment=Qt.AlignmentFlag.AlignHCenter)

        # signals
        if allow_edit:
            self.mempool_buttons.signal_click_median_fee.connect(self.on_mempool_button_clicked)
        self.spin_fee_rate.valueChanged.connect(self._on_spin_fee_rate_valueChanged)
        self.mempool_buttons.mempool_manager.signal_data_updated.connect(self.updateUi)

        # refresh
        self.updateUi()

        # signals
        wallet_functions.signals.currency_switch.connect(self.on_currency_switch)

        self.mempool_buttons.signal_explorer_explorer_icon.connect(self._on_explorer_explorer_icon)

    def _on_spin_fee_rate_valueChanged(self, value: float):
        """On spin fee rate valueChanged."""
        self.signal_fee_rate_change.emit(value)

    def _on_explorer_explorer_icon(self, index: int) -> None:
        """On explorer explorer icon."""
        if self.mempool_buttons.tx_status.is_confirmed():
            tx = self.mempool_buttons.tx_status.tx
            if tx:
                url = block_explorer_URL(
                    self.config.network_config.mempool_url,
                    kind="tx",
                    item=str(tx.compute_txid()),
                )
            else:
                url = block_explorer_URL(self.config.network_config.mempool_url, kind="block", item=index)
        else:
            url = block_explorer_URL(self.config.network_config.mempool_url, kind="mempool", item=index)
        if url:
            open_website(url)

    def on_currency_switch(self):
        """On currency switch."""
        btc = self.fx.fiat_to_btc(DOLLAR_FEE_MARK_RED, currency="USD") or BTC_FEE_MARK_RED
        self.totals_box.c2.mark_fiat_red_when_exceeding = self.fx.btc_to_fiat(btc) or DOLLAR_FEE_MARK_RED

    def on_mempool_button_clicked(self, index: int):
        """On mempool button clicked."""
        self.set_spin_fee_value(
            fee_rate=self.mempool_buttons.mempool_manager.median_block_fee_rate(
                index, decimal_precision=self.mempool_buttons.decimal_precision
            )
        )

    def set_spin_fee_value(self, fee_rate: float):
        """Set spin fee value."""
        if self.spin_fee_rate.value() == round(fee_rate, self.spin_fee_rate.decimals()):
            return
        self._cached_spin_fee_rate = fee_rate
        self.update_spin_fee_range(fee_rate)
        self.spin_fee_rate.setValue(fee_rate)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.fee_rate_label.setText(self.tr("Transaction fee rate"))
        self.approximate_fee_label.setText(html_f(self.tr("Approximate rate"), bf=True))

        # only in editor mode
        self.label_block_number.setHidden(True)
        if self.spin_fee_rate.value():
            self.label_block_number.setText(
                self.tr("in ~{n}. Block").format(
                    n=self.mempool_buttons.mempool_manager.fee_rate_to_projected_block_index(
                        self.spin_fee_rate.value()
                    )
                    + 1
                )
            )

        show_approximate_fee_label = self.enable_approximate_fee_label and (
            self.fee_info.fee_rate_is_estimated() if self.fee_info else False
        )
        self.form.set_row_visibility_of_widget(
            self.approximate_fee_label,
            show_approximate_fee_label,
        )
        self.form.set_row_visibility_of_widget(
            self.fee_rate_label,
            bool((not show_approximate_fee_label) and self.fee_info),
        )

        self.approximate_fee_label.setToolTip(
            self.tr(
                "The fee rate cannot be known exactly,\nsince the final size of the transaction is unknown."
            )
        )

        self.set_fee_amount_label()
        self.mempool_buttons.refresh(fee_rate=self.spin_fee_rate.value())

    def set_rbf_label(
        self, current_fee: FeeInfo | None, min_fee_rate: float | None, conflicing_txids: set[str]
    ) -> None:
        """Set rbf label."""
        self.form.set_row_visibility_of_widget(self.rbf_fee_label, bool(min_fee_rate))
        if min_fee_rate:
            fee_rate, unit = format_fee_rate_splitted(fee_rate=min_fee_rate, network=self.config.network)

            url, tooltip = get_rbf_fee_label(
                current_fee=current_fee,
                min_fee_rate=min_fee_rate,
                network=self.config.network,
                conflicing_txids=conflicing_txids,
            )

            self.rbf_fee_label.setText(
                self.tr("{rbf} min: {rate}").format(
                    rate=fee_rate,
                    rbf=link(url, "RBF"),
                )
            )
            self.rbf_fee_label.set_icon_as_help(tooltip, click_url=url)

            self.rbf_fee_label_currency.setText(unit)

    def set_cpfp_label(
        self,
        this_fee_info: FeeInfo,
        unconfirmed_parents_fee_info: FeeInfo | None,
        unconfirmed_ancestors: dict[str, TransactionDetails],
    ) -> None:
        """Set cpfp label."""

        if not this_fee_info or not unconfirmed_parents_fee_info:
            self.form.set_row_visibility_of_widget(self.cpfp_fee_label, False)
            return

        combined_fee_info = this_fee_info + unconfirmed_parents_fee_info

        help_url, tooltip = get_cpfp_label(
            unconfirmed_parents_fee_info=unconfirmed_parents_fee_info,
            combined_fee_info=combined_fee_info,
            unconfirmed_ancestors=unconfirmed_ancestors,
            network=self.config.network,
        )

        cpfp_total_rate, unit = format_fee_rate_splitted(combined_fee_info.fee_rate(), self.config.network)

        self.form.set_row_visibility_of_widget(self.cpfp_fee_label, cpfp_total_rate is not None)

        self.cpfp_fee_label.setText(
            self.tr("{cpfp} total: {rate}").format(rate=cpfp_total_rate, cpfp=link(help_url, "CPFP"))
        )
        self.cpfp_fee_label_currency.setText(unit)
        self.cpfp_fee_label.set_icon_as_help(tooltip=tooltip, click_url=help_url)

    def set_fee_info(self, fee_info: FeeInfo | None):
        """Set fee info."""
        self.fee_info = fee_info

        if not fee_info:
            self.updateUi()
            return

        decimal_precision = self.spin_fee_rate.decimals()
        if round(self.spin_fee_rate.value(), decimal_precision) != round(
            fee_info.fee_rate(), decimal_precision
        ):
            logger.error(
                f"Aborting to set a fee info {fee_info.fee_rate()} that is "
                f"inconsistent with the fee_rate {self.spin_fee_rate.value()}"
            )
            return

        self.updateUi()

    def set_fee_infos(
        self,
        fee_info: FeeInfo | None,
        tx_status: TxStatus,
        can_rbf_safely: bool,
    ) -> None:
        # this has to be done first, because it will trigger signals
        # that will also set self.fee_amount from the spin edit
        """Set fee infos."""
        fee_rate = fee_info.fee_rate() if fee_info else None
        if fee_rate is not None:
            self.set_spin_fee_value(fee_rate)
        self.spin_fee_rate.setHidden(fee_rate is None)
        self.spin_label.setHidden(fee_rate is None)

        self.mempool_buttons.refresh(fee_rate=fee_rate, tx_status=tx_status, can_rbf_safely=can_rbf_safely)

        self.set_fee_info(fee_info)

    def set_fee_amount_label(self):
        """Set fee amount label."""
        amount = self.fee_info.fee_amount if self.fee_info is not None else None
        self.totals_box.c2.set_amount(amount=amount)

    def update_spin_fee_range(self, value: float = 0) -> None:
        """Update spin fee range."""
        fee_range = self.config.fee_ranges[self.config.network].copy()
        fee_range[1] = max(
            fee_range[1],
            value,
            self.spin_fee_rate.value(),
            max(self.mempool_buttons.mempool_manager.fee_rates_min_max(0)),
        )
        self.spin_fee_rate.setRange(*fee_range)
