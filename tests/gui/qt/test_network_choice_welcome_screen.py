#
# Bitcoin Safe
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

from pathlib import Path
from unittest.mock import Mock

import bdkpython as bdk
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.main import should_show_network_choice_welcome_screen

from ...helpers import TestConfig
from .helpers import main_window_context


def _set_mainnet(config: TestConfig) -> None:
    config.network = bdk.Network.BITCOIN
    Path(config.wallet_dir).mkdir(parents=True, exist_ok=True)


def _add_recent_wallet(config: TestConfig, wallet_name: str = "existing.wallet") -> str:
    wallet_path = Path(config.wallet_dir) / wallet_name
    wallet_path.touch()
    config.add_recently_open_wallet(str(wallet_path))
    return str(wallet_path)


def _disable_p2p_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bitcoin_safe.gui.qt.main.delayed_execution", lambda f, parent, delay=10: None)
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.main.MainWindow.init_p2p_listening",
        lambda self: setattr(self, "p2p_listener", None),
    )


def test_should_show_network_choice_welcome_screen_on_mainnet_without_recent_wallets(
    test_config_main_chain: TestConfig,
) -> None:
    _set_mainnet(test_config_main_chain)

    assert should_show_network_choice_welcome_screen(test_config_main_chain) is True


def test_should_not_show_network_choice_welcome_screen_when_mainnet_has_recent_wallets(
    test_config_main_chain: TestConfig,
) -> None:
    _set_mainnet(test_config_main_chain)
    _add_recent_wallet(test_config_main_chain)

    assert should_show_network_choice_welcome_screen(test_config_main_chain) is False


def test_should_not_show_network_choice_welcome_screen_on_signet(
    test_config_main_chain: TestConfig,
) -> None:
    test_config_main_chain.network = bdk.Network.SIGNET

    assert should_show_network_choice_welcome_screen(test_config_main_chain) is False


@pytest.mark.marker_qt_1
def test_load_last_state_shows_network_choice_screen_for_mainnet_first_run(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    _set_mainnet(test_config_main_chain)
    _disable_p2p_init(monkeypatch)

    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore

        main_window.load_last_state()

        assert main_window.tab_wallets.root.findNodeByWidget(main_window.network_choice_welcome_screen)
        assert not main_window.tab_wallets.root.findNodeByWidget(main_window.welcome_screen)


@pytest.mark.marker_qt_1
def test_load_last_state_shows_existing_welcome_screen_when_mainnet_has_recent_wallets(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp, qtbot
    _set_mainnet(test_config_main_chain)
    _add_recent_wallet(test_config_main_chain)
    _disable_p2p_init(monkeypatch)

    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore

        main_window.load_last_state()

        assert main_window.tab_wallets.root.findNodeByWidget(main_window.welcome_screen)
        assert not main_window.tab_wallets.root.findNodeByWidget(main_window.network_choice_welcome_screen)


@pytest.mark.marker_qt_1
def test_new_wallet_shows_network_choice_screen_for_mainnet_first_run(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp, qtbot
    _set_mainnet(test_config_main_chain)
    _disable_p2p_init(monkeypatch)

    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore

        main_window.new_wallet()

        assert main_window.tab_wallets.root.findNodeByWidget(main_window.network_choice_welcome_screen)
        assert not main_window.tab_wallets.root.findNodeByWidget(main_window.welcome_screen)


@pytest.mark.marker_qt_1
def test_network_choice_secure_wallet_opens_existing_welcome_screen(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    _set_mainnet(test_config_main_chain)
    _disable_p2p_init(monkeypatch)

    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore

        main_window.new_wallet()
        qtbot.mouseClick(
            main_window.network_choice_welcome_screen.card_secure_wallet,
            Qt.MouseButton.LeftButton,
        )

        assert main_window.tab_wallets.root.findNodeByWidget(main_window.welcome_screen)
        assert not main_window.tab_wallets.root.findNodeByWidget(main_window.network_choice_welcome_screen)
        assert main_window.welcome_screen.wallet_name == main_window.make_default_wallet_id()


@pytest.mark.marker_qt_1
def test_network_choice_safe_playground_restarts_into_signet(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    _set_mainnet(test_config_main_chain)
    _disable_p2p_init(monkeypatch)

    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        restart_mock = Mock()
        monkeypatch.setattr(main_window, "restart", restart_mock)

        main_window.new_wallet()
        qtbot.mouseClick(
            main_window.network_choice_welcome_screen.card_safe_playground,
            Qt.MouseButton.LeftButton,
        )

        restart_mock.assert_called_once_with(new_startup_network=bdk.Network.SIGNET)
