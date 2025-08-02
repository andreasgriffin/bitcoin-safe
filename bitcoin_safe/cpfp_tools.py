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
from typing import List, Set, Tuple

from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import TransactionDetails

from .wallet import Wallet

logger = logging.getLogger(__name__)


class CpfpTools:
    def __init__(self, wallets: List[Wallet]) -> None:
        self.wallets = wallets

    def get_unconfirmed_ancestors(self, txids: Set[str]) -> List[TransactionDetails] | None:
        unconfirmed_txs: List[TransactionDetails] = []
        for txid in txids:
            for wallet in self.wallets:
                tx = wallet.get_tx(txid)
                if tx and not tx.chain_position.is_confirmed():
                    unconfirmed_txs.append(tx)

        # i am modifying unconfirmed_txs duringt he loop, so the copy() is essential
        for unconfirmed_tx in unconfirmed_txs.copy():
            # add its unconfirmed parents
            unconfirmed_txs += (
                self.get_unconfirmed_ancestors(
                    txids=set(txin.previous_output.txid for txin in unconfirmed_tx.transaction.input()),
                )
                or []
            )
        if not unconfirmed_txs:
            return None

        # the following removes already all with duplicate txids
        tx_dict = {tx.txid: tx for tx in unconfirmed_txs}
        return list(tx_dict.values())

    def get_fee_info_of_new_tx(
        self,
        unconfirmed_ancestors_fee_info: FeeInfo,
        new_tx_vsize: int,
        target_total_unconfirmed_fee_rate: float,
    ) -> Tuple[FeeInfo, FeeInfo]:
        new_tx_fee_info_wrong_fee = FeeInfo.from_fee_rate_and_vsize(
            fee_rate=unconfirmed_ancestors_fee_info.fee_rate(),
            vsize=new_tx_vsize,
            fee_rate_is_estimated=unconfirmed_ancestors_fee_info.fee_rate_is_estimated(),
            vsize_is_estimated=True,
        )

        goal_total_fee_info = FeeInfo.from_fee_rate_and_vsize(
            fee_rate=target_total_unconfirmed_fee_rate,
            vsize=unconfirmed_ancestors_fee_info.vsize + new_tx_fee_info_wrong_fee.vsize,
            fee_rate_is_estimated=True,
            vsize_is_estimated=True,
        )

        new_tx_fee_info = FeeInfo(
            fee_amount=int(
                target_total_unconfirmed_fee_rate * goal_total_fee_info.vsize
                - unconfirmed_ancestors_fee_info.fee_amount
            ),
            vsize=new_tx_fee_info_wrong_fee.vsize,
            fee_amount_is_estimated=True,
            vsize_is_estimated=True,
        )
        return new_tx_fee_info, goal_total_fee_info
