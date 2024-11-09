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

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.util import icon_path
from bitcoin_safe.html_utils import html_f, link
from bitcoin_safe.psbt_util import FeeInfo

from ...config import FEE_RATIO_HIGH_WARNING, NO_FEE_WARNING_BELOW, UserConfig

logger = logging.getLogger(__name__)

from typing import Optional

import bdkpython as bdk
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...mempool import MempoolData, TxPrio
from ...signals import pyqtSignal
from ...util import Satoshis, format_fee_rate, unit_fee_str
from .block_buttons import (
    BaseBlock,
    ConfirmedBlock,
    MempoolButtons,
    MempoolProjectedBlock,
)


class FeeWarningBar(NotificationBar):
    def __init__(self) -> None:
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=False,
        )
        self.set_background_color("#FFDF00")
        self.set_icon(QIcon(icon_path("warning.png")))

        self.optionalButton.setVisible(False)

        self.setVisible(False)

    def setText(self, value: Optional[str]):
        self.textLabel.setText(value if value else "")


class FeeGroup(QObject):
    signal_set_fee_rate = pyqtSignal(float)

    def __init__(
        self,
        mempool_data: MempoolData,
        fx: FX,
        config: UserConfig,
        fee_info: FeeInfo | None = None,
        allow_edit=True,
        is_viewer=False,
        confirmation_time: bdk.BlockTime | None = None,
        url: str | None = None,
        fee_rate: float | None = None,
    ) -> None:
        super().__init__()

        self.fx = fx
        self.allow_edit = allow_edit
        self.config = config
        self.fee_info = fee_info

        fee_rate = fee_rate if fee_rate else (mempool_data.get_prio_fee_rates()[TxPrio.low])

        # add the groupBox_Fee
        self.groupBox_Fee = QGroupBox()
        self.groupBox_Fee_layout = QVBoxLayout(self.groupBox_Fee)
        self.groupBox_Fee.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)
        self.groupBox_Fee.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.groupBox_Fee_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.groupBox_Fee_layout.setContentsMargins(0, 0, 0, 0)

        self._confirmed_block = None
        self._mempool_projected_block = None
        self._mempool_buttons = None

        self.high_fee_rate_warning_label = FeeWarningBar()
        self.high_fee_rate_warning_label.setHidden(True)
        self.groupBox_Fee_layout.addWidget(
            self.high_fee_rate_warning_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.high_fee_warning_label = FeeWarningBar()
        self.high_fee_warning_label.setHidden(True)
        self.groupBox_Fee_layout.addWidget(
            self.high_fee_warning_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        if confirmation_time:
            self._confirmed_block = ConfirmedBlock(
                mempool_data=mempool_data,
                url=url,
                confirmation_time=confirmation_time,
                fee_rate=fee_rate,
            )
        elif is_viewer:
            self._mempool_projected_block = MempoolProjectedBlock(
                mempool_data, config=self.config, fee_rate=fee_rate
            )
        else:
            self._mempool_buttons = MempoolButtons(mempool_data, max_button_count=3)

        if allow_edit:
            self.mempool().signal_click.connect(self.set_fee_rate)
        self.groupBox_Fee_layout.addWidget(
            self.mempool().button_group, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.approximate_fee_label = QLabel()
        self.approximate_fee_label.setVisible(False)
        self.groupBox_Fee_layout.addWidget(
            self.approximate_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.rbf_fee_label = QLabel()
        self.rbf_fee_label.setWordWrap(True)
        self.rbf_fee_label.setHidden(True)
        self.groupBox_Fee_layout.addWidget(self.rbf_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.widget_around_spin_box = QWidget()
        self.widget_around_spin_box_layout = QHBoxLayout(self.widget_around_spin_box)
        self.widget_around_spin_box_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        self.groupBox_Fee_layout.addWidget(
            self.widget_around_spin_box, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.spin_fee_rate = QDoubleSpinBox()
        self.spin_fee_rate.setReadOnly(not allow_edit)
        self.spin_fee_rate.setSingleStep(1)  # Set the step size
        self.spin_fee_rate.setDecimals(1)  # Set the number of decimal places
        self.spin_fee_rate.setMaximumWidth(55)
        if fee_rate:
            self.spin_fee_rate.setValue(fee_rate)
        self.update_spin_fee_range()

        self.widget_around_spin_box_layout.addWidget(self.spin_fee_rate)

        self.spin_label = QLabel()
        self.spin_label.setText(unit_fee_str(self.config.network))
        self.widget_around_spin_box_layout.addWidget(self.spin_label)

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

        if allow_edit:
            # self.spin_fee_rate.editingFinished.connect(lambda: self.set_fee_rate(self.spin_fee_rate.value()))
            self.spin_fee_rate.valueChanged.connect(lambda: self.set_fee_rate(self.spin_fee_rate.value()))
        self.mempool().mempool_data.signal_data_updated.connect(self.updateUi)
        self.mempool().refresh()
        self.updateUi()

    def mempool(self) -> BaseBlock:
        if self._confirmed_block:
            return self._confirmed_block
        if self._mempool_projected_block:
            return self._mempool_projected_block
        if self._mempool_buttons:
            return self._mempool_buttons
        raise Exception(f"{self.__class__.__name__} wasnt initialized correctly")

    def updateUi(self) -> None:
        self.groupBox_Fee.setTitle(self.tr("Fee"))
        self.rbf_fee_label.setText(
            html_f(self.tr("... is the minimum to replace the existing transactions."), bf=True)
        )
        self.approximate_fee_label.setText(html_f(self.tr("Approximate fee rate"), bf=True))

        # only in editor mode
        self.label_block_number.setHidden(self.spin_fee_rate.isReadOnly())
        if self.spin_fee_rate.value():
            self.label_block_number.setText(
                self.tr("in ~{n}. Block").format(
                    n=self.mempool().mempool_data.fee_rate_to_projected_block_index(
                        self.spin_fee_rate.value()
                    )
                    + 1
                )
            )

        self.approximate_fee_label.setVisible(self.fee_info.is_estimated if self.fee_info else False)
        if self.fee_info:
            self.approximate_fee_label.setToolTip(
                f'<html><body>The {"approximate " if   self.fee_info.is_estimated else "" }fee is {Satoshis( self.fee_info.fee_amount  , self.config.network).str_with_unit()}</body></html>'
            )

        self.set_fiat_fee_label()
        self.set_fee_amount_label()
        self.update_fee_rate_warning()
        self.mempool().refresh()

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

    def update_fee_rate_warning(self) -> None:
        fee_rate = self.spin_fee_rate.value()

        too_high = fee_rate > self.mempool().mempool_data.max_reasonable_fee_rate()
        if fee_rate <= NO_FEE_WARNING_BELOW:
            too_high = False

        self.high_fee_rate_warning_label.setVisible(too_high)
        if too_high:
            self.high_fee_rate_warning_label.setText(html_f(self.tr("High fee rate!"), bf=True))
            self.high_fee_rate_warning_label.setToolTip(
                self.tr("The high prio mempool fee rate is {rate}").format(
                    rate=format_fee_rate(
                        self.mempool().mempool_data.max_reasonable_fee_rate(), self.config.network
                    )
                )
            )

    def set_fee_to_send_ratio(
        self,
        fee_info: FeeInfo,
        total_non_change_output_amount: int,
        network: bdk.Network,
        force_show_fee_warning_on_0_amont=False,
    ) -> None:
        if total_non_change_output_amount <= 0:
            # the == 0 case is relevant
            self.high_fee_warning_label.setVisible(force_show_fee_warning_on_0_amont)
            self.high_fee_warning_label.setText(
                self.tr("{sent} is sent!").format(
                    sent=Satoshis(total_non_change_output_amount, network=network).str_with_unit()
                )
            )
            self.high_fee_warning_label.setToolTip(
                html_f(
                    self.tr("The transaction fee is:\n{fee}, and {sent} is sent!").format(
                        fee=Satoshis(fee_info.fee_amount, network).str_with_unit(),
                        sent=Satoshis(total_non_change_output_amount, network=network).str_with_unit(),
                    ),
                    add_html_and_body=True,
                )
            )
            return

        too_high = fee_info.fee_amount / total_non_change_output_amount > FEE_RATIO_HIGH_WARNING
        self.high_fee_warning_label.setVisible(too_high and not self.mempool().confirmation_time)
        if too_high:
            self.high_fee_warning_label.setText(
                html_f(
                    self.tr("High fee ratio: {ratio}%").format(
                        ratio=round(fee_info.fee_amount / total_non_change_output_amount * 100)
                    ),
                    bf=True,
                )
            )
            s = (
                self.tr(
                    "The estimated transaction fee is:\n{fee}, which is {percent}% of\nthe sending value {sent}"
                )
                if fee_info.is_estimated
                else self.tr(
                    "The transaction fee is:\n{fee}, which is {percent}% of\nthe sending value {sent}"
                )
            )
            self.high_fee_warning_label.setToolTip(
                html_f(
                    s.format(
                        fee=Satoshis(fee_info.fee_amount, network).str_with_unit(),
                        percent=round(fee_info.fee_amount / total_non_change_output_amount * 100),
                        sent=Satoshis(total_non_change_output_amount, self.config.network).str_with_unit(),
                    ),
                    add_html_and_body=True,
                )
            )

    def set_fee_rate(
        self,
        fee_rate: float,
        fee_info: FeeInfo | None = None,
        url: str | None = None,
        confirmation_time: bdk.BlockTime | None = None,
        chain_height: int | None = None,
    ) -> None:
        # this has to be done first, because it will trigger signals
        # that will also set self.fee_amount from the spin edit
        self._set_spin_fee_value(fee_rate)
        self.fee_info = fee_info

        self.spin_fee_rate.setHidden(fee_rate is None)
        self.spin_label.setHidden(fee_rate is None)

        self.mempool().refresh(
            fee_rate=fee_rate,
            confirmation_time=confirmation_time,
            chain_height=chain_height,
        )

        if url:
            self.mempool().set_url(url)

        self.updateUi()
        self.signal_set_fee_rate.emit(fee_rate)

    def _set_spin_fee_value(self, value: float) -> None:
        self.update_spin_fee_range(value)
        self.spin_fee_rate.setValue(value)

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
            max(self.mempool().mempool_data.fee_rates_min_max(0)),
        )
        self.spin_fee_rate.setRange(*fee_range)
