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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.icon_label import ClickableLabel
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.plugin_framework.plugin_card_frame import PluginCardFrame

if TYPE_CHECKING:
    from bitcoin_safe.plugin_framework.paid_plugin_client import PaidPluginClient
    from bitcoin_safe.plugin_framework.plugin_client import PluginClient
    from bitcoin_safe.plugin_framework.plugin_manager import SourceCatalogItem


class BasePluginWidget(PluginCardFrame):
    def __init__(
        self,
        title: str,
        description: str,
        provider: str,
        icon: QIcon,
        icon_size: tuple[int, int] = (40, 40),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.icon_size = icon_size

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(10)

        self.content_row = QHBoxLayout()
        self.content_row.setContentsMargins(0, 0, 0, 0)
        self.content_row.setSpacing(12)
        self._layout.addLayout(self.content_row)

        self.icon_label = ClickableLabel(self)
        self.icon_label.setPixmap(icon.pixmap(QSize(*icon_size), self.devicePixelRatioF()))
        self.content_row.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        self.text_container = QWidget(self)
        self.text_layout = QVBoxLayout(self.text_container)
        self.text_layout.setContentsMargins(0, 0, 0, 0)
        self.text_layout.setSpacing(4)
        self.content_row.addWidget(self.text_container, stretch=1)

        self.title_label = QLabel(f"<b>{title}</b>", self.text_container)
        self.title_label.setTextFormat(Qt.TextFormat.RichText)

        self.metadata_row = QWidget(self.text_container)
        self.metadata_layout = QHBoxLayout(self.metadata_row)
        self.metadata_layout.setContentsMargins(0, 0, 0, 0)
        self.metadata_layout.setSpacing(0)

        self.version_label = QLabel("", self.metadata_row)
        self.version_label.setForegroundRole(QPalette.ColorRole.Dark)
        self.version_label.setVisible(False)
        self.metadata_layout.addWidget(self.version_label)

        self.metadata_separator_label = QLabel(" - ", self.metadata_row)
        self.metadata_separator_label.setForegroundRole(QPalette.ColorRole.Dark)
        self.metadata_separator_label.setVisible(False)
        self.metadata_layout.addWidget(self.metadata_separator_label)

        self.provider_label = QLabel(f"Provided by: {provider}", self.metadata_row)
        provider_font = self.provider_label.font()
        provider_font.setItalic(True)
        self.provider_label.setFont(provider_font)
        self.provider_label.setForegroundRole(QPalette.ColorRole.Dark)
        self.provider_label.setTextFormat(Qt.TextFormat.RichText)
        self.provider_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.provider_label.setOpenExternalLinks(True)
        self.metadata_layout.addWidget(self.provider_label)
        self.metadata_layout.addStretch()

        self.description_label = QLabel(description, self.text_container)
        self.description_label.setTextFormat(Qt.TextFormat.RichText)
        self.description_label.setWordWrap(True)
        self.description_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.description_label.setOpenExternalLinks(True)

        self.status_label = QLabel("", self.text_container)
        self.status_label.setWordWrap(True)
        self.status_label.setForegroundRole(QPalette.ColorRole.Dark)

        self.text_layout.addWidget(self.title_label)
        self.text_layout.addWidget(self.metadata_row)
        self.text_layout.addWidget(self.description_label)
        self.text_layout.addWidget(self.status_label)

        self.details_container = QWidget(self.text_container)
        self.details_layout = QVBoxLayout(self.details_container)
        self.details_layout.setContentsMargins(0, 4, 0, 0)
        self.details_layout.setSpacing(8)
        self.text_layout.addWidget(self.details_container)

        self.management_section = QWidget(self.details_container)
        self.management_buttons_container = QWidget(self.management_section)
        self.management_buttons_layout = QHBoxLayout(self.management_buttons_container)
        self.management_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.management_buttons_layout.setSpacing(8)

        self.destructive_buttons_container = QWidget(self.management_section)
        self.destructive_buttons_layout = QHBoxLayout(self.destructive_buttons_container)
        self.destructive_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.destructive_buttons_layout.setSpacing(8)
        self.destructive_buttons_layout.addStretch()

        self.management_layout = QHBoxLayout(self.management_section)
        self.management_layout.setContentsMargins(0, 0, 0, 0)
        self.management_layout.setSpacing(6)
        self.management_layout.addWidget(self.management_buttons_container)
        self.management_layout.addStretch()
        self.management_layout.addWidget(self.destructive_buttons_container)
        self.details_layout.addWidget(self.management_section)

        self.controls_container = QWidget(self)
        self.controls_layout = QVBoxLayout(self.controls_container)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setSpacing(6)
        self.controls_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.content_row.addWidget(self.controls_container, alignment=Qt.AlignmentFlag.AlignTop)

        self.activation_section = self.controls_container
        self.enable_checkbox = QCheckBox(self.tr("Enable"), self.controls_container)
        self.enable_checkbox.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.controls_layout.addWidget(self.enable_checkbox)

        self.action_buttons_container = QWidget(self.controls_container)
        self.action_buttons_layout = QVBoxLayout(self.action_buttons_container)
        self.action_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.action_buttons_layout.setSpacing(6)
        self.controls_layout.addWidget(self.action_buttons_container)
        self.controls_layout.addStretch()

        self.details_container.setVisible(False)
        self.management_section.setVisible(False)
        self.controls_container.setVisible(False)
        self.set_plugin_metadata(title=title, description=description, provider=provider, icon=icon)

    def set_plugin_metadata(
        self,
        title: str,
        description: str,
        provider: str,
        icon: QIcon,
    ) -> None:
        self.title_label.setText(f"<b>{title}</b>")
        self.provider_label.setText(self.tr("Provided by: {provider}").format(provider=provider))
        self.description_label.setText(description)
        self.icon_label.setPixmap(icon.pixmap(QSize(*self.icon_size), self.devicePixelRatioF()))

    def set_icon_action(self, callback: Callable[[], None] | None, enabled: bool) -> None:
        try:
            self.icon_label.clicked.disconnect()
        except TypeError:
            pass

        if callback is not None and enabled:
            self.icon_label.clicked.connect(callback)
            self.icon_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.icon_label.setToolTip(self.tr("Open plugin"))
            return

        self.icon_label.unsetCursor()
        self.icon_label.setToolTip("")

    def set_version_text(self, version_text: str) -> None:
        self.version_label.setText(version_text)
        self.version_label.setVisible(bool(version_text))
        self.metadata_separator_label.setVisible(bool(version_text))

    def _add_section_button(
        self,
        parent: QWidget,
        layout: QVBoxLayout | QHBoxLayout,
        spinning: bool = False,
    ) -> QPushButton:
        button = (
            SpinningButton("", parent=parent, timeout=120, svg_tools=svg_tools)
            if spinning
            else QPushButton(parent)
        )
        button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(button)
        return button

    def add_management_button(self) -> QPushButton:
        return self._add_section_button(
            parent=self.action_buttons_container,
            layout=self.action_buttons_layout,
        )

    def add_spinning_management_button(self) -> QPushButton:
        return self._add_section_button(
            parent=self.action_buttons_container,
            layout=self.action_buttons_layout,
            spinning=True,
        )

    def add_detail_button(self) -> QPushButton:
        return self._add_section_button(
            parent=self.management_buttons_container,
            layout=self.management_buttons_layout,
        )

    def add_spinning_detail_button(self) -> QPushButton:
        return self._add_section_button(
            parent=self.management_buttons_container,
            layout=self.management_buttons_layout,
            spinning=True,
        )

    def add_destructive_detail_button(self) -> QPushButton:
        return self._add_section_button(
            parent=self.destructive_buttons_container,
            layout=self.destructive_buttons_layout,
        )

    def add_spinning_destructive_detail_button(self) -> QPushButton:
        return self._add_section_button(
            parent=self.destructive_buttons_container,
            layout=self.destructive_buttons_layout,
            spinning=True,
        )

    def set_status_text(self, status_text: str) -> None:
        self.status_label.setText(status_text)
        self.status_label.setVisible(bool(status_text))

    def set_enable_toggle(
        self,
        checked: bool,
        callback: Callable[[int], None] | None,
        visible: bool,
    ) -> None:
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(checked)
        self.enable_checkbox.blockSignals(False)

        try:
            self.enable_checkbox.stateChanged.disconnect()
        except TypeError:
            pass

        if callback is not None:
            self.enable_checkbox.stateChanged.connect(callback)

        self.enable_checkbox.setVisible(visible)

    def _set_button_action(
        self,
        button: QPushButton,
        text: str,
        callback: Callable[[], None] | None,
        visible: bool,
        enable: bool,
    ) -> None:
        button.setAccessibleName(text)
        button.setText(text)
        button.setIcon(QIcon())
        button.setToolTip(text if visible else "")
        button.setStatusTip(text if visible else "")

        try:
            button.clicked.disconnect()
        except TypeError:
            pass

        if callback is not None:
            if isinstance(button, SpinningButton):
                button.clicked.connect(
                    partial(self._run_spinning_button_action, button=button, callback=callback)
                )
            else:
                button.clicked.connect(callback)

        button.setVisible(visible)
        button.setEnabled(enable)

    def _run_spinning_button_action(
        self,
        button: SpinningButton,
        callback: Callable[[], None],
    ) -> None:
        QTimer.singleShot(0, partial(self._finish_spinning_button_action, button, callback))

    def _finish_spinning_button_action(
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

    def _is_control_visible(self, widget: QWidget | None) -> bool:
        return widget is not None and not widget.isHidden()

    def _layout_has_visible_widgets(self, layout: QHBoxLayout | QVBoxLayout) -> bool:
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None and not widget.isHidden():
                return True
        return False

    def set_management_section_visible(self, visible: bool) -> None:
        self.management_section.setVisible(visible)

    def set_activation_section_visible(self, visible: bool) -> None:
        self.controls_container.setVisible(visible)

    def _management_section_visible(self) -> bool:
        return self._layout_has_visible_widgets(
            self.management_buttons_layout
        ) or self._layout_has_visible_widgets(self.destructive_buttons_layout)

    def _activation_section_visible(self) -> bool:
        return self._is_control_visible(self.enable_checkbox) or self._layout_has_visible_widgets(
            self.action_buttons_layout
        )

    def _sync_section_visibility(self) -> None:
        management_buttons_visible = self._layout_has_visible_widgets(self.management_buttons_layout)
        destructive_buttons_visible = self._layout_has_visible_widgets(self.destructive_buttons_layout)
        self.management_buttons_container.setVisible(management_buttons_visible)
        self.destructive_buttons_container.setVisible(destructive_buttons_visible)
        management_visible = management_buttons_visible or destructive_buttons_visible
        self.set_management_section_visible(management_visible)
        self.details_container.setVisible(management_visible)
        self.set_activation_section_visible(self._activation_section_visible())

    def updateUi(self) -> None:
        return None


class PluginWidget(BasePluginWidget):
    def __init__(
        self,
        plugin: PluginClient,
        icon_size: tuple[int, int] = (40, 40),
        parent: QWidget | None = None,
    ) -> None:
        self.plugin = plugin
        super().__init__(
            title=plugin.title,
            description=plugin.description,
            provider=plugin.provider,
            icon=plugin.icon,
            icon_size=icon_size,
            parent=parent,
        )
        self._create_additional_sections()
        self._create_action_buttons()
        self.plugin.signal_enabled_changed.connect(self._on_enabled_changed)
        self.plugin.signal_needs_persist.connect(self.updateUi)
        self.updateUi()

    def _create_additional_sections(self) -> None:
        return None

    def _create_action_buttons(self) -> None:
        return None

    def _on_enabled_changed(self, _enabled: bool) -> None:
        self.updateUi()

    def _on_checkbox_try_change(self, state_int: int) -> None:
        self.enable_checkbox.blockSignals(True)
        state = Qt.CheckState(state_int)
        previous = Qt.CheckState.Checked if state == Qt.CheckState.Unchecked else Qt.CheckState.Unchecked
        self.enable_checkbox.setCheckState(previous)
        self.enable_checkbox.blockSignals(False)
        self.plugin.signal_request_enabled.emit(state == Qt.CheckState.Checked)

    def _can_select_node(self) -> bool:
        return self.plugin.enabled and self.plugin.node is not None

    def _select_plugin_node(self) -> None:
        if node := self.plugin.node:
            node.select()

    def _combined_status_text(self) -> str:
        status_text = self.plugin.status_text()
        additional_status_text = self.plugin.additional_status_text()
        if additional_status_text:
            return f"{status_text}\n{additional_status_text}" if status_text else additional_status_text
        return status_text

    def _update_action_buttons(self) -> None:
        return None

    def _enable_toggle_visible(self) -> bool:
        return self.plugin.supports_enable_toggle()

    def updateUi(self) -> None:
        self.set_plugin_metadata(
            title=self.plugin.title,
            description=self.plugin.description,
            provider=self.plugin.provider,
            icon=self.plugin.icon,
        )
        self.set_version_text(self.plugin.version_text())
        self.set_enable_toggle(
            checked=self.plugin.enabled,
            callback=self._on_checkbox_try_change,
            visible=self._enable_toggle_visible(),
        )
        self._update_action_buttons()
        self._sync_section_visibility()
        self.set_status_text(self._combined_status_text())
        self.set_icon_action(callback=self._select_plugin_node, enabled=self._can_select_node())


class ExternalPluginWidget(PluginWidget):
    def _create_action_buttons(self) -> None:
        self.update_button = self.add_spinning_detail_button()
        self.delete_button = self.add_spinning_management_button()

    def _update_action_buttons(self) -> None:
        self._set_button_action(
            button=self.update_button,
            text=self.plugin.update_button_text(),
            callback=self.plugin.request_update,
            visible=self.plugin.has_update_available(),
            enable=self.plugin.can_update_plugin(),
        )
        self._set_button_action(
            button=self.delete_button,
            text=self.tr("Delete Plugin"),
            callback=self.plugin.request_delete,
            visible=self.plugin.can_delete_plugin(),
            enable=self.plugin.can_delete_plugin(),
        )


@dataclass
class PaidPluginControls:
    subscription_section: QWidget
    subscription_layout: QVBoxLayout
    plan_selector_container: QWidget
    plan_selector_layout: QHBoxLayout
    plan_selector_title_label: QLabel
    plan_selector_combo: QComboBox
    offer_label: QLabel
    subscription_buttons_container: QWidget
    subscription_buttons_layout: QHBoxLayout


class PaidPluginWidget(PluginWidget):
    plugin: PaidPluginClient

    def create_paid_controls(self, parent: QWidget, details_layout: QVBoxLayout) -> PaidPluginControls:
        subscription_section = QWidget(parent)
        subscription_layout = QVBoxLayout(subscription_section)
        subscription_layout.setContentsMargins(0, 0, 0, 0)
        subscription_layout.setSpacing(6)
        details_layout.addWidget(subscription_section)

        plan_selector_container = QWidget(subscription_section)
        plan_selector_layout = QHBoxLayout(plan_selector_container)
        plan_selector_layout.setContentsMargins(0, 0, 0, 0)
        plan_selector_layout.setSpacing(8)
        subscription_layout.addWidget(plan_selector_container)

        plan_selector_title_label = QLabel("", plan_selector_container)
        plan_selector_layout.addWidget(plan_selector_title_label)

        plan_selector_combo = QComboBox(plan_selector_container)
        plan_selector_combo.setMinimumContentsLength(12)
        plan_selector_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        plan_selector_combo.setMaximumWidth(250)
        plan_selector_combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        plan_selector_layout.addWidget(plan_selector_combo)

        offer_label = QLabel("", subscription_section)
        offer_label.setVisible(False)
        subscription_layout.addWidget(offer_label)

        subscription_buttons_container = QWidget(plan_selector_container)
        subscription_buttons_layout = QHBoxLayout(subscription_buttons_container)
        subscription_buttons_layout.setContentsMargins(0, 0, 0, 0)
        subscription_buttons_layout.setSpacing(8)
        plan_selector_layout.addWidget(subscription_buttons_container)
        plan_selector_layout.addStretch()

        subscription_section.setVisible(False)
        plan_selector_container.setVisible(False)
        subscription_buttons_container.setVisible(False)

        return PaidPluginControls(
            subscription_section=subscription_section,
            subscription_layout=subscription_layout,
            plan_selector_container=plan_selector_container,
            plan_selector_layout=plan_selector_layout,
            plan_selector_title_label=plan_selector_title_label,
            plan_selector_combo=plan_selector_combo,
            offer_label=offer_label,
            subscription_buttons_container=subscription_buttons_container,
            subscription_buttons_layout=subscription_buttons_layout,
        )

    def _create_additional_sections(self) -> None:
        controls = self.create_paid_controls(
            parent=self.details_container,
            details_layout=self.details_layout,
        )
        self.subscription_section = controls.subscription_section
        self.subscription_layout = controls.subscription_layout
        self.plan_selector_container = controls.plan_selector_container
        self.plan_selector_layout = controls.plan_selector_layout
        self.plan_selector_title_label = controls.plan_selector_title_label
        self.plan_selector_combo = controls.plan_selector_combo
        self.offer_label = controls.offer_label
        self.subscription_buttons_container = controls.subscription_buttons_container
        self.subscription_buttons_layout = controls.subscription_buttons_layout
        self._plan_option_keys: list[str] = []
        self.management_title_label = QLabel("", self.management_section)
        self.management_buttons_layout.insertWidget(0, self.management_title_label)

    def add_subscription_button(self) -> QPushButton:
        return self._add_section_button(
            parent=self.subscription_buttons_container,
            layout=self.subscription_buttons_layout,
        )

    def set_plan_selector(
        self,
        title: str,
        options: tuple[tuple[str, str], ...],
        selected_key: str,
        callback: Callable[[str], None] | None,
        visible: bool,
    ) -> None:
        if not visible or not options:
            self.plan_selector_title_label.setText(title)
            self.plan_selector_title_label.setVisible(False)
            self.plan_selector_combo.blockSignals(True)
            self.plan_selector_combo.clear()
            self.plan_selector_combo.blockSignals(False)
            self._plan_option_keys = []
            self.plan_selector_container.setVisible(False)
            return

        self.plan_selector_title_label.setText(title)
        self.plan_selector_title_label.setVisible(bool(title))
        try:
            self.plan_selector_combo.currentIndexChanged.disconnect()
        except TypeError:
            pass

        self.plan_selector_combo.blockSignals(True)
        self.plan_selector_combo.clear()
        self._plan_option_keys = []
        for storage_key, label in options:
            self.plan_selector_combo.addItem(label)
            self._plan_option_keys.append(storage_key)

        selected_index = 0
        if selected_key in self._plan_option_keys:
            selected_index = self._plan_option_keys.index(selected_key)
        self.plan_selector_combo.setCurrentIndex(selected_index)
        self.plan_selector_combo.blockSignals(False)

        if callback is not None:
            self.plan_selector_combo.currentIndexChanged.connect(
                lambda index: callback(self._plan_option_keys[index]) if index >= 0 else None
            )

        self.plan_selector_container.setVisible(True)

    def _subscription_section_visible(self) -> bool:
        return (
            self._is_control_visible(self.plan_selector_container)
            or self._is_control_visible(self.offer_label)
            or self._layout_has_visible_widgets(self.subscription_buttons_layout)
        )

    def _management_row_visible(self) -> bool:
        for index in range(self.management_buttons_layout.count()):
            item = self.management_buttons_layout.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            if widget is None or widget is self.management_title_label:
                continue
            if not widget.isHidden():
                return True
        return self._layout_has_visible_widgets(self.destructive_buttons_layout)

    def _plan_options(self) -> tuple[tuple[str, str], ...]:
        options: list[tuple[str, str]] = []
        for storage_key, label in self.plugin.available_plan_options():
            options.append((storage_key, self.plugin.subscription_price_text(storage_key) or label))
        return tuple(options)

    def _create_action_buttons(self) -> None:
        self.start_trial_button = SpinningButton(
            text="",
            parent=self.subscription_buttons_container,
            timeout=60,
            svg_tools=svg_tools,
        )
        self.subscription_buttons_layout.addWidget(self.start_trial_button)
        self.manage_subscription_button = self.add_detail_button()
        self.refresh_subscription_button = self.add_detail_button()
        self.management_buttons_layout.addStretch()

    def _on_start_trial_clicked(self) -> None:
        self.plugin.trigger_start_trial()
        if not self.plugin.subscription_manager.activation_in_progress:
            self.start_trial_button.enable_button()

    def _enable_toggle_visible(self) -> bool:
        return self.plugin.supports_enable_toggle() and self.plugin.subscription_allows_access()

    def _update_action_buttons(self) -> None:
        self.management_title_label.setText(self.tr("Subscription:"))
        displayed_subscription_manager = self.plugin.displayed_subscription_manager
        supports_manage_subscription = displayed_subscription_manager.supports_manage_subscription()
        show_plan_selector = (
            self.plugin.supports_plan_selection() and not self.plugin.subscription_allows_access()
        )
        show_start_trial = (
            self.plugin.supports_start_trial_action() and not self.plugin.subscription_allows_access()
        )

        self.set_plan_selector(
            title=self.plugin.plan_selection_title(),
            options=self._plan_options(),
            selected_key=self.plugin.selected_plan_option_key(),
            callback=self.plugin.select_plan_option,
            visible=show_plan_selector,
        )
        self._set_button_action(
            button=self.start_trial_button,
            text=self.plugin.start_trial_button_text(),
            callback=self._on_start_trial_clicked,
            visible=show_start_trial,
            enable=not self.plugin.subscription_manager.activation_in_progress,
        )
        if self.plugin.subscription_manager.activation_in_progress:
            self.start_trial_button.start_spin()
        else:
            self.start_trial_button.enable_button()
        self.subscription_buttons_container.setVisible(show_start_trial or show_plan_selector)

        self._set_button_action(
            button=self.manage_subscription_button,
            text=self.tr("Manage"),
            callback=displayed_subscription_manager.trigger_manage_subscription,
            visible=supports_manage_subscription,
            enable=True,
        )
        supports_refresh_subscription_button = self.plugin.supports_refresh_subscription_status_action()
        self._set_button_action(
            button=self.refresh_subscription_button,
            text=self.tr("Refresh status"),
            callback=self.plugin.trigger_refresh_subscription_status_action,
            visible=supports_refresh_subscription_button,
            enable=True,
        )

    def _sync_section_visibility(self) -> None:
        management_row_visible = self._management_row_visible()
        self.subscription_buttons_container.setVisible(
            self._layout_has_visible_widgets(self.subscription_buttons_layout)
        )
        subscription_visible = self._subscription_section_visible()
        self.subscription_section.setVisible(subscription_visible)
        self.set_management_section_visible(management_row_visible)
        self.details_container.setVisible(subscription_visible or management_row_visible)
        self.set_activation_section_visible(self._activation_section_visible())


class ExternalPaidPluginWidget(PaidPluginWidget):
    def _create_action_buttons(self) -> None:
        super()._create_action_buttons()
        self.update_button = self.add_spinning_management_button()
        self.delete_button = self.add_spinning_management_button()

    def _update_action_buttons(self) -> None:
        super()._update_action_buttons()
        self._set_button_action(
            button=self.update_button,
            text=self.plugin.update_button_text(),
            callback=self.plugin.request_update,
            visible=self.plugin.has_update_available(),
            enable=self.plugin.can_update_plugin(),
        )
        self._set_button_action(
            button=self.delete_button,
            text=self.tr("Delete Plugin"),
            callback=self.plugin.request_delete,
            visible=self.plugin.can_delete_plugin(),
            enable=self.plugin.can_delete_plugin(),
        )


class SourceCatalogItemWidget(BasePluginWidget):
    def __init__(
        self,
        item: SourceCatalogItem,
        icon_size: tuple[int, int] = (40, 40),
        parent: QWidget | None = None,
    ) -> None:
        self.item = item
        super().__init__(
            title=item.title,
            description=item.description,
            provider=item.provider,
            icon=item.icon,
            icon_size=icon_size,
            parent=parent,
        )
        self.install_button = self.add_spinning_detail_button()
        self.updateUi()

    def updateUi(self) -> None:
        self.set_plugin_metadata(
            title=self.item.title,
            description=self.item.description,
            provider=self.item.provider,
            icon=self.item.icon,
        )
        self.set_enable_toggle(checked=False, callback=None, visible=False)
        self.set_version_text(self.item.version_text())
        self.set_status_text(self.item.status_text())
        self.set_icon_action(callback=None, enabled=False)
        self._set_button_action(
            button=self.install_button,
            text=self.item.install_button_text(),
            callback=self.item.trigger_install,
            visible=True,
            enable=True,
        )
        self._sync_section_visibility()


class SectionHeader(QWidget):
    def __init__(self, title: str, description: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        self.title_row.setSpacing(10)
        layout.addLayout(self.title_row)

        self.title_label = QLabel(title, self)
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_row.addWidget(self.title_label)

        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        self.title_row.addWidget(divider, stretch=1)

        self.description_label = QLabel(description, self)
        self.description_label.setWordWrap(True)
        self.description_label.setForegroundRole(QPalette.ColorRole.Dark)
        self.description_label.setVisible(bool(description))
        layout.addWidget(self.description_label)

    def add_title_widget(self, widget: QWidget) -> None:
        self.title_row.addWidget(widget)


class PluginListWidget(QWidget):
    def __init__(
        self,
        icon_size: tuple[int, int] = (40, 40),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.icon_size = icon_size
        self.plugins_widgets: list[BasePluginWidget] = []

        self.plugins_section_layout = QVBoxLayout(self)
        self.plugins_section_layout.setContentsMargins(0, 0, 0, 0)
        self.plugins_section_layout.setSpacing(10)

        self.plugins_header = SectionHeader(
            self.tr("Plugins"),
            self.tr("Enable and manage optional wallet integrations."),
            self,
        )
        self.plugins_section_layout.addWidget(self.plugins_header)

        self.plugins_container = QWidget(self)
        self.plugins_container_layout = QVBoxLayout(self.plugins_container)
        self.plugins_container_layout.setContentsMargins(0, 0, 0, 0)
        self.plugins_container_layout.setSpacing(4)
        self.plugins_section_layout.addWidget(self.plugins_container)

        self.setVisible(False)

    def set_plugins(self, plugins: Sequence[PluginClient | SourceCatalogItem]) -> None:
        while self.plugins_container_layout.count():
            item = self.plugins_container_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.close()
                widget.hide()

        self.plugins_widgets.clear()

        for plugin in plugins:
            plugin_widget = plugin.create_plugin_widget(
                icon_size=self.icon_size, parent=self.plugins_container
            )
            self.plugins_widgets.append(plugin_widget)
            self.plugins_container_layout.addWidget(plugin_widget)

        self.plugins_container_layout.addStretch()
        self.setVisible(bool(plugins))

    def updateUi(self) -> None:
        self.plugins_header.title_label.setText(self.tr("Plugins"))
        self.plugins_header.description_label.setText(
            self.tr("Enable and manage optional wallet integrations.")
        )
        self.plugins_header.description_label.setVisible(True)
        for plugin_widget in self.plugins_widgets:
            plugin_widget.updateUi()

    def close(self) -> bool:
        for plugin_widget in self.plugins_widgets:
            plugin_widget.close()
        self.plugins_widgets.clear()
        return super().close()
