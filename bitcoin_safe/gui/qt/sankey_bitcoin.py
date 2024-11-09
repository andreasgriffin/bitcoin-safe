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
from typing import Dict, List, Optional

import bdkpython as bdk
from PyQt6.QtGui import QColor

from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.sankey_widget import FlowIndex, FlowType, SankeyWidget
from bitcoin_safe.html_utils import html_f
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    TxOut,
    get_outpoints,
    robust_address_str_from_script,
)
from bitcoin_safe.signals import Signals, UpdateFilter
from bitcoin_safe.util import Satoshis
from bitcoin_safe.wallet import Wallet, get_label_from_any_wallet, get_wallets

logger = logging.getLogger(__name__)


class SankeyBitcoin(SankeyWidget):
    def __init__(self, network: bdk.Network, signals: Signals):
        super().__init__()
        self.signals = signals
        self.network = network
        self.tx: bdk.Transaction | None = None
        self.txouts: List[TxOut] = []
        self.addresses: List[str] = []

        self.signals.any_wallet_updated.connect(self.refresh)
        self.signal_on_label_click.connect(self.on_label_click)

    def refresh(self, update_filter: UpdateFilter):
        if not self.tx:
            return

        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or self.tx.txid() in update_filter.txids:
            should_update = True
        if should_update or set(self.outpoints).intersection(update_filter.outpoints):
            should_update = True
        if should_update or set(self.input_outpoints).intersection(update_filter.outpoints):
            should_update = True
        if should_update or set(self.addresses).intersection(update_filter.addresses):
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")
        self.set_tx(self.tx)

    @property
    def outpoints(self) -> List[OutPoint]:
        if not self.tx:
            return []
        txid = self.tx.txid()
        return [OutPoint(txid=txid, vout=vout) for vout in range(len(self.tx.output()))]

    @property
    def input_outpoints(self) -> List[OutPoint]:
        if not self.tx:
            return []
        return [OutPoint.from_bdk(inp.previous_output) for inp in self.tx.input()]

    def set_tx(self, tx: bdk.Transaction, fee_info: FeeInfo | None = None) -> bool:
        self.tx = tx
        self.addresses = []
        wallets = get_wallets(self.signals)

        labels: Dict[FlowIndex, str] = {}
        tooltips: Dict[FlowIndex, str] = {}
        colors: Dict[FlowIndex, QColor] = {}

        # output
        self.txouts = [TxOut.from_bdk(txout) for txout in tx.output()]
        out_flows: List[float] = [txout.value for txout in self.txouts]
        for i, txout in enumerate(self.txouts):
            flow_index = FlowIndex(flow_type=FlowType.OutFlow, i=i)
            address = robust_address_str_from_script(txout.script_pubkey, network=self.network)
            self.addresses.append(address)

            label = get_label_from_any_wallet(
                address, signals=self.signals, wallets=wallets, autofill_from_txs=False
            )
            color = self.get_address_color(address, wallets=wallets)
            labels[flow_index] = label if label else address
            tooltips[flow_index] = html_f(
                ((label + "\n" + address) if label else address)
                + "\n"
                + Satoshis(txout.value, self.network).str_with_unit(),
                add_html_and_body=True,
            )
            if color:
                colors[flow_index] = color

        wallets = get_wallets(self.signals)
        outpoint_dict = {
            outpoint_str: (python_utxo, wallet)
            for wallet in wallets
            for outpoint_str, python_utxo in wallet.get_all_txos_dict().items()
        }

        # input
        in_python_txos: List[PythonUtxo] = []
        sufficient_info = True
        for outpoint in get_outpoints(tx):
            outpoint_str = str(outpoint)
            if outpoint_str not in outpoint_dict:
                # ensure all inputs are known
                sufficient_info = False
                break
            python_utxo, wallet = outpoint_dict[outpoint_str]
            in_python_txos.append(python_utxo)

        for i, txo in enumerate(in_python_txos):
            self.addresses.append(txo.address)
            flow_index = FlowIndex(flow_type=FlowType.InFlow, i=i)

            label = get_label_from_any_wallet(
                txo.address, signals=self.signals, wallets=wallets, autofill_from_txs=False
            )
            color = self.get_address_color(txo.address, wallets=wallets)
            labels[flow_index] = label if label else txo.address
            tooltips[flow_index] = html_f(
                ((label + "\n" + txo.address) if label else txo.address)
                + "\n"
                + Satoshis(txo.txout.value, self.network).str_with_unit(),
                add_html_and_body=True,
            )
            if color:
                colors[flow_index] = color

        in_flows: List[float] = [txo.txout.value for txo in in_python_txos]

        if not sufficient_info:
            # if there is only 1 input and the fee is known, I can still construct a diagram
            if len(get_outpoints(tx)) == 1 and len(in_flows) == 0 and fee_info and not fee_info.is_estimated:
                in_flows = [sum(out_flows) + fee_info.fee_amount]
                sufficient_info = True

        if not sufficient_info:
            return False

        in_sum = sum(in_flows)

        # other
        fee = int(in_sum - sum(out_flows))
        if fee > 0:
            out_flows.append(fee)
            flow_index = FlowIndex(FlowType.OutFlow, i=len(self.txouts))
            labels[flow_index] = self.tr("Fee")
            tooltips[flow_index] = html_f(
                labels[flow_index] + "<br>" + Satoshis(fee, self.network).str_with_unit(),
                add_html_and_body=True,
            )

        self.set(
            in_flows=in_flows,
            out_flows=out_flows,
            colors=colors,
            labels=labels,
            tooltips=tooltips,
        )
        return True

    def get_address_color(self, address: str, wallets: List[Wallet]) -> QColor | None:
        def get_wallet():
            for wallet in wallets:
                if wallet.is_my_address(address):
                    return wallet
            return None

        wallet = get_wallet()
        if not wallet:
            return None
        color = AddressEdit.color_address(address, wallet)
        if not color:
            logger.error("This should not happen, since wallet should only be found if the address is mine.")
            return None
        return color

    def get_python_txo(self, outpoint: str, wallets: List[Wallet] | None = None) -> Optional[PythonUtxo]:
        wallets = wallets if wallets else get_wallets(self.signals)
        for wallet in wallets:
            txo = wallet.get_python_txo(outpoint)
            if txo:
                return txo
        return None

    def on_label_click(self, flow_index: FlowIndex):
        if not self.tx:
            return
        if flow_index.flow_type == FlowType.OutFlow:
            # output
            # careful, the last flow_index.i is the fee, so
            # outflow indexes go 1 larger than the actual vout index
            outpoint = OutPoint(self.tx.txid(), flow_index.i)
            txo = self.get_python_txo(str(outpoint))
            if not txo:
                return
            if txo.is_spent_by_txid:
                # open the spending tx
                self.signals.open_tx_like.emit(txo.is_spent_by_txid)

        elif flow_index.flow_type == FlowType.InFlow:
            outpoints = get_outpoints(self.tx)
            if len(outpoints) <= flow_index.i:
                return
            outpoint = outpoints[flow_index.i]
            self.signals.open_tx_like.emit(outpoint.txid)
