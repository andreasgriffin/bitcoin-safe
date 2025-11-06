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

from bitcoin_safe.gui.qt.my_treeview import MyTreeView
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.gui.qt.ui_tx.ui_tx_creator import UITx_Creator
from bitcoin_safe.html_utils import html_f
from bitcoin_safe.signals import WalletFunctions

from .search_tree_view import ResultItem, SearchTreeView, format_result_text

logger = logging.getLogger(__name__)


# -----------------------------


class SearchWallets(SearchTreeView):
    def __init__(self, wallet_functions: WalletFunctions, parent=None, search_box_on_bottom=True) -> None:
        """Initialize instance."""
        super().__init__(
            self.do_search,
            parent=parent,
            on_click=self.search_result_on_click,
            search_box_on_bottom=search_box_on_bottom,
        )
        self.wallet_functions = wallet_functions

        self.updateUi()

        self.wallet_functions.signals.language_switch.connect(self.updateUi)

    def updateUi(self):
        """UpdateUi."""
        super().updateUi()

    def search_result_on_click(self, result_item: ResultItem) -> None:
        # call the parent action first
        """Search result on click."""
        if result_item.parent is not None:
            self.search_result_on_click(result_item.parent)

        if isinstance(result_item.obj, MyTreeView):
            if result_item.obj_key is not None:
                result_item.obj.select_row_by_clipboard(result_item.obj_key, scroll_to_last=True)
        # elif isinstance(result_item.obj, (SearchableTab)):
        #     if (parent := result_item.obj.parent()) and  isinstance((tabs := parent.parent()), QTabWidget):
        #         tabs.setCurrentWidget(result_item.obj)
        if isinstance(result_item.obj, SidebarNode) and result_item.obj.parent_node:
            result_item.obj.parent_node.setCurrentNode(result_item.obj)

            if isinstance(result_item.obj.data, UITx_Creator):
                result_item.obj.data.set_utxo_list_visible(True)

    def do_search(self, search_text: str) -> ResultItem:
        """Do search."""
        search_text = search_text.strip()
        root = ResultItem("")
        qt_wallets: list[QTWallet] = list(self.wallet_functions.get_qt_wallets.emit().values())
        for qt_wallet in qt_wallets:
            wallet_item = ResultItem(
                html_f(qt_wallet.wallet.id, bf=True), icon=qt_wallet.tabs.icon, obj=qt_wallet
            )

            # tx
            wallet_tx_ids = ResultItem(
                qt_wallet.hist_node.title,
                icon=qt_wallet.hist_node.icon,
                obj=qt_wallet.hist_node,
            )
            for txid in qt_wallet.wallet.get_dict_fulltxdetail().keys():
                if search_text in txid:
                    ResultItem(
                        format_result_text(full_text=txid, search_text=search_text),
                        parent=wallet_tx_ids,
                        obj=qt_wallet.history_list,
                        obj_key=txid,
                    )
                    # connect also the higher parents, so the results appear at all
                    wallet_tx_ids.set_parent(wallet_item)
                    wallet_item.set_parent(root)
                label = qt_wallet.wallet.get_label_for_txid(txid, autofill_from_addresses=False)
                if label and (search_text.lower() in label.lower()):
                    ResultItem(
                        format_result_text(full_text=label, search_text=search_text),
                        parent=wallet_tx_ids,
                        obj=qt_wallet.history_list,
                        obj_key=txid,
                    )
                    # connect also the higher parents, so the results appear at all
                    wallet_tx_ids.set_parent(wallet_item)
                    wallet_item.set_parent(root)

            # addresses
            wallet_addresses = ResultItem(
                qt_wallet.address_node.title,
                icon=qt_wallet.address_node.icon,
                obj=qt_wallet.address_node,
            )
            for address in qt_wallet.wallet.get_addresses():
                if search_text in address:
                    ResultItem(
                        format_result_text(full_text=address, search_text=search_text),
                        parent=wallet_addresses,
                        obj=qt_wallet.address_list,
                        obj_key=address,
                    )
                    # connect also the higher parents, so the results appear at all
                    wallet_addresses.set_parent(wallet_item)
                    wallet_item.set_parent(root)
                label = qt_wallet.wallet.get_label_for_address(address, autofill_from_txs=False)
                if label and (search_text.lower() in label.lower()):
                    ResultItem(
                        format_result_text(full_text=label, search_text=search_text),
                        parent=wallet_addresses,
                        obj=qt_wallet.address_list,
                        obj_key=address,
                    )
                    # connect also the higher parents, so the results appear at all
                    wallet_addresses.set_parent(wallet_item)
                    wallet_item.set_parent(root)

            # utxos
            wallet_utxos = ResultItem(
                html_f(self.tr("UTXOs"), bf=True),
                icon=qt_wallet.send_node.icon,
                obj=qt_wallet.send_node,
            )
            wallet_txos = ResultItem(
                html_f(self.tr("Spent Outputs"), bf=True),
                icon=qt_wallet.hist_node.icon,
                obj=qt_wallet.hist_node,
            )
            for pythonutxo in qt_wallet.wallet.get_all_txos_dict().values():
                outpoint_str = str(pythonutxo.outpoint)
                if search_text in outpoint_str:
                    if pythonutxo.is_spent_by_txid:
                        ResultItem(
                            format_result_text(full_text=outpoint_str, search_text=search_text),
                            parent=wallet_txos,
                            obj=qt_wallet.history_list,
                            obj_key=pythonutxo.is_spent_by_txid,
                        )
                        # connect also the higher parents, so the results appear at all
                        wallet_txos.set_parent(wallet_item)
                        wallet_item.set_parent(root)
                    else:
                        ResultItem(
                            format_result_text(full_text=outpoint_str, search_text=search_text),
                            parent=wallet_utxos,
                            obj=qt_wallet.uitx_creator.utxo_list,
                            obj_key=outpoint_str,
                        )
                        # connect also the higher parents, so the results appear at all
                        wallet_utxos.set_parent(wallet_item)
                        wallet_item.set_parent(root)

        return root
