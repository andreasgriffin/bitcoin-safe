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

from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import TransactionDetails

from .wallet import Wallet

logger = logging.getLogger(__name__)


class CpfpTools:
    def __init__(self, wallets: list[Wallet]) -> None:
        """Initialize instance."""
        self.wallets = wallets

    def get_unconfirmed_ancestors(
        self,
        txids: set[str],
        known_ancestors: dict[str, TransactionDetails],
    ) -> dict[str, TransactionDetails]:
        """Get unconfirmed ancestors."""
        for txid in txids:
            # already processed?
            if txid in known_ancestors:
                continue

            # find tx once across wallets
            tx = None
            for wallet in self.wallets:
                tx = wallet.get_tx(txid)
                if tx:
                    break

            # nothing to do if missing or confirmed
            if not tx or tx.chain_position.is_confirmed():
                continue

            # record BEFORE recursing to prevent duplicate work / cycles
            known_ancestors[tx.txid] = tx

            # recurse into parents (prune already-known to limit fan-out)
            parents = {str(txin.previous_output.txid) for txin in tx.transaction.input()}
            parents.difference_update(known_ancestors.keys())
            if parents:
                self.get_unconfirmed_ancestors(parents, known_ancestors)

        return known_ancestors

    def get_fee_info_of_new_tx(
        self,
        unconfirmed_ancestors_fee_info: FeeInfo,
        new_tx_vsize: int,
        target_total_unconfirmed_fee_rate: float,
    ) -> tuple[FeeInfo, FeeInfo]:
        """Get fee info of new tx."""
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
