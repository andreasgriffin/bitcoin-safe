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

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from bitcoin_safe_lib.storage import Storage
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.loading_wallet_tab import LoadingWalletTab
from bitcoin_safe.gui.qt.qt_wallet import QTWallet

from ...helpers import TestConfig
from .helpers import main_window_context


def _stack_widgets(main_window) -> list:
    """All widgets registered in the sidebar's shared stack."""
    stack = main_window.tab_wallets.stack
    return [stack.widget(i) for i in range(stack.count())]


def _count_loading_tabs(main_window) -> int:
    return sum(isinstance(widget, LoadingWalletTab) for widget in _stack_widgets(main_window))


@pytest.mark.marker_qt_2
def test_loading_widgets_do_not_accumulate_across_open_close_cycles(
    qapp: QApplication,
    qtbot: QtBot,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opening and closing wallets, including cancelled and wrong password attempts,
    must not leave LoadingWalletTab widgets behind in the sidebar stack."""
    from bitcoin_safe.gui.qt import main as main_module

    monkeypatch.setattr(
        main_module,
        "Message",
        lambda *args, **kwargs: type("M", (), {"show": lambda self: None})(),
    )

    wallet_src = Path("tests") / "data" / "0.2.0.wallet"
    with main_window_context(test_config=test_config) as main_window:
        baseline_stack_size = main_window.tab_wallets.stack.count()

        for cycle in range(3):
            temp_path = Path(tempfile.mkdtemp()) / f"0.2.0-{cycle}.wallet"
            shutil.copy(str(wallet_src), str(temp_path))

            qt_wallet = main_window.open_wallet(str(temp_path))
            assert isinstance(qt_wallet, QTWallet)
            assert _count_loading_tabs(main_window) == 0

            node = main_window.tab_wallets.root.findNodeByTitle(qt_wallet.wallet.id)
            assert node
            main_window.close_tab(node)
            QApplication.processEvents()
            assert _count_loading_tabs(main_window) == 0

        # a cancelled password prompt must also clean up its loading tab
        encrypted_path = Path(tempfile.mkdtemp()) / "encrypted.wallet"
        shutil.copy(str(wallet_src), str(encrypted_path))
        with (
            patch.object(Storage, "has_password", return_value=True),
            patch("bitcoin_safe.gui.qt.main.PasswordQuestion") as password_question,
        ):
            password_question.return_value.ask_for_password.return_value = None
            assert main_window.open_wallet(str(encrypted_path)) is None
        QApplication.processEvents()
        assert _count_loading_tabs(main_window) == 0

        # no temporary widget may stay registered after all cycles
        assert main_window.tab_wallets.stack.count() <= baseline_stack_size + 1


@pytest.mark.marker_qt_2
def test_loading_widget_qobject_is_destroyed_after_exit(
    qapp: QApplication,
    qtbot: QtBot,
    test_config: TestConfig,
) -> None:
    """After exit the loading widget is hidden, detached from its stack and no longer in the sidebar."""
    with main_window_context(test_config=test_config) as main_window:
        stack = main_window.tab_wallets.stack
        loading_tab = LoadingWalletTab(main_window.tab_wallets, "temporary", focus=False)
        with loading_tab:
            assert main_window.tab_wallets.root.findNodeByWidget(loading_tab) is not None
            assert not sip.isdeleted(loading_tab)

        assert main_window.tab_wallets.root.findNodeByWidget(loading_tab) is None
        assert stack.indexOf(loading_tab) == -1
        assert loading_tab.isHidden()
        assert loading_tab.parent() is None


@pytest.mark.marker_qt_2
def test_open_wallet_leaves_no_live_loading_widgets(
    qapp: QApplication,
    qtbot: QtBot,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every LoadingWalletTab created while opening a wallet must be destroyed afterwards."""
    from bitcoin_safe.gui.qt import main as main_module

    created: list[LoadingWalletTab] = []
    original_init = LoadingWalletTab.__init__

    def tracking_init(self: LoadingWalletTab, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(LoadingWalletTab, "__init__", tracking_init)
    monkeypatch.setattr(
        main_module,
        "Message",
        lambda *args, **kwargs: type("M", (), {"show": lambda self: None})(),
    )

    wallet_src = Path("tests") / "data" / "0.2.0.wallet"
    temp_path = Path(tempfile.mkdtemp()) / "0.2.0-lifetime.wallet"
    shutil.copy(str(wallet_src), str(temp_path))
    with main_window_context(test_config=test_config) as main_window:
        created.clear()
        qt_wallet = main_window.open_wallet(str(temp_path))
        assert isinstance(qt_wallet, QTWallet)
        assert len(created) == 1  # one placeholder for the whole open_wallet() operation

        for tab in created:
            assert tab.isHidden()
            assert tab.parent() is None
            assert main_window.tab_wallets.stack.indexOf(tab) == -1
