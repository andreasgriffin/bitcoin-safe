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

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import format_fee_rate

from bitcoin_safe.cpfp_tools import CpfpTools
from bitcoin_safe.execute_config import GENERAL_RBF_AVAILABLE
from bitcoin_safe.i18n import translate
from bitcoin_safe.network_config import MIN_RELAY_FEE
from bitcoin_safe.tx import TxUiInfos, short_tx_id

from ...psbt_util import FeeInfo
from ...pythonbdk_types import Recipient, TransactionDetails
from ...signals import Signals
from ...wallet import TxStatus, Wallet, get_wallets
from .util import Message

logger = logging.getLogger(__name__)


class TxTools:
    @classmethod
    def edit_tx(cls, replace_tx: TransactionDetails, txinfos: TxUiInfos, signals: Signals):
        if not GENERAL_RBF_AVAILABLE:
            txinfos.utxos_read_only = True
            txinfos.recipient_read_only = True
            txinfos.replace_tx = replace_tx
        signals.open_tx_like.emit(txinfos)

    @classmethod
    def can_cpfp(cls, tx: bdk.Transaction, tx_status: TxStatus, wallet: Wallet) -> bool:
        if not tx_status.can_cpfp():
            return False
        utxo = wallet.get_cpfp_utxos(tx=tx)
        return bool(utxo)

    @classmethod
    def cpfp_tx(cls, tx_details: TransactionDetails, wallet: Wallet, signals: Signals) -> None:
        utxo = wallet.get_cpfp_utxos(tx=tx_details.transaction)
        if not utxo:
            Message(translate("tx", "Cannot CPFP the transaction because no receiving output could be found"))
            return

        txinfos = TxUiInfos()
        txinfos.fill_utxo_dict_from_utxos(utxos=[utxo])

        this_tx_fee_info = FeeInfo.estimate_from_num_inputs(
            MIN_RELAY_FEE,
            input_mn_tuples=[wallet.get_mn_tuple() for i in range(1)],
            num_outputs=1,
        )

        cpfp_tools = CpfpTools(wallets=get_wallets(signals))

        unconfirmed_ancestors = cpfp_tools.get_unconfirmed_ancestors(txids=set([tx_details.txid]))
        unconfirmed_ancestors_fee_info = (
            unconfirmed_ancestors_fee_info
            if unconfirmed_ancestors
            and (unconfirmed_ancestors_fee_info := FeeInfo.combined_fee_info(txs=unconfirmed_ancestors))
            else this_tx_fee_info
        )

        new_tx_fee_info, goal_total_fee_info = cpfp_tools.get_fee_info_of_new_tx(
            unconfirmed_ancestors_fee_info=unconfirmed_ancestors_fee_info,
            new_tx_vsize=this_tx_fee_info.vsize,
            target_total_unconfirmed_fee_rate=unconfirmed_ancestors_fee_info.fee_rate() + MIN_RELAY_FEE,
        )

        txinfos.fee_rate = new_tx_fee_info.fee_rate()
        logger.info(
            f"Choosing feerate {format_fee_rate( txinfos.fee_rate, network=wallet.config.network)} to bump the existing unconfirmed transactions from {format_fee_rate(unconfirmed_ancestors_fee_info.fee_rate(), network=wallet.config.network)} to {format_fee_rate(goal_total_fee_info.fee_rate(), network=wallet.config.network)}"
        )
        txinfos.recipients = [
            Recipient(
                address=str(wallet.get_address().address),
                label=translate("tx", "Speedup of {txid}").format(txid=short_tx_id(tx_details.txid)),
                checked_max_amount=True,
                amount=0,
            )
        ]
        txinfos.main_wallet_id = wallet.id
        signals.open_tx_like.emit(txinfos)
