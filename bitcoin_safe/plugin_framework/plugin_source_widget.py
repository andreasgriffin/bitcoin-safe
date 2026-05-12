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

import logging
from collections.abc import Callable
from functools import partial
from html import escape
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.plugin_framework.external_plugin_registry import (
    ExternalPluginCatalogEntry,
    ExternalPluginRegistry,
    PluginSource,
    PluginSourceAuthConfig,
)
from bitcoin_safe.plugin_framework.plugin_display import format_version_with_hash
from bitcoin_safe.plugin_framework.plugin_list_widget import (
    BasePluginWidget,
)
from bitcoin_safe.signature_manager import KnownGPGKeys

logger = logging.getLogger(__name__)

ALLOW_THIRD_PARTY_SOURCES = False


class AddPluginSourceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Add Plugin Source"))

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.manifest_url_edit = QLineEdit(self)
        self.display_name_edit = QLineEdit(self)
        self.bearer_token_edit = QLineEdit(self)
        self.pinned_key_edit = QPlainTextEdit(self)
        self.pinned_key_edit.setPlaceholderText(self.tr("Paste the ASCII-armored public key here"))
        if not ALLOW_THIRD_PARTY_SOURCES:
            self.pinned_key_edit.setPlainText(KnownGPGKeys.andreasgriffin.key.strip())
            self.pinned_key_edit.setReadOnly(True)
            self.pinned_key_edit.setEnabled(False)

        form.addRow(self.tr("Manifest URL"), self.manifest_url_edit)
        form.addRow(self.tr("Display name"), self.display_name_edit)
        form.addRow(self.tr("Bearer token"), self.bearer_token_edit)
        form.addRow(self.tr("Pinned public key"), self.pinned_key_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def source_values(self) -> tuple[str, str | None, PluginSourceAuthConfig, str]:
        manifest_url = self.manifest_url_edit.text().strip()
        display_name = self.display_name_edit.text().strip() or None
        bearer_token = self.bearer_token_edit.text().strip() or None
        auth_config = PluginSourceAuthConfig(
            kind="bearer" if bearer_token else "none",
            bearer_token=bearer_token,
        )
        pinned_key = (
            self.pinned_key_edit.toPlainText().strip()
            if ALLOW_THIRD_PARTY_SOURCES
            else KnownGPGKeys.andreasgriffin.key.strip()
        )
        return manifest_url, display_name, auth_config, pinned_key


class PluginSourceWidget(BasePluginWidget):
    signal_refresh_requested = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_delete_requested = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        source: PluginSource,
        installed_plugins_count: int,
        parent: QWidget | None = None,
    ) -> None:
        self.source = source
        self.installed_plugins_count = installed_plugins_count
        super().__init__(
            title=self._display_title(),
            description=self._manifest_url_text(),
            provider="",
            icon=svg_tools.get_QIcon("bi--cloud.svg"),
            parent=parent,
        )
        self.provider_label.setVisible(False)
        self.version_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)

        self.refresh_button = self.add_spinning_management_button()
        self.delete_button = self.add_management_button()
        self.updateUi()

    def _display_title(self) -> str:
        return escape(self.source.display_name)

    def _manifest_url_text(self) -> str:
        return escape(self.source.manifest_url)

    def _emit_refresh_requested(self) -> None:
        self.signal_refresh_requested.emit(self.source.source_id)

    def _emit_delete_requested(self) -> None:
        self.signal_delete_requested.emit(self.source.source_id)

    def updateUi(self) -> None:
        self.set_plugin_metadata(
            title=self._display_title(),
            description=self._manifest_url_text(),
            provider="",
            icon=svg_tools.get_QIcon("bi--cloud.svg"),
        )
        self.provider_label.setVisible(False)
        self.set_version_text(self.tr("Source ID: {source_id}").format(source_id=self.source.source_id))

        status_parts: list[str] = []
        if self.source.last_error:
            status_parts.append(self.tr("Last error: {error}").format(error=self.source.last_error))
        if self.installed_plugins_count:
            status_parts.append(
                self.tr("Cannot remove while {count} plugin(s) are installed.").format(
                    count=self.installed_plugins_count
                )
            )
        self.set_status_text("\n".join(status_parts))
        self.set_enable_toggle(checked=False, callback=None, visible=False)
        self.set_icon_action(callback=None, enabled=False)
        self._set_button_action(
            button=self.refresh_button,
            text=self.tr("Refresh"),
            callback=self._emit_refresh_requested,
            visible=True,
            enable=True,
        )
        self._set_button_action(
            button=self.delete_button,
            text=self.tr("Delete"),
            callback=self._emit_delete_requested,
            visible=True,
            enable=self.installed_plugins_count == 0,
        )
        self.delete_button.setToolTip(
            ""
            if self.installed_plugins_count == 0
            else self.tr("Remove installed plugins from this source before deleting the source.")
        )
        self._sync_section_visibility()


