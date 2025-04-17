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

from PyQt6.QtWidgets import QLayout, QVBoxLayout

from bitcoin_safe.gui.qt.fee_group import FeeRateWarningBar, FeeWarningBar
from bitcoin_safe.signal_tracker import SignalTracker

from ...config import UserConfig
from ...mempool import MempoolData
from ...signals import Signals
from ...wallet import Wallet
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
