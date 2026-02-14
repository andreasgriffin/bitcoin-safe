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

from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_list import CategoryList
from bitcoin_safe.gui.qt.nlocktime_group_box import NLocktimeGroupBox
from bitcoin_safe.gui.qt.sankey_bitcoin import SankeyBitcoin
from bitcoin_safe.gui.qt.ui_tx.fee_group import FeeGroup
from bitcoin_safe.gui.qt.ui_tx.header_widget import HeaderWidget
from bitcoin_safe.gui.qt.ui_tx.totals_box import TotalsBox
from bitcoin_safe.gui.qt.util import (
    set_margins,
    set_no_margins,
    sort_id_to_icon,
    svg_tools,
)
from bitcoin_safe.gui.qt.utxo_list import UtxoListWithToolbar
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.wallet import TxConfirmationStatus, TxStatus

from ....mempool_manager import MempoolManager
from ....signals import WalletFunctions
from .recipients import Recipients

logger = logging.getLogger(__name__)


class BaseColumn(QWidget):
    def __init__(
        self,
        fx: FX,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)

        self._layout = QVBoxLayout(self)

        self.header_widget = HeaderWidget(self)
        self._layout.addWidget(self.header_widget)

        # bottom bar
        self.totals = TotalsBox(fx=fx, network=fx.config.network)
        self._layout.addWidget(self.totals)
        set_margins(self.totals._layout, {Qt.Edge.BottomEdge: 0})

    def updateUi(self) -> None:
        """UpdateUi."""
        pass

    def insert_middle_widget(self, widget: QWidget, **kwargs):
        """Insert middle widget."""
        self._layout.insertWidget(1, widget, **kwargs)

    def is_available(self) -> bool:
        """Is available."""
        return True

    def close(self) -> bool:
        self.totals.close()
        return super().close()


class ColumnInputs(BaseColumn):
    def __init__(
        self,
        category_list: CategoryList | None,
        widget_utxo_with_toolbar: UtxoListWithToolbar,
        fx: FX,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, fx=fx)

        self.setMinimumWidth(200)

        set_margins(
            self._layout,
            {
                Qt.Edge.LeftEdge: 0,
                Qt.Edge.TopEdge: 0,
                Qt.Edge.BottomEdge: 0,
            },
        )

        self.header_widget.set_icon("bi--inputs.svg")

        groupbox = QGroupBox(self)
        groupbox_layout = QVBoxLayout(groupbox)
        self.insert_middle_widget(groupbox)

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        groupbox_layout.addWidget(self.v_splitter)

        self.checkBox_manual_coin_select = QCheckBox()
        self.checkBox_auto_opportunistic_coin_select = QCheckBox()

        if category_list:
            upper_widget = QWidget(self)
            upper_widget_layout = QVBoxLayout(upper_widget)
            set_margins(
                upper_widget_layout,
                {
                    Qt.Edge.TopEdge: 0,
                    Qt.Edge.LeftEdge: 0,
                    Qt.Edge.RightEdge: 0,
                },
            )
            set_no_margins(upper_widget_layout)

            upper_widget_layout.addWidget(category_list)
            upper_widget_layout.addWidget(self.checkBox_auto_opportunistic_coin_select)
            upper_widget_layout.addWidget(self.checkBox_manual_coin_select)

            self.v_splitter.addWidget(upper_widget)
        else:
            self.checkBox_manual_coin_select.setHidden(True)

        self.lower_widget_utxo_selection = QWidget(self)
        lower_widget_layout = QVBoxLayout(self.lower_widget_utxo_selection)
        set_margins(
            lower_widget_layout,
            {
                Qt.Edge.BottomEdge: 0,
                Qt.Edge.LeftEdge: 0,
                Qt.Edge.RightEdge: 0,
            },
        )
        lower_widget_layout.addWidget(widget_utxo_with_toolbar)
        self.v_splitter.addWidget(self.lower_widget_utxo_selection)

        # utxo list
        self.button_add_utxo = QPushButton()
        # if hasattr(bdk.TxBuilder(), "add_foreign_utxo"):
        #     self.button_add_utxo.clicked.connect(self.click_add_utxo)
        #     verticalLayout_inputs.addWidget(self.button_add_utxo)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.button_add_utxo.setText(self.tr("Add foreign UTXOs"))
        if self.checkBox_manual_coin_select:
            self.checkBox_manual_coin_select.setText(self.tr("Select specific UTXOs"))
        self.header_widget.label_title.setText(self.tr("Sending source"))
        self.totals.c0.l2.setText(self.tr("Input total:"))


class ColumnRecipients(BaseColumn):
    def __init__(
        self,
        wallet_functions: WalletFunctions,
        fx: FX,
        allow_edit=True,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, fx=fx)

        set_margins(
            self._layout,
            {
                Qt.Edge.TopEdge: 0,
                Qt.Edge.BottomEdge: 0,
            },
        )

        self.recipients = Recipients(
            wallet_functions=wallet_functions,
            network=fx.config.network,
            allow_edit=allow_edit,
            fx=fx,
            header_widget=self.header_widget,
        )
        self.insert_middle_widget(self.recipients)
        self.setMinimumWidth(250)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.recipients.updateUi()
        self.totals.c0.l2.setText(self.tr("Sending total:"))

    def close(self) -> bool:
        self.recipients.close()
        return super().close()


