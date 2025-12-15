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
from abc import abstractmethod
from typing import Any, cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.plugin_framework.plugin_conditions import PluginConditions
from bitcoin_safe.plugin_framework.plugin_server import PluginPermission, PluginServerView
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.util import fast_version

logger = logging.getLogger(__name__)


class PluginClient(BaseSaveableClass, QWidget):
    known_classes = {
        **BaseSaveableClass.known_classes,
        PluginPermission.__name__: PluginPermission,
    }
    VERSION = "0.0.2"
    plugin_conditions = PluginConditions()
    required_permissions: set[PluginPermission] = set()
    title = "Base Plugin"
    description = ""
    provider = ""

    signal_request_enabled = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_enabled_changed = cast(SignalProtocol[[bool]], pyqtSignal(bool))

    def __init__(self, enabled: bool, icon: QIcon) -> None:
        """Initialize instance."""
        super().__init__()
        self.server: PluginServerView | None = None
        self.signal_tracker = SignalTracker()
        self.icon = icon
        self.node = SidebarNode[object](data=self, widget=self, title=self.title, icon=icon)
        self.enabled = enabled
        self.node.setVisible(enabled)

    @abstractmethod
    def get_widget(self) -> QWidget:
        """Get widget."""
        pass

    def set_enabled(self, value: bool):
        """On set enabled."""
        if self.enabled == value:
            return

        self.node.setVisible(value)

        logger.debug(f"on_triggered {value=}")
        self.enabled = value
        if value:
            self.load()
        else:
            self.unload()

        self.signal_enabled_changed.emit(value)

    @abstractmethod
    def load(self):
        """Load."""
        pass

    @abstractmethod
    def unload(self):
        """Unload."""
        pass

    def drop_wallet_specific_things(self) -> bool:
        "Returns if dropping was successful"
        return True

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["tab_text"] = self.title
        d["enabled"] = self.enabled
        return d

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            pass
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.1"):
            dct["tab_text"] = dct["title"]

        # now the version is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    def close(self) -> bool:
        """Close."""
        self.signal_tracker.disconnect_all()
        return super().close()

    def updateUi(self):
        """UpdateUi."""
        pass

    def set_server_view(
        self,
        server: PluginServerView,
    ):
        self.server = server
