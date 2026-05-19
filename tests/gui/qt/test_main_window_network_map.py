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

from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.initial_cbf_sync_widget import NetworkMapWidget

from ...helpers import TestConfig
from .helpers import main_window_context


def test_network_map_tool_tab_is_lazy_and_reusable(qtbot: QtBot, test_config: TestConfig) -> None:
    with main_window_context(test_config=test_config) as main_window:
        assert main_window.global_network_map_widget is None

        main_window.open_network_map()
        QApplication.processEvents()

        first_widget = main_window.global_network_map_widget
        assert isinstance(first_widget, NetworkMapWidget)
        assert main_window.global_network_map_node is not None
        assert main_window.tab_wallets.root.findNodeByWidget(first_widget) is not None

        main_window.open_network_map()
        QApplication.processEvents()

        assert main_window.global_network_map_widget is first_widget
        assert [node for node in main_window.tab_wallets.roots if node.widget is first_widget] == [
            main_window.global_network_map_node
        ]

        node = main_window.global_network_map_node
        assert node is not None
        main_window.close_tab(node)
        QApplication.processEvents()

        assert main_window.global_network_map_widget is None
        assert main_window.global_network_map_node is None

        main_window.open_network_map()
        QApplication.processEvents()

        assert isinstance(main_window.global_network_map_widget, NetworkMapWidget)
        assert main_window.global_network_map_widget is not first_widget

        main_window.refresh_global_network_map()
        QApplication.processEvents()