class ColumnSankey(BaseColumn):
    def __init__(
        self,
        wallet_functions: WalletFunctions,
        fx: FX,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, fx=fx)

        set_margins(
            self._layout,
            {
                Qt.Edge.TopEdge: 0,
                Qt.Edge.BottomEdge: 0,
            },
        )

        self.header_widget.set_icon("flows.svg")

        self.sankey_bitcoin = SankeyBitcoin(network=fx.config.network, wallet_functions=wallet_functions)
        self.sankey_bitcoin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.button_export_svg = QPushButton()
        self.button_export_svg.setIcon(svg_tools.get_QIcon("bi--filetype-svg.svg"))
        self.button_export_svg.clicked.connect(self.sankey_bitcoin.export_to_svg)
        self.header_widget.h_laylout.addWidget(self.button_export_svg)

        self.insert_middle_widget(self.sankey_bitcoin)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.header_widget.label_title.setText(self.tr("Diagram"))
        self.button_export_svg.setText(self.tr("Export svg"))

    def is_available(self) -> bool:
        """Is available."""
        return self.sankey_bitcoin.isEnabled()

    def close(self):
        """Close."""
        self.sankey_bitcoin.close()
        return super().close()


class ColumnFee(BaseColumn):
    def __init__(
        self,
        mempool_manager: MempoolManager,
        fx: FX,
        wallet_functions: WalletFunctions,
        tx_status: TxStatus,
        enable_approximate_fee_label: bool = True,
        fee_info: FeeInfo | None = None,
        allow_edit=True,
        is_viewer=False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, fx=fx)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        set_margins(
            self._layout,
            {
                Qt.Edge.RightEdge: 0,
                Qt.Edge.TopEdge: 0,
                Qt.Edge.BottomEdge: 0,
            },
        )

        self.fee_group = FeeGroup(
            wallet_functions=wallet_functions,
            mempool_manager=mempool_manager,
            fx=fx,
            config=fx.config,
            enable_approximate_fee_label=enable_approximate_fee_label,
            fee_info=fee_info,
            allow_edit=allow_edit,
            is_viewer=is_viewer,
            totals_box=self.totals,
            tx_status=tx_status,
        )
        self.insert_middle_widget(self.fee_group.groupBox_Fee, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.nlocktime_group = NLocktimeGroupBox(self)
        self.nlocktime_group.set_allow_edit(allow_edit)
        self.nlocktime_group.setHidden(True)
        self._layout.insertWidget(2, self.nlocktime_group)

        self.toolbutton_advanced = QToolButton()
        self.toolbutton_advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.toolbutton_advanced.setIcon(svg_tools.get_QIcon("bi--gear.svg"))

        self.menu_advanced = Menu(self)
        self.action_set_nlocktime = QAction(self)
        self.action_set_nlocktime.setCheckable(True)
        self.action_set_nlocktime.toggled.connect(self._on_nlocktime_toggled)
        self.menu_advanced.addAction(self.action_set_nlocktime)
        self.toolbutton_advanced.setMenu(self.menu_advanced)
        self.toolbutton_advanced.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.header_widget.h_laylout.addWidget(self.toolbutton_advanced)

    def _on_nlocktime_toggled(self, checked: bool) -> None:
        """On nlocktime toggled."""
        self.nlocktime_group.setVisible(checked)

    def set_nlocktime(self, nlocktime: int | None, current_height: int) -> None:
        """Set nlocktime."""
        self.set_nlocktime_visibility(
            visible=nlocktime is not None,
            current_height=current_height,
            reset_on_hide=False,
        )
        self.nlocktime_group.set_locktime(nlocktime, current_height=current_height)

    def set_nlocktime_visibility(
        self, visible: bool, current_height: int, reset_on_hide: bool = True
    ) -> None:
        """Set nlocktime visibility without triggering menu handlers."""
        with QSignalBlocker(self.action_set_nlocktime):
            self.action_set_nlocktime.setChecked(visible)
        if not visible and reset_on_hide:
            self.nlocktime_group.set_locktime(None, current_height=current_height)
        self.nlocktime_group.setVisible(visible)

    def nlocktime(self) -> int | None:
        """Get nlocktime."""
        if not self.action_set_nlocktime.isChecked():
            return None
        return self.nlocktime_group.locktime()

    def updateUi(self) -> None:
        """UpdateUi."""
        title = self.tr("Mempool Fees")
        tx_status = self.fee_group.mempool_buttons.tx_status
        icon_text = sort_id_to_icon(tx_status.sort_id())
        if tx_status.confirmation_status in [TxConfirmationStatus.DRAFT, TxConfirmationStatus.PSBT]:
            icon_text = "block-explorer.svg"
            title = self.tr("Priority")
        elif tx_status.confirmation_status in [TxConfirmationStatus.LOCAL, TxConfirmationStatus.UNCONFIRMED]:
            title = self.tr("Mempool position")
        elif tx_status.confirmation_status == TxConfirmationStatus.CONFIRMED:
            if tx_status.confirmations() < 6:
                title = self.tr("Confirming...")
            else:
                title = self.tr("Confirmed")
        self.header_widget.set_icon(icon_text)
        self.header_widget.label_title.setText(title)
        self.action_set_nlocktime.setText(self.tr("Show nLocktime"))
        self.nlocktime_group.updateUi()
        self.fee_group.updateUi()
