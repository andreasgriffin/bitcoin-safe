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
from typing import List, Optional

import bdkpython as bdk
from bitcoin_tools.gui.qt.satoshis import Satoshis, format_fee_rate, unit_fee_str
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.html_utils import html_f, link
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import TransactionDetails
from bitcoin_safe.typestubs import TypedPyQtSignal
from bitcoin_safe.wallet import TxConfirmationStatus

from ...config import FEE_RATIO_HIGH_WARNING, NO_FEE_WARNING_BELOW, UserConfig
from ...mempool import MempoolData, TxPrio
from .block_buttons import (
    BaseBlock,
    ConfirmedBlock,
    MempoolButtons,
    MempoolProjectedBlock,
)
from .util import adjust_bg_color_for_darkmode

logger = logging.getLogger(__name__)


class FeeRateWarningBar(NotificationBar):
    def __init__(self, network: bdk.Network) -> None:
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

    def setText(self, value: Optional[str]):
        self.textLabel.setText(value if value else "")

    def update_fee_rate_warning(
        self,
        fee_rate: float | None,
        max_reasonable_fee_rate: float,
        confirmation_status: TxConfirmationStatus,
    ) -> None:
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
    def __init__(self, network: bdk.Network) -> None:
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=False,
        )
        self.network = network
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("#FFDF00")))
        self.set_icon(svg_tools.get_QIcon("warning.svg"))

        self.optionalButton.setVisible(False)

        self.setVisible(False)

    def setText(self, value: Optional[str]):
        self.textLabel.setText(value if value else "")

    def set_fee_to_send_ratio(
        self,
        fee_info: FeeInfo | None,
        total_non_change_output_amount: int,
        network: bdk.Network,
        chain_position: bdk.ChainPosition | None,
        force_show_fee_warning_on_0_amont=False,
    ) -> None:
        if not fee_info:
            self.setVisible(False)
            return

        if total_non_change_output_amount <= 0:
            # the == 0 case is relevant
            self.setVisible(force_show_fee_warning_on_0_amont)
            title = self.tr("{sent} is sent!").format(
                sent=Satoshis(total_non_change_output_amount, network=network).str_with_unit()
            )
            description = html_f(
                self.tr("The transaction fee is:\n{fee}, and {sent} is sent!").format(
                    fee=Satoshis(fee_info.fee_amount, network).str_with_unit(),
                    sent=Satoshis(total_non_change_output_amount, network=network).str_with_unit(),
                ),
                add_html_and_body=True,
            )
            self.setText(title + " " + description)
            return

        too_high = fee_info.fee_amount / total_non_change_output_amount > FEE_RATIO_HIGH_WARNING
        self.setVisible(too_high and (not chain_position or not chain_position.is_confirmed()))
        if too_high:
            s = (
                self.tr(
                    "The estimated transaction fee is:\n{fee}, which is {percent}% of\nthe sending value {sent}"
                )
                if fee_info.is_estimated
                else self.tr(
                    "The transaction fee is:\n{fee}, which is {percent}% of\nthe sending value {sent}"
                )
            )
            description = s.format(
                fee=Satoshis(fee_info.fee_amount, network).str_with_unit(),
                percent=round(fee_info.fee_amount / total_non_change_output_amount * 100),
                sent=Satoshis(total_non_change_output_amount, self.network).str_with_unit(),
            )
            title = html_f(
                self.tr("High fee ratio: {ratio}%.").format(
                    ratio=round(fee_info.fee_amount / total_non_change_output_amount * 100)
                ),
                bf=True,
            )

            self.setText(title + " " + description)


