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

from unittest.mock import Mock

import bdkpython as bdk
import pytest
from PyQt6 import sip
from PyQt6.QtCore import Qt
from pytestqt.qtbot import QtBot

from bitcoin_safe.category_info import CategoryInfo
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.gui.qt.category_manager.category_list import CategoryList, CategoryListWithToolbar
from bitcoin_safe.gui.qt.category_manager.category_manager import CategoryManager
from bitcoin_safe.gui.qt.ui_tx.recipients import RecipientWidget
from bitcoin_safe.gui.qt.utxo_list import UTXOList, UtxoListWithToolbar
from bitcoin_safe.signals import Signals, UpdateFilter, WalletFunctions, WalletSignals
from bitcoin_safe.wallet import Wallet
from tests.helpers import TestConfig as ConfigForTest


def test_closing_recipient_disconnects_label_editor(qtbot: QtBot) -> None:
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    first = RecipientWidget(fx=None, wallet_functions=wallet_functions, network=bdk.Network.REGTEST)
    second = RecipientWidget(fx=None, wallet_functions=wallet_functions, network=bdk.Network.REGTEST)
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    initial_receivers = signals.receivers(signals.any_wallet_updated)

    first.close()
    assert signals.receivers(signals.any_wallet_updated) == initial_receivers - 2
    sip.delete(first.label_line_edit.category_edit)
    signals.any_wallet_updated.emit(UpdateFilter(refresh_all=True))
    assert second.label_line_edit.category() == ""

    second.close()
    assert signals.receivers(signals.any_wallet_updated) == 0


@pytest.mark.parametrize("list_type", ["utxo", "category"])
def test_closing_list_toolbar_disconnects_wallet_and_fx_signals(qtbot: QtBot, list_type: str) -> None:
    config = ConfigForTest()
    signals = Signals()
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    if list_type == "utxo":
        tree = UTXOList(config=config, wallet_functions=WalletFunctions(signals), outpoints=[], fx=fx)
        toolbar = UtxoListWithToolbar(tree, config)
    else:
        tree = CategoryList(config=config, fx=fx, category_core=None, signals=signals)
        toolbar = CategoryListWithToolbar(tree, config)
    qtbot.addWidget(toolbar)

    assert signals.receivers(signals.any_wallet_updated) == 2
    assert fx.receivers(fx.signal_data_updated) == 1
    toolbar.close()
    assert signals.receivers(signals.any_wallet_updated) == 0
    assert signals.receivers(signals.language_switch) == 0
    assert signals.receivers(signals.currency_switch) == 0
    assert fx.receivers(fx.signal_data_updated) == 0
    signals.any_wallet_updated.emit(UpdateFilter(refresh_all=True))
    fx.signal_data_updated.emit()
    fx.close()


@pytest.mark.parametrize(
    "key, modifiers",
    [
        (Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier),
    ],
)
def test_category_manager_can_reopen_after_shortcut(
    qtbot: QtBot, key: Qt.Key, modifiers: Qt.KeyboardModifier
) -> None:
    config = ConfigForTest()
    signals = Signals()
    wallet_signals = WalletSignals()
    wallet = Mock(spec=Wallet)
    wallet.id = "test"
    wallet.network = bdk.Network.REGTEST
    categories = [CategoryInfo("first", 0, 0, 0, 0, 0)]
    wallet_signals.get_category_infos.connect(lambda: categories)
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    core = CategoryCore(wallet=wallet, signals=signals, wallet_signals=wallet_signals)
    manager = CategoryManager(config=config, fx=fx, category_core=core, wallet_id=wallet.id)
    qtbot.addWidget(manager)
    manager.show()
    qtbot.waitUntil(manager.isVisible)
    manager.activateWindow()
    qtbot.waitUntil(manager.isActiveWindow)
    qtbot.keyClick(manager, key, modifier=modifiers)
    qtbot.waitUntil(manager.isHidden)

    manager.show()
    qtbot.waitUntil(manager.isVisible)
    assert manager.category_list_with_toolbar.parent() is manager
    assert manager.category_list_with_toolbar.searchable_list is manager.category_list
    categories.append(CategoryInfo("second", 0, 0, 0, 0, 0))
    signals.any_wallet_updated.emit(UpdateFilter(refresh_all=True))
    assert manager.category_list.model().rowCount() == 2

    manager.close()
    assert manager.isHidden()
    assert signals.receivers(signals.any_wallet_updated) == 0
    assert fx.receivers(fx.signal_data_updated) == 0
    fx.close()


@pytest.mark.parametrize("tx_type", ["creator", "viewer"])
def test_transaction_widget_disconnects_updates_on_close(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tx_type: str
) -> None:
    from bitcoin_qr_tools.data import Data, DataType

    from bitcoin_safe.gui.qt.qt_wallet import create_tx_viewer
    from bitcoin_safe.gui.qt.ui_tx.ui_tx_creator import UITx_Creator
    from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
    from bitcoin_safe.mempool_manager import MempoolManager
    from tests.non_gui.test_psbt_util import p2wsh_psbt_0_1of1

    config = ConfigForTest()
    config.network = bdk.Network.REGTEST
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    mempool = MempoolManager(config.network_config, signals, None)
    widget_class = UITx_Creator if tx_type == "creator" else UITx_Viewer
    calls: list[UITx_Creator | UITx_Viewer] = []
    original_update = widget_class.update_all_totals

    def record_update(widget: UITx_Creator | UITx_Viewer) -> None:
        calls.append(widget)
        original_update(widget)

    monkeypatch.setattr(widget_class, "update_all_totals", record_update)
    if tx_type == "creator":
        widget = UITx_Creator(mempool, fx, config, wallet_functions)
    else:
        data = Data(p2wsh_psbt_0_1of1, DataType.PSBT, bdk.Network.REGTEST)
        widget = create_tx_viewer(
            config, wallet_functions, fx, mempool, bdk.Network.REGTEST, data, [], None, None
        )
    qtbot.addWidget(widget)
    calls.clear()
    signals.currency_switch.emit()
    assert calls == [widget]
    calls.clear()
    if isinstance(widget, UITx_Viewer):
        original_close = widget.label_line_edit.close

        def close_label() -> bool:
            signals.currency_switch.emit()
            widget.utxo_list.signal_finished_update.emit()
            return original_close()

        monkeypatch.setattr(widget.label_line_edit, "close", close_label)
    widget.close()
    assert calls == []
    calls.clear()
    signals.currency_switch.emit()
    assert calls == []
    mempool.close()
    fx.close()
