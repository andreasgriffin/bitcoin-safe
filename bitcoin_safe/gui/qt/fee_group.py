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
from bitcoin_safe.gui.qt.util import Message, MessageType
from bitcoin_safe.html import html_f, link

from ...config import FEE_RATIO_HIGH_WARNING, NO_FEE_WARNING_BELOW, UserConfig

logger = logging.getLogger(__name__)

from typing import Optional

import bdkpython as bdk
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...mempool import MempoolData, TxPrio
from ...signals import pyqtSignal
from ...util import Satoshis, format_dollar, format_fee_rate, unit_fee_str
from .block_buttons import ConfirmedBlock, MempoolButtons, MempoolProjectedBlock


class FeeGroup(QObject):
    signal_set_fee_rate = pyqtSignal(float)

    def __init__(
        self,
        mempool_data: MempoolData,
        fx: FX,
        layout: QLayout,
        config: UserConfig,
        vsize: int = None,
        allow_edit=True,
        is_viewer=False,
        confirmation_time: bdk.BlockTime = None,
        url: str = None,
        fee_rate=None,
    ) -> None:
        super().__init__()

        self.fx = fx
        self.allow_edit = allow_edit
        self.config = config
        self.vsize = vsize

        fee_rate = fee_rate if fee_rate else (mempool_data.get_prio_fee_rates()[TxPrio.low])

        # add the groupBox_Fee
        self.groupBox_Fee = QGroupBox()
        self.groupBox_Fee.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)
        self.groupBox_Fee.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.groupBox_Fee.setLayout(QVBoxLayout())
        self.groupBox_Fee.layout().setAlignment(Qt.AlignmentFlag.AlignHCenter)
        # self.groupBox_Fee.layout().setContentsMargins(
        #     int(layout.contentsMargins().left() / 5),
        #     int(layout.contentsMargins().top() / 5),
        #     int(layout.contentsMargins().right() / 5),
        #     int(layout.contentsMargins().bottom() / 5),
        # )

        if confirmation_time:
            self.mempool = ConfirmedBlock(
                mempool_data=mempool_data,
                url=url,
                confirmation_time=confirmation_time,
                fee_rate=fee_rate,
            )
        elif is_viewer:
            self.mempool = MempoolProjectedBlock(mempool_data, config=self.config, fee_rate=fee_rate)
        else:
            self.mempool = MempoolButtons(mempool_data, max_button_count=3)

        if allow_edit:
            self.mempool.signal_click.connect(self.set_fee_rate)
        self.groupBox_Fee.layout().addWidget(
            self.mempool.button_group, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.high_fee_rate_warning_label = QLabel()
        self.high_fee_rate_warning_label.setHidden(True)
        self.groupBox_Fee.layout().addWidget(
            self.high_fee_rate_warning_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.high_fee_warning_label = QLabel()
        self.high_fee_warning_label.setHidden(True)
        self.groupBox_Fee.layout().addWidget(
            self.high_fee_warning_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.approximate_fee_label = QLabel()
        self.approximate_fee_label.setHidden(True)
        self.groupBox_Fee.layout().addWidget(
            self.approximate_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.rbf_fee_label = QLabel()
        self.rbf_fee_label.setWordWrap(True)
        self.rbf_fee_label.setHidden(True)
        self.groupBox_Fee.layout().addWidget(self.rbf_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.widget_around_spin_box = QWidget()
        self.widget_around_spin_box.setLayout(QHBoxLayout())
        self.widget_around_spin_box.layout().setContentsMargins(0, 0, 0, 0)  # Remove margins
        self.groupBox_Fee.layout().addWidget(
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
        self.spin_fee_rate.editingFinished.connect(lambda: self.set_fee_rate(self.spin_fee_rate.value()))
        self.spin_fee_rate.valueChanged.connect(lambda: self.set_fee_rate(self.spin_fee_rate.value()))

        self.widget_around_spin_box.layout().addWidget(self.spin_fee_rate)

        self.spin_label = QLabel()
        self.spin_label.setText(unit_fee_str(self.config.network))
        self.widget_around_spin_box.layout().addWidget(self.spin_label)

        self.fiat_fee_label = QLabel()
        self.fiat_fee_label.setHidden(True)
        self.groupBox_Fee.layout().addWidget(self.fiat_fee_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.fx.signal_data_updated.connect(self.updateUi)

        self.label_block_number = QLabel()
        self.label_block_number.setHidden(True)
        self.groupBox_Fee.layout().addWidget(self.label_block_number, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(self.groupBox_Fee, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.spin_fee_rate.valueChanged.connect(self.updateUi)
        self.mempool.mempool_data.signal_data_updated.connect(self.updateUi)
        self.mempool.refresh()
        self.updateUi()

    def updateUi(self) -> None:
        self.groupBox_Fee.setTitle(self.tr("Fee"))
        self.rbf_fee_label.setText(
            html_f(self.tr("... is the minimum to replace the existing transactions."), bf=True)
        )
        self.high_fee_rate_warning_label.setText(html_f(self.tr("High fee rate"), color="red", bf=True))
        self.high_fee_warning_label.setText(html_f(self.tr("High fee"), color="red", bf=True))
        self.approximate_fee_label.setText(html_f(self.tr("Approximate fee rate"), bf=True))

        # only in editor mode
        self.label_block_number.setHidden(self.spin_fee_rate.isReadOnly())
        if self.spin_fee_rate.value():
            self.label_block_number.setText(
                self.tr("in ~{n}. Block").format(
                    n=self.mempool.mempool_data.fee_rate_to_projected_block_index(self.spin_fee_rate.value())
                    + 1
                )
            )

        self.set_fiat_fee_label()
        self.update_fee_rate_warning()
        self.mempool.refresh()

    def set_vsize(self, vsize) -> None:
        self.vsize = vsize
        self.updateUi()

    def set_fiat_fee_label(self) -> None:
        if not self.fx.rates.get("usd"):
            self.fiat_fee_label.setHidden(True)
            return
        if self.vsize is None:
            self.fiat_fee_label.setHidden(True)
            return
        fee = self.vsize * self.spin_fee_rate.value()
        self.fiat_fee_label.setText(format_dollar(self.fx.rates["usd"]["value"] / 1e8 * fee))
        self.fiat_fee_label.setHidden(False)

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

    def set_fee_to_send_ratio(
        self, fee: int, total_output_amount: int, network: bdk.Network, fee_is_exact=False
    ) -> None:
        if total_output_amount > 0:
            too_high = fee / total_output_amount > FEE_RATIO_HIGH_WARNING
        else:
            Message(self.tr("Fee rate could not be determined"), type=MessageType.Error)
            return

        self.high_fee_warning_label.setVisible(too_high and not self.mempool.confirmation_time)
        if too_high:
            self.high_fee_warning_label.setText(
                html_f(
                    self.tr("High fee ratio: {ratio}%").format(ratio=round(fee / total_output_amount * 100)),
                    color="red",
                    bf=True,
                )
            )
            if fee_is_exact:
                self.high_fee_warning_label.setToolTip(
                    html_f(
                        self.tr(
                            "The transaction fee is:\n{fee}, which is {percent}% of\nthe sending value {sent}"
                        ).format(
                            fee=Satoshis(fee, network).str_with_unit(),
                            percent=round(fee / total_output_amount * 100),
                            sent=Satoshis(total_output_amount, self.config.network).str_with_unit(),
                        ),
                        add_html_and_body=True,
                    )
                )
            else:
                self.high_fee_warning_label.setToolTip(
                    html_f(
                        self.tr(
                            "The estimated transaction fee is:\n{fee}, which is {percent}% of\nthe sending value {sent}"
                        ).format(
                            fee=Satoshis(fee, network).str_with_unit(),
                            percent=round(fee / total_output_amount * 100),
                            sent=Satoshis(total_output_amount, self.config.network).str_with_unit(),
                        ),
                        add_html_and_body=True,
                    )
                )

    def update_fee_rate_warning(self) -> None:
        fee_rate = self.spin_fee_rate.value()

        too_high = fee_rate > self.mempool.mempool_data.max_reasonable_fee_rate()
        if fee_rate <= NO_FEE_WARNING_BELOW:
            too_high = False

        self.high_fee_rate_warning_label.setVisible(too_high)
        if too_high:
            self.high_fee_rate_warning_label.setText(html_f(self.tr("High fee rate!"), color="red", bf=True))
            self.high_fee_rate_warning_label.setToolTip(
                self.tr("The high prio mempool fee rate is {rate}").format(
                    rate=format_fee_rate(
                        self.mempool.mempool_data.max_reasonable_fee_rate(), self.config.network
                    )
                )
            )

    def set_fee_rate(
        self,
        fee_rate: float,
        url: str = None,
        confirmation_time: bdk.BlockTime = None,
        chain_height=None,
    ) -> None:
        self.spin_fee_rate.setHidden(fee_rate is None)
        self.spin_label.setHidden(fee_rate is None)

        self.mempool.refresh(
            fee_rate=fee_rate,
            confirmation_time=confirmation_time,
            chain_height=chain_height,
        )
        self._set_value(fee_rate if fee_rate else 0)

        if url:
            self.mempool.set_url(url)

        self.updateUi()
        self.signal_set_fee_rate.emit(fee_rate)

    def _set_value(self, value: float) -> None:
        self.update_spin_fee_range(value)
        self.spin_fee_rate.setValue(value)

    def update_spin_fee_range(self, value: float = 0) -> None:
        "Set the acceptable range"
        fee_range = self.config.fee_ranges[self.config.network].copy()
        fee_range[1] = max(
            fee_range[1],
            value,
            self.spin_fee_rate.value(),
            max(self.mempool.mempool_data.fee_rates_min_max(0)),
        )
        self.spin_fee_rate.setRange(*fee_range)
