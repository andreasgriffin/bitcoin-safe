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
from collections import defaultdict
from typing import Dict, List, Set

import bdkpython as bdk
from PyQt6.QtWidgets import QLayout, QVBoxLayout

from bitcoin_safe.cpfp_tools import CpfpTools
from bitcoin_safe.gui.qt.fee_group import FeeGroup, FeeRateWarningBar, FeeWarningBar
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import Recipient, TransactionDetails
from bitcoin_safe.signal_tracker import SignalTracker

from ...config import UserConfig
from ...mempool import MempoolData
from ...signals import Signals
from ...wallet import Wallet, get_wallet_of_address, get_wallets, is_local
from .my_treeview import SearchableTab
from .recipients import Recipients

logger = logging.getLogger(__name__)


class UITx_Base(SearchableTab):
    def __init__(
        self, config: UserConfig, signals: Signals, mempool_data: MempoolData, parent=None, **kwargs
    ) -> None:
        super().__init__(parent=parent, **kwargs)
        self.signal_tracker = SignalTracker()
        self.signals = signals
        self.mempool_data = mempool_data
        self.config = config

        self._layout = QVBoxLayout(self)

        self.high_fee_rate_warning_label = FeeRateWarningBar(network=self.config.network)
        self.high_fee_rate_warning_label.setHidden(True)
        self._layout.addWidget(self.high_fee_rate_warning_label)

        self.high_fee_warning_label = FeeWarningBar(network=self.config.network)
        self.high_fee_warning_label.setHidden(True)
        self._layout.addWidget(self.high_fee_warning_label)

    def create_recipients(
        self,
        layout: QLayout,
        parent=None,
        allow_edit=True,
    ) -> Recipients:
        recipients = Recipients(
            self.signals,
            network=self.config.network,
            allow_edit=allow_edit,
        )

        layout.addWidget(recipients)
        recipients.setMinimumWidth(250)
        return recipients

    @staticmethod
    def get_category_dict_of_addresses(addresses: List[str], wallets: List[Wallet]) -> Dict[str, Set[str]]:
        """_summary_

        Args:
            addresses (List[str]): _description_
            wallets (List[Wallet]): _description_

        Returns:
            Dict[str, Set[str]]: category : {wallet_id, ...}
        """
        categories: Dict[str, Set[str]] = defaultdict(set[str])
        for wallet in wallets:
            for address in addresses:
                if not wallet.is_my_address(address):
                    continue
                category = wallet.labels.get_category(address)
                if category is not None:
                    categories[category].add(wallet.id)
        return categories

    def get_unconfirmed_ancestors(
        self, txids: Set[str], wallets: List[Wallet] | None = None
    ) -> List[TransactionDetails] | None:
        wallets = wallets if wallets else get_wallets(self.signals)

        cpfp_tools = CpfpTools(wallets=wallets)
        return cpfp_tools.get_unconfirmed_ancestors(txids=txids)

    def set_fee_group_cpfp_label(
        self,
        parent_txids: Set[str],
        this_fee_info: FeeInfo,
        fee_group: FeeGroup,
        chain_position: bdk.ChainPosition | None,
    ) -> None:
        if chain_position and (chain_position.is_confirmed() or is_local(chain_position)):
            fee_group.set_cpfp_label(unconfirmed_ancestors=None, this_fee_info=this_fee_info)
            return

        unconfirmed_ancestors = self.get_unconfirmed_ancestors(txids=parent_txids)

        fee_group.set_cpfp_label(unconfirmed_ancestors=unconfirmed_ancestors, this_fee_info=this_fee_info)

    def updateUi(self) -> None:
        self.high_fee_rate_warning_label.updateUi()
        self.high_fee_warning_label.updateUi()

    def _get_total_non_change_output_amount(self, recipients: List[Recipient], wallet: Wallet | None = None):
        total_non_change_output_amount = 0
        for recipient in recipients:
            if not recipient.address:
                continue
            this_wallet = wallet if wallet else get_wallet_of_address(recipient.address, self.signals)
            if not this_wallet:
                continue
            if not (
                (address_info := this_wallet.is_my_address_with_peek(recipient.address))
                and address_info.is_change()
            ):
                total_non_change_output_amount += recipient.amount
        return total_non_change_output_amount
