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
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalTracker
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout

from bitcoin_safe.cpfp_tools import CpfpTools
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.ui_tx.fee_group import (
    FeeGroup,
    FeeRateWarningBar,
    FeeWarningBar,
)
from bitcoin_safe.gui.qt.ui_tx.recipients import Recipients
from bitcoin_safe.gui.qt.ui_tx.util import get_rbf_fee_label
from bitcoin_safe.gui.qt.util import adjust_bg_color_for_darkmode
from bitcoin_safe.gui.qt.warning_bars import LinkingWarningBar
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.pythonbdk_types import OutPoint, Recipient, TransactionDetails

from ....config import UserConfig
from ....mempool_manager import MempoolManager
from ....signals import WalletFunctions
from ....wallet import TxStatus, Wallet, get_wallet_of_address, get_wallets, is_local
from ..my_treeview import SearchableTab
from .util import get_cpfp_label

logger = logging.getLogger(__name__)


class RBFBar(NotificationBar):
    def __init__(
        self,
        network: bdk.Network,
        text: str = "",
        optional_button_text: str | None = None,
        callback_optional_button: Callable[..., Any] | None = None,
        has_close_button: bool = True,
        parent=None,
    ) -> None:
        super().__init__(text, optional_button_text, callback_optional_button, has_close_button, parent)

        self.network = network
        self.setVisible(False)
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("lightblue")))

    def set_infos(
        self, conflicing_txids: set[str], current_fee: FeeInfo | None, min_fee_rate: float | None
    ) -> None:
        self.setVisible(min_fee_rate is not None)

        if min_fee_rate is None:
            return

        url, tooltip = get_rbf_fee_label(
            conflicing_txids=conflicing_txids,
            min_fee_rate=min_fee_rate,
            current_fee=current_fee,
            network=self.network,
        )

        self.icon_label.set_icon_as_help(tooltip="", click_url=url)
        self.icon_label.setText(tooltip)


class CPFPBar(NotificationBar):
    def __init__(
        self,
        network: bdk.Network,
        text: str = "",
        optional_button_text: str | None = None,
        callback_optional_button: Callable[..., Any] | None = None,
        has_close_button: bool = True,
        parent=None,
    ) -> None:
        super().__init__(text, optional_button_text, callback_optional_button, has_close_button, parent)

        self.network = network
        self.setVisible(False)
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("lightblue")))

    def set_infos(
        self,
        this_fee_info: FeeInfo,
        unconfirmed_parents_fee_info: FeeInfo | None,
        unconfirmed_ancestors: dict[str, TransactionDetails],
    ) -> None:
        if not this_fee_info or not unconfirmed_parents_fee_info:
            self.setVisible(False)
            return

        combined_fee_info = this_fee_info + unconfirmed_parents_fee_info
        url, tooltip = get_cpfp_label(
            unconfirmed_parents_fee_info=unconfirmed_parents_fee_info,
            combined_fee_info=combined_fee_info,
            unconfirmed_ancestors=unconfirmed_ancestors,
            network=self.network,
        )

        self.setVisible(bool(unconfirmed_ancestors))
        if unconfirmed_ancestors:
            self.icon_label.set_icon_as_help(tooltip="", click_url=url)
            self.icon_label.setText(tooltip)