class FeeGroup(QObject):
    signal_fee_rate_change: TypedPyQtSignal[float] = pyqtSignal(float)  # type: ignore

    def __init__(
        self,
        mempool_data: MempoolData,
        fx: FX,
        config: UserConfig,
        fee_info: FeeInfo | None = None,
        allow_edit=True,
        is_viewer=False,
        chain_position: bdk.ChainPosition | None = None,
        url: str | None = None,
        fee_rate: float | None = None,
        decimal_precision: int = 1,
        enable_approximate_fee_label: bool = True,
    ) -> None:
        super().__init__()
        self.is_viewer = is_viewer
        self.fx = fx
        self.allow_edit = allow_edit
        self.config = config
        self.fee_info = fee_info
        self.enable_approximate_fee_label = enable_approximate_fee_label

        fee_rate = fee_rate if fee_rate else (mempool_data.get_prio_fee_rates()[TxPrio.low])

        # add the groupBox_Fee
        self.groupBox_Fee = QGroupBox()
        self.groupBox_Fee_layout = QVBoxLayout(self.groupBox_Fee)
        self.groupBox_Fee.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)
        self.groupBox_Fee.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.groupBox_Fee_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        current_margins = self.groupBox_Fee_layout.contentsMargins()
        self.groupBox_Fee_layout.setContentsMargins(
            0, 0, 0, current_margins.bottom()
        )  # Left, Top, Right, Bottom margins

        self._confirmed_block = ConfirmedBlock(
            mempool_data=mempool_data,
            url=url,
            chain_position=chain_position,
            fee_rate=fee_rate,
        )
        self._mempool_projected_block = MempoolProjectedBlock(
            mempool_data=mempool_data, config=self.config, fee_rate=fee_rate
        )
        self._mempool_buttons = MempoolButtons(
            fee_rate=fee_rate,
            mempool_data=mempool_data,
            max_button_count=5,
            decimal_precision=decimal_precision,
        )

        self._all_mempool_buttons: List[BaseBlock] = [
            self._confirmed_block,
            self._mempool_projected_block,
            self._mempool_buttons,
        ]
        for button_group in self._all_mempool_buttons:
            self.groupBox_Fee_layout.addWidget(button_group, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.set_mempool_visibility()

        self.approximate_fee_label = QLabel()
        self.approximate_fee_label.setVisible(False)
        self.groupBox_Fee_layout.addWidget(
            self.approximate_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.rbf_fee_label = QLabel()
        self.rbf_fee_label.setWordWrap(True)
        self.rbf_fee_label.setHidden(True)
        self.groupBox_Fee_layout.addWidget(self.rbf_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.cpfp_fee_label = QLabel()
        self.cpfp_fee_label.setWordWrap(True)
        self.cpfp_fee_label.setHidden(True)
        self.groupBox_Fee_layout.addWidget(self.cpfp_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.widget_around_spin_box = QWidget()
        self.widget_around_spin_box_layout = QVBoxLayout(self.widget_around_spin_box)
        self.widget_around_spin_box_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        self.groupBox_Fee_layout.addWidget(
            self.widget_around_spin_box, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.spin_fee_rate = QDoubleSpinBox()
        self.spin_fee_rate.setReadOnly(not allow_edit)
        self.spin_fee_rate.setSingleStep(1)  # Set the step size
        self.spin_fee_rate.setDecimals(decimal_precision)  # Set the number of decimal places
        # self.spin_fee_rate.setMaximumWidth(55)
        if fee_rate:
            self.set_spin_fee_value(fee_rate)
        self.update_spin_fee_range()

        self.widget_around_spin_box_layout.addWidget(
            self.spin_fee_rate, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.spin_label = QLabel()
        self.spin_label.setText(unit_fee_str(self.config.network))
        self.widget_around_spin_box_layout.addWidget(self.spin_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.fee_amount_label = QLabel()
        self.fee_amount_label.setHidden(True)
        self.fee_amount_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.groupBox_Fee_layout.addWidget(self.fee_amount_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.fiat_fee_label = QLabel()
        self.fiat_fee_label.setHidden(True)
        self.fiat_fee_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.groupBox_Fee_layout.addWidget(self.fiat_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.fx.signal_data_updated.connect(self.updateUi)

        self.label_block_number = QLabel()
        self.label_block_number.setHidden(True)
        self.groupBox_Fee_layout.addWidget(self.label_block_number, alignment=Qt.AlignmentFlag.AlignHCenter)

        # signals
        if allow_edit:
            self.visible_mempool_buttons.signal_click.connect(self.on_mempool_button_clicked)
        self.spin_fee_rate.valueChanged.connect(self.signal_fee_rate_change.emit)
        self.visible_mempool_buttons.mempool_data.signal_data_updated.connect(self.updateUi)

        # refresh
        self.updateUi()

    def on_mempool_button_clicked(self, fee_rate: float):
        self.set_spin_fee_value(fee_rate=fee_rate)

    def set_spin_fee_value(self, fee_rate: float):
        if self.spin_fee_rate.value() == round(fee_rate, self.spin_fee_rate.decimals()):
            return
        self._cached_spin_fee_rate = fee_rate
        self.update_spin_fee_range(fee_rate)
        self.spin_fee_rate.setValue(fee_rate)

    def set_confirmation_time(self, chain_position: bdk.ChainPosition | None = None):
        self._confirmed_block.chain_position = chain_position
        self.set_mempool_visibility()

    def set_mempool_visibility(self):
        self.visible_mempool_buttons: BaseBlock

        if self._confirmed_block.chain_position and self._confirmed_block.chain_position.is_confirmed():
            self.visible_mempool_buttons = self._confirmed_block
        elif self.is_viewer:
            self.visible_mempool_buttons = self._mempool_projected_block
        else:
            self.visible_mempool_buttons = self._mempool_buttons

        for mempool_buttons in self._all_mempool_buttons:
            mempool_buttons.setVisible(self.visible_mempool_buttons == mempool_buttons)

    def updateUi(self) -> None:
        self.groupBox_Fee.setTitle(self.tr("Fee"))
        self.rbf_fee_label.setText(
            html_f(self.tr("... is the minimum to replace the existing transactions."), bf=True)
        )
        self.approximate_fee_label.setText(html_f(self.tr("Approximate fee rate"), bf=True))

        # only in editor mode
        self.label_block_number.setHidden(True)
        if self.spin_fee_rate.value():
            self.label_block_number.setText(
                self.tr("in ~{n}. Block").format(
                    n=self.visible_mempool_buttons.mempool_data.fee_rate_to_projected_block_index(
                        self.spin_fee_rate.value()
                    )
                    + 1
                )
            )

        self.approximate_fee_label.setVisible(
            self.enable_approximate_fee_label and (self.fee_info.is_estimated if self.fee_info else False)
        )
        if self.fee_info:
            self.approximate_fee_label.setToolTip(
                f'<html><body>The {"approximate " if   self.fee_info.is_estimated else "" }fee is {Satoshis( self.fee_info.fee_amount  , self.config.network).str_with_unit()}</body></html>'
            )

        self.set_fiat_fee_label()
        self.set_fee_amount_label()
        self.visible_mempool_buttons.refresh(fee_rate=self.spin_fee_rate.value())

    def set_fiat_fee_label(self) -> None:
        self.fiat_fee_label.setHidden(self.fee_info is None)
        if self.fee_info is None:
            return

        fee = self.fee_info.vsize * self.spin_fee_rate.value()
        dollar_amount = self.fx.to_fiat("usd", int(fee))
        if dollar_amount is None:
            self.fiat_fee_label.setHidden(True)
            return

        dollar_text = self.fx.format_dollar(dollar_amount)
        if dollar_amount > 100:
            # make red when dollar amount high
            dollar_text = html_f(dollar_text, bf=True, color="red")
        self.fiat_fee_label.setText(dollar_text)

    def set_rbf_label(self, min_fee_rate: Optional[float]) -> None:
        self.rbf_fee_label.setVisible(bool(min_fee_rate))
        if min_fee_rate:
            self.rbf_fee_label.setText(
                (
                    self.tr("{rate} is the minimum for {rbf}").format(
                        rate=format_fee_rate(min_fee_rate, self.config.network),
                        rbf=link("https://github.com/bitcoin/bips/blob/master/bip-0125.mediawiki", "RBF"),
                    )
                )
            )
            self.rbf_fee_label.setTextFormat(Qt.TextFormat.RichText)
            self.rbf_fee_label.setOpenExternalLinks(True)  # Enable opening links

    def combined_fee_info(self, txs: List[TransactionDetails]) -> FeeInfo:
        combined_info = FeeInfo(fee_amount=0, vsize=0, is_estimated=False)
        if not txs:
            return combined_info
        for tx in txs:
            info = FeeInfo.from_txdetails(tx)
            if info:
                combined_info += info
        return combined_info

    def set_cpfp_label(
        self, unconfirmed_ancestors: List[TransactionDetails] | None, this_fee_info: FeeInfo
    ) -> None:

        self.cpfp_fee_label.setVisible(bool(unconfirmed_ancestors))
        if not unconfirmed_ancestors:
            return

        unconfirmed_parents_fee_info = self.combined_fee_info(txs=unconfirmed_ancestors)
        if not unconfirmed_parents_fee_info:
            self.cpfp_fee_label.setVisible(False)
            return

        combined_fee_info = this_fee_info + unconfirmed_parents_fee_info

        self.cpfp_fee_label.setText(
            (
                self.tr("{rate} combined fee rate").format(
                    rate=format_fee_rate(combined_fee_info.fee_rate(), self.config.network),
                )
            )
        )
        self.cpfp_fee_label.setToolTip(
            self.tr(
                "This transaction has {number} unconfirmed parents with a combined fee rate of {parents_fee_rate}"
            ).format(
                parents_fee_rate=format_fee_rate(
                    unconfirmed_parents_fee_info.fee_rate(), network=self.config.network
                ),
                number=len(unconfirmed_ancestors or []),
            )
        )
        self.cpfp_fee_label.setTextFormat(Qt.TextFormat.RichText)
        self.cpfp_fee_label.setOpenExternalLinks(True)  # Enable opening links

    def set_fee_info(self, fee_info: FeeInfo | None):
        self.fee_info = fee_info

        if not fee_info:
            return

        decimal_precision = self.spin_fee_rate.decimals()
        if round(self.spin_fee_rate.value(), decimal_precision) != round(
            fee_info.fee_rate(), decimal_precision
        ):
            logger.error(
                f"Aborting to set a fee info {fee_info.fee_rate()} that is inconsistent with the fee_rate {self.spin_fee_rate.value()}"
            )
            return

        self.updateUi()

    def set_fee_infos(
        self,
        fee_info: FeeInfo,
        chain_position: bdk.ChainPosition | None,
        url: str | None = None,
        chain_height: int | None = None,
    ) -> None:
        # this has to be done first, because it will trigger signals
        # that will also set self.fee_amount from the spin edit
        fee_rate = fee_info.fee_rate()
        self.set_spin_fee_value(fee_rate)
        self.set_confirmation_time(chain_position)
        self.spin_fee_rate.setHidden(fee_rate is None)
        self.spin_label.setHidden(fee_rate is None)

        self.visible_mempool_buttons.refresh(
            fee_rate=fee_rate,
            chain_position=chain_position,
            chain_height=chain_height,
        )

        if url:
            self.visible_mempool_buttons.set_url(url)

        self.set_fee_info(fee_info)

    def set_fee_amount_label(self):
        self.fee_amount_label.setHidden(self.fee_info is None)
        if self.fee_info is None:
            return

        fee = self.fee_info.fee_amount
        self.fee_amount_label.setText(Satoshis(int(fee), self.config.network).str_with_unit())

    def update_spin_fee_range(self, value: float = 0) -> None:
        fee_range = self.config.fee_ranges[self.config.network].copy()
        fee_range[1] = max(
            fee_range[1],
            value,
            self.spin_fee_rate.value(),
            max(self.visible_mempool_buttons.mempool_data.fee_rates_min_max(0)),
        )
        self.spin_fee_rate.setRange(*fee_range)
