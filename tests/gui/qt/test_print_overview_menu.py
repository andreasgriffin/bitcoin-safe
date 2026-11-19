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

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.main import MainWindow
from bitcoin_safe.gui.qt.qt_wallet import QTWallet

from .helpers import main_window_context


def test_print_and_export_menu_actions(qtbot: QtBot, test_config: UserConfig) -> None:
    selected = SimpleNamespace(wallet=object(), export_pdf_statement=Mock())
    with (
        patch("bitcoin_safe.gui.qt.main.get_wallets", return_value=[selected.wallet]),
        patch("bitcoin_safe.gui.qt.main.InheritanceOverviewPDF") as pdf,
        patch("bitcoin_safe.gui.qt.main.write_and_open_temp_pdf") as open_pdf,
        main_window_context(test_config) as window,
    ):
        qtbot.addWidget(window)
        assert window.menu_action_print_overview.text() == "Print overview"
        assert window.menu_action_export_inheritance_overview.text() == "Inheritance overview"
        assert window.menu_action_export_balance_statement.text() == "Balance statement"
        assert window.menu_action_print_overview.shortcut().toString() == "Ctrl+P"
        assert window.menu_action_export_balance_statement in window.menu_wallet_export.actions()
        with patch.object(window, "get_qt_wallet", return_value=selected):
            window.menu_action_print_overview.trigger()
            window.menu_action_export_inheritance_overview.trigger()
            window.menu_action_export_balance_statement.trigger()
        assert pdf.call_count == 2
        assert open_pdf.call_count == 2
        selected.export_pdf_statement.assert_called_once_with()


def test_balance_statement_uses_selected_wallet() -> None:
    selected = SimpleNamespace(wallet=object(), export_pdf_statement=Mock())
    window = cast(MainWindow, SimpleNamespace(get_qt_wallet=Mock(return_value=selected)))
    MainWindow.export_balance_statement(window)
    selected.export_pdf_statement.assert_called_once_with()


def test_balance_statement_does_not_require_sync_plugin() -> None:
    active_wallet = SimpleNamespace(id="wallet")
    qt_wallet = cast(QTWallet, SimpleNamespace(wallet=active_wallet, plugin_manager=None))
    with patch("bitcoin_safe.gui.qt.qt_wallet.make_and_open_pdf_statement") as make_pdf:
        QTWallet.export_pdf_statement(qt_wallet)
    assert make_pdf.call_args.args == (active_wallet,)
