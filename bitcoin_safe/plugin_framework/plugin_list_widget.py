#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from typing import Protocol, cast, runtime_checkable

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.gui.qt.util import svg_tools

logger = logging.getLogger(__name__)


@runtime_checkable
class PluginProtocol(Protocol):
    title: str
    description: str
    provider: str
    icon: QIcon
    signal_request_enabled: SignalProtocol[bool]
    signal_enabled_changed: SignalProtocol[bool]
    enabled: bool
    node: SidebarNode

    def get_widget(self) -> QWidget:
        """Get widget."""
        ...


class PluginWidget(QWidget):
    def __init__(
        self, plugin: PluginProtocol, icon_size: tuple[int, int] = (40, 40), parent: QWidget | None = None
    ):
        """Initialize instance."""
        super().__init__(parent)
        self.plugin = plugin

        # — Layout & Widgets —
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(5, 5, 5, 5)
        self._layout.setSpacing(15)

        # Icon label
        self.icon_label = QLabel()
        self.icon_label.setPixmap(plugin.icon.pixmap(*icon_size))
        self._layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        # Text container (title, provider, description)
        self.text_container = QWidget()
        text_layout = QVBoxLayout(self.text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        # Title
        self.title_label = QLabel(f"<b>{plugin.title}</b>")
        self.title_label.setTextFormat(Qt.TextFormat.RichText)

        # Provider (new)
        self.provider_label = QLabel(f"Provided by: {plugin.provider}")
        self.provider_label.setStyleSheet("color: gray; font-style: italic;")
        self.provider_label.setTextFormat(Qt.TextFormat.RichText)
        self.provider_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.provider_label.setOpenExternalLinks(True)

        # Description
        self.description_label = QLabel(plugin.description)
        self.description_label.setTextFormat(Qt.TextFormat.RichText)
        self.description_label.setWordWrap(True)
        self.description_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.description_label.setOpenExternalLinks(True)

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.provider_label)
        text_layout.addWidget(self.description_label)
        self._layout.addWidget(self.text_container, stretch=1)

        # Enable/disable checkbox
        self.enable_checkbox = QCheckBox(self.tr("Enable/Disable"))
        self.enable_checkbox.stateChanged.connect(self._on_checkbox_try_change)
        self._layout.addWidget(self.enable_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        self.plugin.signal_enabled_changed.connect(self._on_enabled_changed)

        # Initialize UI state
        self.updateUi()

    def _on_enabled_changed(self, enabled: bool) -> None:
        self.updateUi()

    def _on_checkbox_try_change(self, state_int: int):
        # Temporarily disconnect to prevent recursion
        self.enable_checkbox.blockSignals(True)

        state = Qt.CheckState(state_int)

        # Revert state change, since be need to send signal_request_enabled first
        previous = Qt.CheckState.Checked if state == Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
        self.enable_checkbox.setCheckState(previous)

        self.enable_checkbox.blockSignals(False)

        self.plugin.signal_request_enabled.emit(state == Qt.CheckState.Checked)

    def updateUi(self) -> None:
        """Refreshes the checkbox to match the plugin's current enabled state."""
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(self.plugin.enabled)
        self.enable_checkbox.blockSignals(False)


class PluginListWidget(QWidget):
    def __init__(
        self,
        icon_size: tuple[int, int] = (40, 40),
        parent: QWidget | None = None,
    ):
        """Initialize instance."""
        super().__init__(parent)
        self.icon_size = icon_size
        self.plugins_widgets: list[PluginWidget] = []

        # Scrollable area setup
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.v_layout = QVBoxLayout(container)
        scroll.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll)

        self.node = SidebarNode[object](
            data=self,
            widget=self,
            icon=svg_tools.get_QIcon("bi--gear.svg"),
            title="",
        )

    def set_plugins(
        self,
        plugins: Sequence[PluginProtocol],
    ):
        # Create a PluginWidget for each plugin
        """Set plugins."""
        for plugin in plugins:
            pw = PluginWidget(plugin, self.icon_size, self)
            self.plugins_widgets.append(pw)
            self.v_layout.addWidget(pw)
            self.node.addChildNode(plugin.node)
            self.node.setVisible(plugin.enabled)

        # push them to the top
        self.v_layout.addStretch()

    def updateUi(self) -> None:
        """Call this whenever plugin states may have changed externally."""
        for plugin_widget in self.plugins_widgets:
            plugin_widget.updateUi()


# Example usage with a dummy plugin implementation
class DummyPlugin(QObject):
    signal_request_enabled = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_enabled_changed = cast(SignalProtocol[[bool]], pyqtSignal(bool))

    def __init__(self, title, icon, description, provider):
        """Initialize instance."""
        super().__init__()
        self.title = title
        self.icon = icon
        self.description = description
        self.provider = provider
        self.enabled = True
        self._widget = QLabel(f"<i>{self.title} UI</i>")
        self.node = SidebarNode(title="", data=self, widget=None)

    def get_widget(self) -> QWidget:
        """Get widget."""
        return self._widget


if __name__ == "__main__":
    app = QApplication(sys.argv)

    plugins = [
        DummyPlugin(
            "Plugin A", QIcon.fromTheme("applications-development"), "Does really cool things.", "Alice"
        ),
        DummyPlugin("Plugin B", QIcon.fromTheme("help-about"), "Provides extra functionality.", "Bob"),
        DummyPlugin("Plugin C", QIcon.fromTheme("system-run"), "Runs background tasks.", "Carol"),
    ]

    w = PluginListWidget()
    w.set_plugins(plugins)
    w.setWindowTitle("Plugin Manager")
    w.resize(500, 400)
    w.show()

    sys.exit(app.exec())