class SourceManagementDialog(QDialog):
    signal_add_source_requested = cast(SignalProtocol[[]], pyqtSignal())
    signal_refresh_source_requested = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_recheck_plugins_requested = cast(SignalProtocol[[]], pyqtSignal())
    signal_delete_source_requested = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        registry: ExternalPluginRegistry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self.setWindowTitle(self.tr("Plugin Sources"))
        self.resize(760, 420)

        layout = QVBoxLayout(self)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget(self.scroll_area)
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(10)
        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area)

        self.empty_label = QLabel(self)
        self.empty_label.setStyleSheet("color: gray;")
        self.scroll_layout.addWidget(self.empty_label)

        self.button_box = QDialogButtonBox(parent=self)

        self.add_source_button = QPushButton(self)
        self.add_source_button.clicked.connect(self.signal_add_source_requested.emit)
        self.button_box.addButton(self.add_source_button, QDialogButtonBox.ButtonRole.ActionRole)

        self.recheck_plugins_button = SpinningButton("", parent=self, timeout=120, svg_tools=svg_tools)
        self.recheck_plugins_button.clicked.connect(
            partial(
                self._run_spinning_action,
                button=self.recheck_plugins_button,
                callback=self.signal_recheck_plugins_requested.emit,
            )
        )
        self.button_box.addButton(self.recheck_plugins_button, QDialogButtonBox.ButtonRole.ActionRole)

        self.close_button = QPushButton(self)
        self.close_button.clicked.connect(self.accept)
        self.button_box.addButton(self.close_button, QDialogButtonBox.ButtonRole.RejectRole)

        layout.addWidget(self.button_box)
        self.updateUi()
        self.reload_sources()

    def updateUi(self) -> None:
        self.add_source_button.setText(self.tr("Add Plugin Source..."))
        self.recheck_plugins_button.setText(self.tr("Recheck Installed Plugins"))
        self.close_button.setText(self.tr("Close"))

    def reload_sources(self) -> None:
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        sources = self._registry.load_sources()
        installed_counts = self._registry.installed_plugin_counts_by_source()
        self.empty_label = QLabel(self.scroll_content)
        self.empty_label.setStyleSheet("color: gray;")
        self.empty_label.setText(
            self.tr("No plugin sources added yet.") if not sources else self.tr("Configured plugin sources")
        )
        self.scroll_layout.addWidget(self.empty_label)

        for source in sources:
            row_widget = PluginSourceWidget(
                source=source,
                installed_plugins_count=installed_counts.get(source.source_id, 0),
                parent=self.scroll_content,
            )
            row_widget.signal_refresh_requested.connect(self.signal_refresh_source_requested.emit)
            row_widget.signal_delete_requested.connect(self.signal_delete_source_requested.emit)
            self.scroll_layout.addWidget(row_widget)

        self.scroll_layout.addStretch()

    def _run_spinning_action(
        self,
        button: SpinningButton,
        callback: Callable[[], None],
    ) -> None:
        QTimer.singleShot(0, partial(self._finish_spinning_action, button, callback))

    def _finish_spinning_action(
        self,
        button: SpinningButton,
        callback: Callable[[], None],
    ) -> None:
        QApplication.processEvents()
        try:
            callback()
        finally:
            try:
                button.enable_button()
            except RuntimeError:
                pass


class SourceCatalogItem(QObject):
    signal_install_requested = cast(
        SignalProtocol[[ExternalPluginCatalogEntry]],
        pyqtSignal(ExternalPluginCatalogEntry),
    )
    signal_request_enabled = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_enabled_changed = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_needs_persist = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        entry: ExternalPluginCatalogEntry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.icon = svg_tools.get_QIcon("bi--download.svg")
        self.enabled = False
        self.title = entry.display_name
        self.description = entry.description
        self.provider = f"{entry.provider} via {entry.source_display_name}"

    @property
    def node(self) -> SidebarNode[object] | None:
        return None

    def status_text(self) -> str:
        if self.entry.update_available and self.entry.installed_version:
            return self.tr("Installed {installed}; update available: {available}").format(
                installed=self.entry.installed_version,
                available=self._available_update_target_text(),
            )
        if self.entry.installed_version:
            return self.tr("Installed version: {version}").format(version=self.entry.installed_version)
        return self.tr("Available version: {version}").format(version=self.entry.version)

    def additional_status_text(self) -> str:
        return ""

    def version_text(self) -> str:
        if self.entry.installed_version and self.entry.update_available:
            return self.tr("Version {installed} -> {available}").format(
                installed=self.entry.installed_version,
                available=self._available_update_target_text(),
            )
        if self.entry.installed_version:
            return self.tr("Version {version}").format(version=self.entry.installed_version)
        return self.tr("Latest {version}").format(version=self.entry.version)

    def install_button_text(self) -> str:
        if self.entry.update_available:
            return self.tr("Update to {available}").format(available=self._available_update_target_text())
        if self.entry.installed_version:
            return self.tr("Reinstall {version}").format(version=self.entry.version)
        return self.tr("Install {version}").format(version=self.entry.version)

    def _available_update_target_text(self) -> str:
        return format_version_with_hash(
            self,
            version=self.entry.version,
            folder_hash=self.entry.folder_hash,
        )

    def trigger_install(self) -> None:
        self.signal_install_requested.emit(self.entry)

    def create_plugin_widget(
        self,
        icon_size: tuple[int, int] = (40, 40),
        parent: QWidget | None = None,
    ) -> BasePluginWidget:
        from bitcoin_safe.plugin_framework.plugin_list_widget import SourceCatalogItemWidget

        return SourceCatalogItemWidget(item=self, icon_size=icon_size, parent=parent)
