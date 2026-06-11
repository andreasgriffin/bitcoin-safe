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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.gui.qt.step_progress_bar import TutorialWidget
from bitcoin_safe.gui.qt.util import set_margins, set_no_margins
from bitcoin_safe.plugin_framework.plugin_manager import PluginManagerWidget

from .wizard_support import BaseTab


class PluginListStep(BaseTab):
    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)
        widget_layout.setSpacing(16)

        self.label_title = QLabel(widget)
        title_font = self.label_title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        self.label_title.setFont(title_font)
        widget_layout.addWidget(self.label_title)

        self.label_main = QLabel(widget)
        self.label_main.setWordWrap(True)
        self.label_main.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.label_main.setOpenExternalLinks(True)
        widget_layout.addWidget(self.label_main)

        self.plugins_host = QWidget(widget)
        self.plugins_host_layout = QVBoxLayout(self.plugins_host)
        set_no_margins(self.plugins_host_layout)
        self.plugins_host_layout.setSpacing(0)
        widget_layout.addWidget(self.plugins_host, stretch=1)

        self.label_fallback = QLabel(self.plugins_host)
        self.label_fallback.setWordWrap(True)
        self.label_fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plugins_host_layout.addWidget(self.label_fallback)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.set_callback(self._on_step_activated)

        self.updateUi()
        return tutorial_widget

    def _on_step_activated(self) -> None:
        """Ensure the plugin manager widget is embedded when this step becomes active."""
        self._embed_plugin_manager_widget()

    def _plugin_manager_widget(self) -> PluginManagerWidget | None:
        """Return the existing plugin manager widget if available."""
        if not self.refs.qt_wallet:
            return None
        return self.refs.qt_wallet.plugin_manager_widget

    def _plugins_node(self) -> SidebarNode[object] | None:
        """Return the existing plugins sidebar node if available."""
        if not self.refs.qt_wallet:
            return None
        return self.refs.qt_wallet.get_plugins_node()

    def _embed_plugin_manager_widget(self) -> None:
        """Temporarily move the existing plugin manager widget into this tutorial step."""
        plugin_widget = self._plugin_manager_widget()
        if plugin_widget is None:
            self.label_fallback.setVisible(True)
            return

        self.label_fallback.setVisible(False)
        if self.plugins_host_layout.indexOf(plugin_widget) != -1:
            return

        set_no_margins(plugin_widget.container_layout)
        self.plugins_host_layout.addWidget(plugin_widget)
        plugin_widget.show()

    def _restore_plugin_manager_widget(self) -> None:
        """Restore the plugin manager widget back to the regular Plugins tab."""
        plugin_widget = self._plugin_manager_widget()
        plugins_node = self._plugins_node()
        if plugin_widget is None or plugins_node is None:
            return

        if self.plugins_host_layout.indexOf(plugin_widget) != -1:
            self.plugins_host_layout.removeWidget(plugin_widget)
            plugin_widget.setParent(None)

        set_margins(plugin_widget.container_layout, margins={}, reset_other_margins=True)
        plugins_node.setWidget(plugin_widget)

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.label_title.setText(self.tr("Explore plugins"))
        self.label_main.setText(
            self.tr(
                "Review the available plugins for this wallet. You can enable the ones you want now "
                "and come back to the Plugins tab later at any time."
            )
        )
        self.label_fallback.setText(
            self.tr("Plugins are not available for this wallet, so there is nothing to configure here.")
        )
        self.label_fallback.setVisible(self._plugin_manager_widget() is None)

    def set_visibilities(self, should_be_visible: bool) -> None:
        """Move the shared plugin widget in and out of the tutorial as needed."""
        if should_be_visible:
            self._embed_plugin_manager_widget()
            return
        self._restore_plugin_manager_widget()

    def close(self) -> None:
        """Close."""
        self._restore_plugin_manager_widget()
        super().close()