class UITx_Base(SearchableTab):
    def __init__(
        self,
        fx: FX,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        mempool_manager: MempoolManager,
        parent=None,
        **kwargs,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, **kwargs)
        self.fx = fx
        self.signal_tracker = SignalTracker()
        self.loop_in_thread = mempool_manager.loop_in_thread
        self._owns_loop_in_thread = False
        self.wallet_functions = wallet_functions
        self.signals = wallet_functions.signals
        self.mempool_manager = mempool_manager
        self.config = config

        self._layout = QVBoxLayout(self)

        self.high_fee_rate_warning_label = FeeRateWarningBar(network=self.config.network)
        self.high_fee_rate_warning_label.setHidden(True)
        self._layout.addWidget(self.high_fee_rate_warning_label)

        self.high_fee_warning_label = FeeWarningBar(
            network=self.config.network, btc_symbol=self.fx.config.bitcoin_symbol.value
        )
        self.high_fee_warning_label.setHidden(True)
        self._layout.addWidget(self.high_fee_warning_label)

        # category_linking_warning_bar
        self.category_linking_warning_bar = LinkingWarningBar(signals_min=self.signals)
        self._layout.addWidget(self.category_linking_warning_bar)

        self.rbf_bar = RBFBar(network=self.config.network, text="")
        self._layout.addWidget(self.rbf_bar)

        self.cpfp_bar = CPFPBar(network=self.config.network, text="")
        self._layout.addWidget(self.cpfp_bar)

    def _get_robust_height(self) -> int:
        "Tries to geth the height from any wallet.  If none are open then tries mempool"
        for wallet in get_wallets(self.wallet_functions):
            height = wallet.get_height()
            logger.debug(f"_get_robust_height {height=} from wallet {wallet.id}")
            return height

        height = self.mempool_manager.fetch_block_tip_height()
        logger.debug(f"_get_robust_height {height=} from mempool_manager")
        return height

    @staticmethod
    def get_category_dict_of_addresses(addresses: list[str], wallets: list[Wallet]) -> dict[str, set[str]]:
        """_summary_

        Args:
            addresses (List[str]): _description_
            wallets (List[Wallet]): _description_

        Returns:
            Dict[str, Set[str]]: category : {wallet_id, ...}
        """
        categories: dict[str, set[str]] = defaultdict(set[str])
        for wallet in wallets:
            for address in addresses:
                if not wallet.is_my_address(address):
                    continue
                category = wallet.labels.get_category(address)
                if category is not None:
                    categories[category].add(wallet.id)
        return categories

    def get_unconfirmed_ancestors(
        self, txids: set[str], wallets: list[Wallet] | None = None
    ) -> dict[str, TransactionDetails]:
        """Get unconfirmed ancestors."""
        wallets = wallets if wallets else get_wallets(self.wallet_functions)

        cpfp_tools = CpfpTools(wallets=wallets)
        return cpfp_tools.get_unconfirmed_ancestors(txids=txids, known_ancestors={})

    def set_cpfp_labels(
        self,
        parent_txids: set[str],
        this_fee_info: FeeInfo,
        fee_group: FeeGroup,
        chain_position: bdk.ChainPosition | None,
    ) -> None:
        """Set fee group cpfp label."""
        if chain_position and (chain_position.is_confirmed() or is_local(chain_position)):
            fee_group.set_cpfp_label(
                this_fee_info=this_fee_info, unconfirmed_parents_fee_info=None, unconfirmed_ancestors={}
            )
            self.cpfp_bar.setVisible(False)
            return

        unconfirmed_ancestors = self.get_unconfirmed_ancestors(txids=parent_txids)
        unconfirmed_parents_fee_info = (
            FeeInfo.combined_fee_info(txs=unconfirmed_ancestors.values()) if unconfirmed_ancestors else None
        )

        # fee group
        if not unconfirmed_ancestors or not unconfirmed_parents_fee_info:
            fee_group.set_cpfp_label(
                this_fee_info=this_fee_info, unconfirmed_parents_fee_info=None, unconfirmed_ancestors={}
            )
            self.cpfp_bar.setVisible(False)
            return

        fee_group.set_cpfp_label(
            this_fee_info=this_fee_info,
            unconfirmed_ancestors=unconfirmed_ancestors,
            unconfirmed_parents_fee_info=unconfirmed_parents_fee_info,
        )
        self.cpfp_bar.set_infos(
            this_fee_info=this_fee_info,
            unconfirmed_ancestors=unconfirmed_ancestors,
            unconfirmed_parents_fee_info=unconfirmed_parents_fee_info,
        )

    def updateUi(self) -> None:
        """UpdateUi."""
        self.high_fee_rate_warning_label.updateUi()
        self.high_fee_warning_label.updateUi()
        self.category_linking_warning_bar.updateUi()

    def _get_total_non_change_output_amount(self, recipients: list[Recipient], wallet: Wallet | None = None):
        """Get total non change output amount."""
        total_amount = 0
        change_amount = 0
        for recipient in recipients:
            total_amount += recipient.amount

            if not recipient.address:
                continue

            this_wallet = (
                wallet if wallet else get_wallet_of_address(recipient.address, self.wallet_functions)
            )
            if not this_wallet:
                continue

            if not (address_info := this_wallet.is_my_address_with_peek(recipient.address)):
                continue

            if address_info.is_change():
                change_amount += recipient.amount
                continue

        return total_amount - change_amount

    def set_category_warning_bar(self, outpoints: list[OutPoint], recipient_addresses: list[str]):
        # warn if multiple categories are combined
        """Set category warning bar."""
        wallets: list[Wallet] = list(self.wallet_functions.get_wallets.emit().values())

        category_dict: dict[str, set[str]] = defaultdict(set[str])
        for wallet in wallets:
            addresses = [
                wallet.get_address_of_outpoint(outpoint) for outpoint in outpoints
            ] + recipient_addresses
            this_category_dict = self.get_category_dict_of_addresses(
                [address for address in addresses if address], wallets=[wallet]
            )
            for k, v in this_category_dict.items():
                category_dict[k].update(v)

        self.category_linking_warning_bar.set_category_dict(category_dict)

    def _set_warning_bars(
        self,
        outpoints: list[OutPoint],
        recipient_addresses: list[str],
        tx_status: TxStatus,
    ):
        """Set warning bars."""
        self.set_category_warning_bar(outpoints=outpoints, recipient_addresses=recipient_addresses)

    def _update_high_fee_warning_label(
        self, recipients: Recipients, fee_info: FeeInfo | None, tx_status: TxStatus
    ):
        """Update high fee warning label."""
        total_non_change_output_amount = self._get_total_non_change_output_amount(
            recipients=recipients.recipients
        )

        self.high_fee_warning_label.set_fee_to_send_ratio(
            fee_info=fee_info,
            total_non_change_output_amount=total_non_change_output_amount,
            network=self.config.network,
            # if checked_max_amount, then the user might not notice a 0 output amount,
            # and i better show a warning
            force_show_fee_warning_on_0_amont=any([r.checked_max_amount for r in recipients.recipients]),
            tx_status=tx_status,
        )

    def close(self) -> bool:
        """Close."""
        if self._owns_loop_in_thread:
            self.loop_in_thread.stop()
        return super().close()
