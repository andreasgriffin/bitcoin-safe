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

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.tx import HiddenTxUiInfos, PostCreateEnum, TxBuilderInfos, TxUiInfos


def _make_builder_infos(hidden_tx_infos: HiddenTxUiInfos | None) -> TxBuilderInfos:
    tx = SimpleNamespace(output=lambda: [], compute_txid=lambda: "txid")
    psbt = SimpleNamespace(extract_tx=lambda: tx)
    return TxBuilderInfos(
        recipients=[],
        utxos_for_input=[],
        psbt=psbt,
        hidden_tx_infos=hidden_tx_infos,
    )


def _make_qt_wallet(builder_infos: TxBuilderInfos) -> SimpleNamespace:
    finished_psbt_creation = SimpleNamespace(emit=Mock())
    wallet_signals = SimpleNamespace(
        updated=SimpleNamespace(emit=Mock()), finished_psbt_creation=finished_psbt_creation
    )
    fake_wallet = SimpleNamespace(
        create_psbt=lambda _txinfos: builder_infos,
        network=SimpleNamespace(),
        loop_in_thread=SimpleNamespace(
            run_task=lambda task, on_done, on_success, on_error, key, multiple_strategy: on_done(  # noqa: ARG005
                asyncio.run(task)
            )
        ),
    )
    return SimpleNamespace(
        wallet=fake_wallet,
        wallet_functions=SimpleNamespace(),
        wallet_signals=wallet_signals,
        signal_psbt_created=SimpleNamespace(emit=Mock()),
        signals=SimpleNamespace(open_tx_like=SimpleNamespace(emit=Mock())),
        uitx_creator=SimpleNamespace(clear_ui=Mock()),
    )


def test_create_psbt_opens_tab_by_default() -> None:
    builder_infos = _make_builder_infos(hidden_tx_infos=None)
    qt_wallet = _make_qt_wallet(builder_infos)
    txinfos = TxUiInfos()

    with patch("bitcoin_safe.gui.qt.qt_wallet.get_wallets", return_value=[]):
        QTWallet.create_psbt(qt_wallet, txinfos)

    assert builder_infos.hidden_tx_infos == txinfos.hidden
    qt_wallet.signal_psbt_created.emit.assert_called_once_with(builder_infos)
    qt_wallet.signals.open_tx_like.emit.assert_called_once_with(builder_infos)
    qt_wallet.uitx_creator.clear_ui.assert_called_once()
    qt_wallet.wallet_signals.finished_psbt_creation.emit.assert_called_once_with()


def test_create_psbt_can_skip_tab_opening() -> None:
    hidden = HiddenTxUiInfos(post_create_action=PostCreateEnum.no_action)
    builder_infos = _make_builder_infos(hidden_tx_infos=hidden)
    qt_wallet = _make_qt_wallet(builder_infos)

    with patch("bitcoin_safe.gui.qt.qt_wallet.get_wallets", return_value=[]):
        QTWallet.create_psbt(qt_wallet, TxUiInfos())

    qt_wallet.signal_psbt_created.emit.assert_called_once_with(builder_infos)
    qt_wallet.signals.open_tx_like.emit.assert_not_called()
    qt_wallet.uitx_creator.clear_ui.assert_called_once()
    qt_wallet.wallet_signals.finished_psbt_creation.emit.assert_called_once_with()
