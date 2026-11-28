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

import bdkpython as bdk
import pytest
from PyQt6 import sip
from pytestqt.qtbot import QtBot

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_list import CategoryList, CategoryListWithToolbar
from bitcoin_safe.gui.qt.ui_tx.recipients import RecipientWidget
from bitcoin_safe.gui.qt.utxo_list import UTXOList, UtxoListWithToolbar
from bitcoin_safe.signals import Signals, UpdateFilter, WalletFunctions
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
