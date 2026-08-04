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

from types import MethodType, SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.main import MainWindow
from bitcoin_safe.gui.qt.notification_bar import NotificationBar


def _window_stub(wallets: dict[str, SimpleNamespace], notification_bar: NotificationBar) -> SimpleNamespace:
    window = SimpleNamespace(
        qt_wallets=wallets,
        plugin_update_notification_bar=notification_bar,
    )
    window._wallet_with_plugin_updates = MethodType(MainWindow._wallet_with_plugin_updates, window)
    return window


def test_global_plugin_update_bar_aggregates_wallet_updates(qapp: QApplication) -> None:
    del qapp
    notification_bar = NotificationBar()
    first_manager = SimpleNamespace(has_plugin_updates=Mock(return_value=False))
    second_manager = SimpleNamespace(has_plugin_updates=Mock(return_value=False))
    window = _window_stub(
        wallets={
            "first": SimpleNamespace(plugin_manager=first_manager),
            "second": SimpleNamespace(plugin_manager=second_manager),
        },
        notification_bar=notification_bar,
    )

    try:
        MainWindow.refresh_plugin_update_notification_bar(window)
        assert notification_bar.isHidden()

        second_manager.has_plugin_updates.return_value = True
        MainWindow.refresh_plugin_update_notification_bar(window)

        assert not notification_bar.isHidden()
    finally:
        notification_bar.close()


def test_show_plugin_updates_selects_first_matching_wallet(qapp: QApplication) -> None:
    del qapp
    notification_bar = NotificationBar()
    first_node = SimpleNamespace(select=Mock())
    second_node = SimpleNamespace(select=Mock())
    first_manager = SimpleNamespace(
        has_plugin_updates=Mock(return_value=False),
        node=first_node,
    )
    second_manager = SimpleNamespace(
        has_plugin_updates=Mock(return_value=True),
        node=second_node,
    )
    window = _window_stub(
        wallets={
            "first": SimpleNamespace(plugin_manager=first_manager),
            "second": SimpleNamespace(plugin_manager=second_manager),
        },
        notification_bar=notification_bar,
    )

    try:
        MainWindow.show_plugin_updates(window)

        first_node.select.assert_not_called()
        second_node.select.assert_called_once_with()
    finally:
        notification_bar.close()
