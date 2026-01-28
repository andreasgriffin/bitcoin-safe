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
import platform

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol, Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalTools, SignalTracker
from PyQt6.QtGui import QColor

from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.packaged_tx_like import PackagedTxLike, UiElements
from bitcoin_safe.gui.qt.sankey_widget import FlowIndex, FlowType, SankeyWidget
from bitcoin_safe.html_utils import html_f
from bitcoin_safe.labels import LabelType
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    TxOut,
    get_prev_outpoints,
    robust_address_str_from_txout,
)
from bitcoin_safe.signals import UpdateFilter, WalletFunctions
from bitcoin_safe.wallet import (
    Wallet,
    get_label_from_any_wallet,
    get_wallet_of_address,
    get_wallets,
)

logger = logging.getLogger(__name__)


class SankeyBitcoin(SankeyWidget):
    def __init__(self, network: bdk.Network, wallet_functions: WalletFunctions):
        """Initialize instance."""
        super().__init__()
        self.wallet_functions = wallet_functions
        self.signals = wallet_functions.signals
        self.network = network
        self.tx: bdk.Transaction | None = None
        self.fee_info: FeeInfo | None = None
        self.txouts: list[TxOut] = []
        self.addresses: list[str] = []
        self.txo_dict: dict[str, PythonUtxo] = {}
        self.signal_tracker = SignalTracker()

        self.signal_tracker.connect(self.signals.any_wallet_updated, self.refresh)
        self.signal_tracker.connect(self.signal_on_label_click, self.on_label_click)

    def refresh(self, update_filter: UpdateFilter):
        """Refresh."""
        if not self.tx:
            return

        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or self.tx.compute_txid() in update_filter.txids:
            should_update = True
        if should_update or set(self.outpoints).intersection(update_filter.outpoints):
            should_update = True
        if should_update or set(self.input_outpoints).intersection(update_filter.outpoints):
            should_update = True
        if should_update or set(self.addresses).intersection(update_filter.addresses):
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter")
        self.set_tx(self.tx, fee_info=self.fee_info, txo_dict=self.txo_dict)

    @property
    def outpoints(self) -> list[OutPoint]:
        """Outpoints."""
        if not self.tx:
            return []
        txid = self.tx.compute_txid()
        return [OutPoint(txid=txid, vout=vout) for vout in range(len(self.tx.output()))]

    @property
    def input_outpoints(self) -> list[OutPoint]:
        """Input outpoints."""
        if not self.tx:
            return []
        return [OutPoint.from_bdk(inp.previous_output) for inp in self.tx.input()]

    def set_tx(
        self,
        tx: bdk.Transaction,
        fee_info: FeeInfo | None = None,
        txo_dict: dict[str, PythonUtxo] | None = None,
    ) -> bool:
        """Set tx."""

        def get_label_and_tooltip(
            value: int | None,
            label: str | None,
            address: str | None,
            count: int,
            connect_right=False,
            connect_left=False,
        ):
            """Get label and tooltip."""
            display_label = ""
            tooltip = ""

            system_name = platform.system()  # macOS
            left_arrow = "◁" if system_name == "Darwin" else "⮜"
            right_arrow = "▷" if system_name == "Darwin" else "⮞"

            if connect_left:
                display_label += f"{left_arrow} "

            if label:
                display_label += label + "\n"
                tooltip += label + "\n"
            elif address:
                # display_label += address
                tooltip += address + "\n"

            if value is not None:
                # if count<10 :
                display_label += Satoshis(value, self.network).str_with_unit(
                    color_formatting=None,
                    btc_symbol=self.wallet_functions.signals.get_btc_symbol() or BitcoinSymbol.ISO.value,
                )
                tooltip += Satoshis(value, self.network).str_with_unit(
                    btc_symbol=self.wallet_functions.signals.get_btc_symbol() or BitcoinSymbol.ISO.value
                )

            if connect_right:
                display_label += f" {right_arrow}"
            return display_label.strip("\n"), ""  # html_f(tooltip,add_html_and_body=True,)

        self.fee_info = fee_info
        self.tx = tx
        self.txo_dict = txo_dict if txo_dict else {}
        self.addresses = []
        wallets = get_wallets(self.wallet_functions)

        labels: dict[FlowIndex, str] = {}
        tooltips: dict[FlowIndex, str] = {}
        colors: dict[FlowIndex, QColor] = {}

        # output
        self.txouts = [TxOut.from_bdk(txout) for txout in tx.output()]
        out_flows: list[int] = [txout.value.to_sat() for txout in self.txouts]
        for vout, txout in enumerate(self.txouts):
            flow_index = FlowIndex(flow_type=FlowType.OutFlow, i=vout)
            address = robust_address_str_from_txout(txout, network=self.network)
            self.addresses.append(address)

            label = get_label_from_any_wallet(
                label_type=LabelType.addr,
                ref=address,
                wallet_functions=self.wallet_functions,
                wallets=wallets,
                autofill_from_txs=False,
            )
            color = self.get_address_color(address, wallets=wallets)

            outpoint = self.txo_dict.get(str(OutPoint(txid=self.tx.compute_txid(), vout=vout)))
            labels[flow_index], tooltips[flow_index] = get_label_and_tooltip(
                value=txout.value.to_sat(),
                label=label,
                address=address,
                count=len(self.txouts),
                connect_right=bool(outpoint and outpoint.is_spent_by_txid),
            )

            if color:
                colors[flow_index] = color

        wallets = get_wallets(self.wallet_functions)
        outpoint_dict = {
            outpoint_str: (python_utxo, wallet)
            for wallet in wallets
            for outpoint_str, python_utxo in wallet.get_all_txos_dict().items()
        }

        # input
        in_flows: list[int | None] = []
        prev_outpoints = get_prev_outpoints(tx)
        for vout, outpoint in enumerate(prev_outpoints):
            outpoint_str = str(outpoint)
            flow_index = FlowIndex(flow_type=FlowType.InFlow, i=vout)

            if outpoint_str in outpoint_dict:
                python_utxo, wallet = outpoint_dict[outpoint_str]
                address = python_utxo.address
                value = python_utxo.value
                in_flows.append(value)

                # add labels and colors
                self.addresses.append(address)

                label = get_label_from_any_wallet(
                    label_type=LabelType.addr,
                    ref=address,
                    wallet_functions=self.wallet_functions,
                    wallets=wallets,
                    autofill_from_txs=False,
                )
                color = self.get_address_color(address, wallets=wallets)
                labels[flow_index], tooltips[flow_index] = get_label_and_tooltip(
                    value=value,
                    label=label,
                    address=address,
                    count=len(prev_outpoints),
                    connect_left=bool(
                        python_utxo
                    ),  # if a python utxo is available, it means I know the previous tx
                )
                if color:
                    colors[flow_index] = color
            elif outpoint_str in self.txo_dict:
                value = self.txo_dict[outpoint_str].value
                in_flows.append(value)
                labels[flow_index], tooltips[flow_index] = get_label_and_tooltip(
                    value=value, label=None, address=None, count=len(prev_outpoints)
                )
            else:
                # ensure all inputs are known
                in_flows.append(None)
                continue

        # handle cases where i have sufficient info to still construct a diagram
        if (None in in_flows) and fee_info and not fee_info.fee_amount_is_estimated:
            num_unknown_inputs = in_flows.count(None)
            missing_inflows = sum(out_flows) + fee_info.fee_amount - sum(v for v in in_flows if v is not None)
            # if there is only 1 input unknown, I can still construct a diagram, if the fee is known
            if num_unknown_inputs == 1:
                for vout, in_flow in enumerate(in_flows):
                    if in_flow is None:
                        in_flows[vout] = missing_inflows
                        flow_index = FlowIndex(flow_type=FlowType.InFlow, i=vout)
                        labels[flow_index], tooltips[flow_index] = get_label_and_tooltip(
                            value=missing_inflows, label=None, address=None, count=len(in_flows)
                        )
                        break

            elif num_unknown_inputs > 1:
                # if there is fee info, but the inputs are unknown
                # I can make the unknown inputs half transparent
                # to indicate an unknown amount
                remaining_missing_inflows = missing_inflows
                remaining_unknown_inputs = num_unknown_inputs
                for vout, in_flow in enumerate(in_flows):
                    if in_flow is None and remaining_unknown_inputs > 0:
                        amount = remaining_missing_inflows // remaining_unknown_inputs
                        remaining_missing_inflows -= amount
                        remaining_unknown_inputs -= 1

                        in_flows[vout] = amount
                        flow_index = FlowIndex(flow_type=FlowType.InFlow, i=vout)
                        colors[flow_index] = QColor("#00000000")

                if sum(out_flows) + fee_info.fee_amount != sum(v for v in in_flows if v is not None):
                    logger.warning(
                        "Error in sankey bitcoin widget.  "
                        "There should be enough info to construct a partial diagram."
                    )
                    return False

        if None in in_flows:
            return False

        pure_in_flows = [v for v in in_flows if v is not None]
        in_sum = sum(pure_in_flows)

        # other
        fee = int(in_sum - sum(out_flows))
        if fee > 0:
            out_flows.append(fee)
            flow_index = FlowIndex(FlowType.OutFlow, i=len(self.txouts))
            labels[flow_index] = self.tr("Fee")
            tooltips[flow_index] = html_f(
                labels[flow_index]
                + "<br>"
                + Satoshis(fee, self.network).str_with_unit(
                    btc_symbol=self.wallet_functions.signals.get_btc_symbol() or BitcoinSymbol.ISO.value
                ),
                add_html_and_body=True,
            )

        self.set(
            in_flows=pure_in_flows,
            out_flows=out_flows,
            colors=colors,
            labels=labels,
            tooltips=tooltips,
        )
        return True

    def get_address_color(self, address: str, wallets: list[Wallet]) -> QColor | None:
        """Get address color."""
        wallet = get_wallet_of_address(address=address, wallet_functions=self.wallet_functions)
        if not wallet:
            return None
        color = AddressEdit.color_address(
            address, wallet, wallet_signals=self.wallet_functions.wallet_signals[wallet.id]
        )
        if not color:
            logger.error("This should not happen, since wallet should only be found if the address is mine.")
            return None
        return color

    def get_python_txo(self, outpoint: str, wallets: list[Wallet] | None = None) -> PythonUtxo | None:
        """Get python txo."""
        wallets = wallets if wallets else get_wallets(self.wallet_functions)
        for wallet in wallets:
            txo = wallet.get_python_txo(outpoint)
            if txo:
                return txo
        return None

    def on_label_click(self, flow_index: FlowIndex):
        """On label click."""
        if not self.tx:
            return
        if flow_index.flow_type == FlowType.OutFlow:
            # output
            # careful, the last flow_index.i is the fee, so
            # outflow indexes go 1 larger than the actual vout index
            outpoint = OutPoint(txid=self.tx.compute_txid(), vout=flow_index.i)
            txo = self.txo_dict.get(str(outpoint)) or self.get_python_txo(str(outpoint))
            if not txo:
                return
            if txo.is_spent_by_txid:
                # open the spending tx
                self.signals.open_tx_like.emit(
                    PackagedTxLike(tx_like=txo.is_spent_by_txid, focus_ui_elements=UiElements.diagram)
                )

        elif flow_index.flow_type == FlowType.InFlow:
            outpoints = get_prev_outpoints(self.tx)
            if len(outpoints) <= flow_index.i:
                return
            outpoint = outpoints[flow_index.i]
            self.signals.open_tx_like.emit(
                PackagedTxLike(tx_like=outpoint.txid_str, focus_ui_elements=UiElements.diagram)
            )

    def close(self):
        """Close."""
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setVisible(False)
        self.setParent(None)
        return super().close()
