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

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import format_fee_rate
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.cpfp_tools import CpfpTools
from bitcoin_safe.execute_config import GENERAL_RBF_AVAILABLE
from bitcoin_safe.i18n import translate
from bitcoin_safe.mempool_data import MIN_RELAY_FEE
from bitcoin_safe.tx import TxUiInfos, short_tx_id

from ...psbt_util import FeeInfo
from ...pythonbdk_types import Recipient, TransactionDetails, _is_taproot_script
from ...signals import WalletFunctions
from ...wallet import TxStatus, Wallet, get_tx_details, get_wallets
from .util import Message

logger = logging.getLogger(__name__)


class TxTools:
    @classmethod
    def can_edit_safely(
        cls,
        tx_status: TxStatus,
    ) -> bool:
        """Can edit safely."""
        return tx_status.can_edit()

    @classmethod
    def can_cancel(
        cls,
        tx_status: TxStatus,
    ) -> bool:
        """Can cancel."""
        return GENERAL_RBF_AVAILABLE and tx_status.can_rbf()

    @classmethod
    def can_rbf_safely(
        cls,
        tx: bdk.Transaction,
        tx_status: TxStatus,
    ) -> bool:
        """Return True if the transaction can safely be replaced via RBF.

        If an output might be a Silent Payment output it returns False.

        Silent payment burn protection
        Explanation: Silent payments outputs are dependent on all inputs of the tx
        if any input is changed, but the SP output is left untouched,
        the output becomes: undetectable for the receiver and unspendable
        if the replaces transaction is not known
        ref https://github.com/spesmilo/electrum/pull/9900#issuecomment-3318598185
        and https://github.com/sparrowwallet/sparrow/issues/1434#issuecomment-3345317202
        """
        if not tx_status.can_rbf():
            return False

        if not GENERAL_RBF_AVAILABLE:
            # prevents changing inputs
            return True

        at_least_1_taproot_output = any(
            _is_taproot_script(bytes(output.script_pubkey.to_bytes())) for output in tx.output()
        )

        if at_least_1_taproot_output and not tx.is_explicitly_rbf():
            # this could be a Silent Payment tx
            return False

        return True

    @classmethod
    def add_replace_tx_to_txuiinfos(
        cls,
        replace_tx: bdk.Transaction | None,
        txinfos: TxUiInfos,
    ):
        if not GENERAL_RBF_AVAILABLE and replace_tx:
            txinfos.utxos_read_only = True
            txinfos.recipient_read_only = True
            txinfos.replace_tx = replace_tx

    @classmethod
    def edit_tx(
        cls,
        replace_tx: TransactionDetails | None,
        txinfos: TxUiInfos,
        tx_status: TxStatus,
        wallet_functions: WalletFunctions,
    ):
        """Edit tx."""
        if not cls.can_edit_safely(
            tx_status=tx_status,
        ):
            # cannot be done safely
            return

        if replace_tx:
            cls.add_replace_tx_to_txuiinfos(replace_tx=replace_tx.transaction, txinfos=txinfos)

        txinfos.hide_UTXO_selection = False
        wallet_functions.signals.open_tx_like.emit(txinfos)

    @classmethod
    def rbf_tx(
        cls,
        replace_tx: bdk.Transaction,
        txinfos: TxUiInfos,
        tx_status: TxStatus,
        wallet_functions: WalletFunctions,
    ):
        """Rbf tx."""
        if not cls.can_rbf_safely(
            tx=replace_tx,
            tx_status=tx_status,
        ):
            # cannot be done safely
            return

        if not GENERAL_RBF_AVAILABLE and replace_tx:
            txinfos.utxos_read_only = True
            txinfos.recipient_read_only = True
            txinfos.replace_tx = replace_tx

        txinfos.hide_UTXO_selection = False
        wallet_functions.signals.open_tx_like.emit(txinfos)

    @classmethod
    def can_cpfp(
        cls,
        tx_status: TxStatus,
        wallet_functions: WalletFunctions,
        wallet: Wallet | None = None,
    ) -> bool:
        """Can cpfp."""
        tx = tx_status.tx
        if not tx:
            return False
        if not tx_status.can_cpfp():
            return False

        if not wallet:
            tx_details, wallet = get_tx_details(
                txid=str(tx.compute_txid()), wallet_functions=wallet_functions
            )
            if not wallet:
                return False

        utxo = wallet.get_cpfp_utxos(tx=tx)
        return bool(utxo)

    @classmethod
    def cpfp_tx(
        cls,
        tx_details: TransactionDetails,
        wallet: Wallet,
        wallet_functions: WalletFunctions,
        fee_rate: float | None = None,
        target_total_unconfirmed_fee_rate: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Cpfp tx."""
        utxo = wallet.get_cpfp_utxos(tx=tx_details.transaction)
        if not utxo:
            Message(
                translate("tx", "Cannot CPFP the transaction because no receiving output could be found"),
                parent=parent,
            )
            return

        txinfos = TxUiInfos()
        txinfos.utxos_read_only = True
        txinfos.hide_UTXO_selection = False
        txinfos.fill_utxo_dict_from_utxos(utxos=[utxo])

        this_tx_fee_info = FeeInfo.estimate_from_num_inputs(
            MIN_RELAY_FEE,
            input_mn_tuples=[wallet.get_mn_tuple() for i in range(1)],
            num_outputs=1,
        )

        cpfp_tools = CpfpTools(wallets=get_wallets(wallet_functions))

        if fee_rate is None:
            unconfirmed_ancestors = cpfp_tools.get_unconfirmed_ancestors(
                txids=set([tx_details.txid]), known_ancestors={}
            )
            unconfirmed_ancestors_fee_info = (
                unconfirmed_ancestors_fee_info
                if unconfirmed_ancestors
                and (
                    unconfirmed_ancestors_fee_info := FeeInfo.combined_fee_info(
                        txs=unconfirmed_ancestors.values()
                    )
                )
                else this_tx_fee_info
            )

            new_tx_fee_info, goal_total_fee_info = cpfp_tools.get_fee_info_of_new_tx(
                unconfirmed_ancestors_fee_info=unconfirmed_ancestors_fee_info,
                new_tx_vsize=this_tx_fee_info.vsize,
                target_total_unconfirmed_fee_rate=max(
                    unconfirmed_ancestors_fee_info.fee_rate() + MIN_RELAY_FEE,
                    (
                        target_total_unconfirmed_fee_rate
                        if target_total_unconfirmed_fee_rate is not None
                        else MIN_RELAY_FEE
                    ),
                ),
            )

            txinfos.fee_rate = new_tx_fee_info.fee_rate()
            logger.info(
                f"Choosing feerate {format_fee_rate(txinfos.fee_rate, network=wallet.config.network)} "
                f"to bump the existing unconfirmed transactions from "
                f"{format_fee_rate(unconfirmed_ancestors_fee_info.fee_rate(), network=wallet.config.network)}"
                " to "
                f"{format_fee_rate(goal_total_fee_info.fee_rate(), network=wallet.config.network)}"
            )
        else:
            txinfos.fee_rate = fee_rate

        categories = wallet.get_categories_for_txid(tx_details.txid)
        txinfos.recipients = [
            Recipient(
                address=str(
                    wallet.get_unused_category_address(
                        category=categories[0] if categories else wallet.labels.default_category
                    ).address
                ),
                label=translate("tx", "Speedup of {txid}").format(txid=short_tx_id(tx_details.txid)),
                checked_max_amount=True,
                amount=0,
            )
        ]
        txinfos.main_wallet_id = wallet.id
        wallet_functions.signals.open_tx_like.emit(txinfos)
