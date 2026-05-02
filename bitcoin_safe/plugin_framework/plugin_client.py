#
# Bitcoin Safe
# Copyright (C) 2025-2026 Andreas Griffin
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

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe_lib.util import fast_version
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QWidget

from bitcoin_safe import __version__
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.i18n import translate
from bitcoin_safe.plugin_framework.plugin_conditions import PluginConditions
from bitcoin_safe.plugin_framework.plugin_display import format_version_with_hash
from bitcoin_safe.plugin_framework.plugin_identity import (
    PluginSource as PluginClientSource,
)
from bitcoin_safe.plugin_framework.plugin_identity import (
    build_plugin_id,
)
from bitcoin_safe.plugin_framework.plugin_server import PluginPermission, PluginServerView

if TYPE_CHECKING:
    from bitcoin_safe.plugin_framework.plugin_list_widget import BasePluginWidget
    from bitcoin_safe.plugin_framework.plugins.business_plan.client import BusinessPlanItem


logger = logging.getLogger(__name__)


class PluginClient(QWidget, BaseSaveableClass):
    known_classes: dict[str, Any] = {
        **BaseSaveableClass.known_classes,
        PluginPermission.__name__: PluginPermission,
    }
    VERSION = "0.0.3"
    IS_AVAILABLE = True
    plugin_conditions = PluginConditions()
    required_permissions: set[PluginPermission] = set()
    show_in_list = True
    title = "Base Plugin"
    description = ""
    provider = ""

    signal_request_enabled = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_enabled_changed = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_needs_persist = cast(SignalProtocol[[]], pyqtSignal())
    signal_update_requested = cast(SignalProtocol[[]], pyqtSignal())
    signal_delete_requested = cast(SignalProtocol[[]], pyqtSignal())

    @classmethod
    def cls_kwargs(cls, parent: QWidget | None):
        d = super().cls_kwargs(parent=parent)
        d.update(
            {
                "parent": parent,
            }
        )
        return d

    def __init__(self, enabled: bool, icon: QIcon, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.server: PluginServerView | None = None
        self.signal_tracker = SignalTracker()
        self.icon = icon
        self.node: SidebarNode[object] = SidebarNode[object](
            data=self, widget=self, title=self.title, icon=icon, indent_factor=0, parent=self
        )
        self.enabled = enabled
        self.set_base_infos()
        self.node.setTitle(self.title)
        self.node.setIcon(self.icon)
        self.node.setVisible(enabled)
        self.business_plan: BusinessPlanItem | None = None
        self.notification_bars: list[NotificationBar] = []
        self.plugin_source: PluginClientSource | None = None
        self.plugin_bundle_id: str | None = None
        self._additional_status_text = ""
        self._external_update_available = False
        self._external_installed_version: str | None = None
        self._external_available_version: str | None = None
        self._external_available_hash: str | None = None
        self.plugin_id = self.__class__.__name__

    @classmethod
    def set_base_infos(cls):
        cls.title = translate("ScheduledPaymentsClient", "Demo Subscription Plugin")
        cls.description = translate(
            "ScheduledPaymentsClient",
            "Example plugin based on PaidPluginClient. "
            "Use this to verify subscription-gated activation and plugin-manager actions.",
        )

    @staticmethod
    def build_plugin_id(
        plugin_source: PluginClientSource,
        plugin_bundle_id: str | None,
        class_name: str,
    ) -> str:
        return build_plugin_id(
            plugin_source=plugin_source,
            plugin_bundle_id=plugin_bundle_id,
            class_name=class_name,
        )

    def set_plugin_identity(
        self,
        plugin_source: PluginClientSource,
        plugin_bundle_id: str | None = None,
        plugin_id: str | None = None,
    ) -> None:
        self.plugin_source = plugin_source
        self.plugin_bundle_id = plugin_bundle_id
        self.plugin_id = plugin_id or self.build_plugin_id(
            plugin_source=plugin_source,
            plugin_bundle_id=plugin_bundle_id,
            class_name=self.__class__.__name__,
        )

    def set_additional_status_text(self, text: str) -> None:
        self._additional_status_text = text

    def set_display_metadata(
        self,
        title: str,
        description: str,
        provider: str,
        icon: QIcon,
    ) -> None:
        self.title = title
        self.description = description
        self.provider = provider
        self.icon = icon
        self.node.setTitle(title)
        self.node.setIcon(icon)

    def set_external_state(
        self,
        update_available: bool,
        installed_version: str | None = None,
        available_version: str | None = None,
        available_hash: str | None = None,
    ) -> None:
        self._external_update_available = update_available
        self._external_installed_version = installed_version
        self._external_available_version = available_version if update_available else None
        self._external_available_hash = available_hash if update_available else None

    def _external_update_target_text(self) -> str | None:
        if not self._external_available_version:
            return None
        if not self._external_available_hash:
            return self._external_available_version
        return format_version_with_hash(
            self,
            version=self._external_available_version,
            folder_hash=self._external_available_hash,
        )

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
        self.signal_needs_persist.emit()

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
        d["plugin_id"] = self.plugin_id
        d["plugin_source"] = self.plugin_source.value if self.plugin_source else None
        d["plugin_bundle_id"] = self.plugin_bundle_id
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
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.2"):
            dct.setdefault("plugin_source", PluginClientSource.BUILTIN.value)
            dct.setdefault("plugin_bundle_id", None)
            dct.setdefault(
                "plugin_id",
                cls.build_plugin_id(
                    plugin_source=PluginClientSource(dct["plugin_source"]),
                    plugin_bundle_id=dct["plugin_bundle_id"],
                    class_name=cls.__name__,
                ),
            )

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
        self.set_base_infos()
        self.node.setTitle(self.title)
        self.node.setIcon(self.icon)

    def set_server_view(
        self,
        server: PluginServerView,
    ):
        self.server = server

    def supports_enable_toggle(self) -> bool:
        return True

    def status_text(self) -> str:
        return ""

    def allow_enable_request(self) -> bool:
        return True

    def additional_status_text(self) -> str:
        update_target = self._external_update_target_text()
        if self._external_update_available and update_target:
            return self.tr("Update available: {update_target}").format(update_target=update_target)
        return self._additional_status_text

    def version_text(self) -> str:
        if self._external_installed_version:
            return self.tr("Version {version}").format(version=self._external_installed_version)
        return __version__

    def has_update_available(self) -> bool:
        return self.is_external_plugin() and self._external_update_available

    def is_external_plugin(self) -> bool:
        return self.plugin_source == PluginClientSource.EXTERNAL and self.plugin_bundle_id is not None

    def can_update_plugin(self) -> bool:
        return self.has_update_available()

    def update_button_text(self) -> str:
        update_target = self._external_update_target_text()
        if update_target:
            return self.tr("Update to {update_target}").format(update_target=update_target)
        return self.tr("Update")

    def can_delete_plugin(self) -> bool:
        return self.is_external_plugin() and not self.enabled

    def request_update(self) -> None:
        if self.can_update_plugin():
            self.signal_update_requested.emit()

    def request_delete(self) -> None:
        if self.can_delete_plugin():
            self.signal_delete_requested.emit()

    def supports_plan_selection(self) -> bool:
        return False

    def plan_selection_title(self) -> str:
        return ""

    def available_plan_options(self) -> tuple[tuple[str, str], ...]:
        return ()

    def selected_plan_option_key(self) -> str:
        return ""

    def select_plan_option(self, storage_key: str) -> None:
        return None

    def create_plugin_widget(
        self,
        icon_size: tuple[int, int] = (40, 40),
        parent: QWidget | None = None,
    ) -> BasePluginWidget:
        from bitcoin_safe.plugin_framework.plugin_list_widget import ExternalPluginWidget, PluginWidget

        widget_cls = ExternalPluginWidget if self.is_external_plugin() else PluginWidget
        return widget_cls(plugin=self, icon_size=icon_size, parent=parent)

    def reload_translator(self) -> None:
        pass
