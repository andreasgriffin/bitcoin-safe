#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
#

from unittest.mock import Mock

import pytest

from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason
from bitcoin_safe.tx import TxUiInfos
from bitcoin_safe.wallet import TxConfirmationStatus, TxStatus


def test_psbt_viewer_only_updates_tab_properties_on_chain_height() -> None:
    psbt_status = TxStatus(
        tx=None,
        chain_position=None,
        get_height=lambda: 0,
        fallback_confirmation_status=TxConfirmationStatus.PSBT,
    )
    viewer = Mock()
    viewer.chain_position = None
    viewer.get_tx_status.return_value = psbt_status

    UITx_Viewer.reload(
        viewer,
        UpdateFilter(reason=UpdateFilterReason.ChainHeightAdvanced),
    )

    viewer.set_tab_properties.assert_called_once_with(chain_position=None)
    viewer.maybe_defer_update.assert_not_called()
    viewer.set_psbt.assert_not_called()


@pytest.mark.parametrize("matched", [False, True])
def test_edit_selects_matching_wallet_or_first_open_wallet(
    monkeypatch: pytest.MonkeyPatch, matched: bool
) -> None:
    first_wallet = Mock(id="first")
    matched_wallet = Mock(id="matched")
    infos = TxUiInfos()
    viewer = Mock()
    viewer.wallet_functions.get_wallets.return_value = {"first": first_wallet, "matched": matched_wallet}
    viewer._infos_for_edit_or_rbf.return_value = ("txid", matched_wallet if matched else None, None, infos)
    status_from_wallet = Mock(return_value=Mock())
    edit_tx = Mock()
    monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.TxStatus.from_wallet", status_from_wallet)
    monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.TxTools.edit_tx", edit_tx)

    UITx_Viewer.edit(viewer)

    status_from_wallet.assert_called_once_with(
        txid="txid", wallet=matched_wallet if matched else first_wallet
    )
    assert infos.main_wallet_id == (None if matched else "first")
    assert edit_tx.call_args.kwargs["txinfos"] is infos
