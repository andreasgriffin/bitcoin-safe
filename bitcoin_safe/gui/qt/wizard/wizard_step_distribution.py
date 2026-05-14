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

from dataclasses import dataclass
from functools import partial

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.execute_config import DEFAULT_LANG_CODE
from bitcoin_safe.gui.qt.descriptor_ui import KeyStoreUIs
from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.gui.qt.invisible_scroll_area import InvisibleScrollArea
from bitcoin_safe.gui.qt.step_progress_bar import TutorialWidget, VisibilityOption
from bitcoin_safe.hardware_signers import HardwareSigner, HardwareSigners
from bitcoin_safe.html_utils import html_f, link
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.pdfrecovery import make_and_open_pdf

from ..styled_card_frame import BaseBorderCardFrame
from ..util import (
    AspectRatioSvgWidget,
    Message,
    clear_layout,
    color_with_alpha,
    get_neutral_surface_colors,
    svg_tools,
    svg_tools_hardware_signer,
    to_color_name,
)
from .wizard_support import BaseTab, WizardTabInfo


class RegisterMultisig(BaseTab):
    def __init__(
        self, refs: WizardTabInfo, loop_in_thread: LoopInThread, show_previous_step_button: bool
    ) -> None:
        super().__init__(
            refs=refs, loop_in_thread=loop_in_thread, show_previous_step_button=show_previous_step_button
        )
        self.show_previous_step_button = False

    def _callback(self, tutorial_widget: TutorialWidget) -> None:
        """Callback."""
        del tutorial_widget
        self.updateUi()

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)

        self.label_import = QLabel()
        widget_layout.addWidget(self.label_import)
        self.custom_yes_button = QPushButton("", self.buttonbox)
        self.custom_yes_button.clicked.connect(self.refs.go_to_next_index)
        self.buttonbox.addButton(self.custom_yes_button, QDialogButtonBox.ButtonRole.AcceptRole)

        self.keystore_uis = KeyStoreUIs(
            get_editable_protowallet=self.refs.qtwalletbase.get_editable_protowallet,
            get_address_type=self.refs.qtwalletbase.wallet_descriptor_ui.get_address_type_from_ui,
            signals_min=self.refs.qtwalletbase.signals,
            loop_in_thread=self.loop_in_thread,
            read_only_mode=True,
            show_register_button=True,
        )
        self.keystore_uis.request_show_register_multisig.connect(self._show_register_multisig)
        widget_layout.addWidget(self.keystore_uis)

        self.button_next.setHidden(True)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.set_callback(partial(self._callback, tutorial_widget))
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        self.set_current_signer(0)
        return tutorial_widget

    def _show_register_multisig(self, hardware_signer: HardwareSigner | None) -> None:
        """Open the register-multisig dialog for the current wallet."""
        if self.refs.qt_wallet:
            self.refs.qt_wallet.wallet_descriptor_ui.show_register_multisig(hardware_signer)

        self.updateUi()

    def has_registered_all_signers(self) -> bool:
        """Return whether every signer card has had its register action triggered."""
        return all(
            keystore_ui.counter_register_button_clicked > 0
            for keystore_ui in self.keystore_uis.getAllTabData().values()
        )

    def set_current_signer(self, value: int) -> None:
        """Set current signer."""
        if value >= self.keystore_uis.count():
            return
        self.keystore_uis.setCurrentIndex(value)
        self.keystore_uis.collapse_all()
        if current_keystore_ui := self.keystore_uis.getCurrentTabData():
            current_keystore_ui.button_register.setFocus()
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.label_import.setText(self.tr("Register the multisig wallet on each signing device."))

        self.apply_next_button_style(self.custom_yes_button)
        self.custom_yes_button.setEnabled(self.has_registered_all_signers())
        for keystore_ui in self.keystore_uis.getAllTabData().values():
            keystore_ui.updateUi()
        self.custom_yes_button.setVisible(True)

    def set_visibilities(self, should_be_visible: bool) -> None:
        """Refresh read-only signer cards each time the step is shown."""
        if should_be_visible:
            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.set_current_signer(min(self.keystore_uis.currentIndex(), self.keystore_uis.count() - 1))


@dataclass(frozen=True)
class DistributionPlanRow:
    location_label: str
    location_index: int
    device_label: str | None
    device_signer: HardwareSigner | None
    fingerprint: str | None
    backup_label: str | None
    backup_subtitle: str | None
    show_seed_link: bool = True


class DistributionSurfaceCardFrame(BaseBorderCardFrame):
    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.background_color = None
        self.refresh_style()


class DistributeSeeds(BaseTab):
    def __init__(
        self, refs: WizardTabInfo, loop_in_thread: LoopInThread, show_previous_step_button: bool
    ) -> None:
        super().__init__(
            refs=refs, loop_in_thread=loop_in_thread, show_previous_step_button=show_previous_step_button
        )
        self.backup_sheets_printed = False
        self.seed_words_attached_confirmed = False
        self.sheet_selection_checkboxes: list[QCheckBox] = []

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(0, 0, 0, 0)
        widget_layout.setSpacing(18)

        self.label_title = QLabel(widget)
        title_font = self.label_title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 3)
        self.label_title.setFont(title_font)
        self.label_title.setWordWrap(True)
        widget_layout.addWidget(self.label_title)

        self.label_description = QLabel(widget)
        self.label_description.setWordWrap(True)
        widget_layout.addWidget(self.label_description)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(18)
        widget_layout.addLayout(body_layout)

        self.left_panel = DistributionSurfaceCardFrame(widget)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(16)
        body_layout.addWidget(self.left_panel, stretch=5)

        left_header = QHBoxLayout()
        left_header.setContentsMargins(0, 0, 0, 0)
        left_header.setSpacing(10)
        left_layout.addLayout(left_header)

        self.left_section_badge = self._section_badge("1", widget)
        left_header.addWidget(self.left_section_badge, alignment=Qt.AlignmentFlag.AlignTop)

        left_title_layout = QVBoxLayout()
        left_title_layout.setContentsMargins(0, 0, 0, 0)
        left_title_layout.setSpacing(4)
        left_header.addLayout(left_title_layout, stretch=1)

        self.label_left_title = QLabel(widget)
        left_title_font = self.label_left_title.font()
        left_title_font.setBold(True)
        self.label_left_title.setFont(left_title_font)
        left_title_layout.addWidget(self.label_left_title)

        self.label_left_subtitle = QLabel(widget)
        self.label_left_subtitle.setWordWrap(True)
        left_title_layout.addWidget(self.label_left_subtitle)

        self.print_section = DistributionSurfaceCardFrame(self.left_panel)
        print_layout = QVBoxLayout(self.print_section)
        print_layout.setContentsMargins(18, 18, 18, 18)
        print_layout.setSpacing(14)
        left_layout.addWidget(self.print_section)

        self.label_print_section = QLabel(widget)
        self.label_print_section.setWordWrap(True)
        print_layout.addWidget(self.label_print_section)

        self.sheet_previews_scroll_area = InvisibleScrollArea(self.print_section)
        self.sheet_previews_scroll_area.setWidgetResizable(False)
        self.sheet_previews_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.sheet_previews_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sheet_previews_scroll_area.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.sheet_previews_layout = QHBoxLayout(self.sheet_previews_scroll_area.content_widget)
        self.sheet_previews_layout.setContentsMargins(0, 0, 0, 0)
        self.sheet_previews_layout.setSpacing(10)
        self.sheet_previews_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        print_layout.addWidget(self.sheet_previews_scroll_area)

        self.button_print_backup_sheets = QPushButton(widget)
        self.button_print_backup_sheets.setIcon(svg_tools.get_QIcon("print.svg"))
        self.button_print_backup_sheets.clicked.connect(self._on_print_backup_sheets)
        print_layout.addWidget(self.button_print_backup_sheets)

        self.seed_words_section = DistributionSurfaceCardFrame(self.left_panel)
        seed_words_layout = QVBoxLayout(self.seed_words_section)
        seed_words_layout.setContentsMargins(18, 18, 18, 18)
        seed_words_layout.setSpacing(14)
        left_layout.addWidget(self.seed_words_section)

        self.label_seed_words_section = QLabel(widget)
        self.label_seed_words_section.setWordWrap(True)
        seed_words_layout.addWidget(self.label_seed_words_section)

        self.checkbox_seed_words_attached = QCheckBox(widget)
        self.checkbox_seed_words_attached.toggled.connect(self._on_seed_words_attached_toggled)
        seed_words_layout.addWidget(self.checkbox_seed_words_attached)
        left_layout.addStretch(1)

        self.right_panel = DistributionSurfaceCardFrame(widget)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(16)
        body_layout.addWidget(self.right_panel, stretch=7)

        right_header = QHBoxLayout()
        right_header.setContentsMargins(0, 0, 0, 0)
        right_header.setSpacing(10)
        right_layout.addLayout(right_header)

        self.right_section_badge = self._section_badge("2", widget)
        right_header.addWidget(self.right_section_badge, alignment=Qt.AlignmentFlag.AlignTop)

        right_title_layout = QVBoxLayout()
        right_title_layout.setContentsMargins(0, 0, 0, 0)
        right_title_layout.setSpacing(4)
        right_header.addLayout(right_title_layout, stretch=1)

        self.label_right_title = QLabel(widget)
        right_title_font = self.label_right_title.font()
        right_title_font.setBold(True)
        self.label_right_title.setFont(right_title_font)
        right_title_layout.addWidget(self.label_right_title)

        self.label_right_subtitle = QLabel(widget)
        self.label_right_subtitle.setWordWrap(True)
        right_title_layout.addWidget(self.label_right_subtitle)

        self.distribution_table = DistributionSurfaceCardFrame(widget)
        self.distribution_table_layout = QVBoxLayout(self.distribution_table)
        self.distribution_table_layout.setContentsMargins(0, 0, 0, 0)
        self.distribution_table_layout.setSpacing(0)
        right_layout.addWidget(self.distribution_table, stretch=1)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(self.refs.floating_button_box, on_focus_set_visible=False)
        )

        self.updateUi()
        return tutorial_widget

    def _section_badge(self, text: str, parent: QWidget) -> QLabel:
        badge = QLabel(text, parent)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(40, 40)
        badge_font = badge.font()
        badge_font.setBold(True)
        badge.setFont(badge_font)
        return badge

    def _is_single_sig(self) -> bool:
        return self.refs.qtwalletbase.get_mn_tuple() == (1, 1)

    def _required_sheet_count(self) -> int:
        return 1 if self._is_single_sig() else self.num_keystores()

    def _wallet_keystores(self) -> list[KeyStore]:
        if self.refs.qt_wallet:
            return list(self.refs.qt_wallet.wallet.keystores)
        return []

    def _resolve_hardware_signer(self, keystore) -> HardwareSigner:
        hardware_signer = HardwareSigners.from_id(keystore.hardware_signer_id)
        return hardware_signer if hardware_signer else HardwareSigners.generic

    def _device_display_name(self, keystore, index: int) -> str:
        m, n = self.refs.qtwalletbase.get_mn_tuple()
        fallback_name = self.tr("Signer {i}").format(i=index + 1)
        if not self._is_single_sig() and n > m and index >= m:
            fallback_name = self.tr("Recovery Signer {i}").format(i=index + 1)
        return keystore.hardware_signer_label(fallback_name=fallback_name)

    def _distribution_rows(self) -> list[DistributionPlanRow]:
        keystores = self._wallet_keystores()
        if not keystores:
            return []
        if self._is_single_sig():
            keystore = keystores[0]
            return [
                DistributionPlanRow(
                    location_label=self.tr("Location 1"),
                    location_index=1,
                    device_label=self._device_display_name(keystore, index=0),
                    device_signer=self._resolve_hardware_signer(keystore),
                    backup_label=None,
                    backup_subtitle=None,
                    fingerprint=keystore.fingerprint,
                    show_seed_link=False,
                ),
                DistributionPlanRow(
                    location_label=self.tr("Location 2"),
                    location_index=2,
                    device_label=None,
                    device_signer=self._resolve_hardware_signer(keystore),
                    backup_label=self.tr("Backup sheet"),
                    backup_subtitle=self.tr("Seed words attached"),
                    fingerprint=None,
                ),
            ]
        return [
            DistributionPlanRow(
                location_label=self.tr("Vault {letter}").format(letter=chr(ord("A") + index)),
                location_index=index + 1,
                device_label=self._device_display_name(keystore, index=index),
                device_signer=self._resolve_hardware_signer(keystore),
                backup_label=self.tr("Backup sheet {number}").format(number=index + 1),
                backup_subtitle=self.tr("Seed words attached"),
                fingerprint=keystore.fingerprint,
            )
            for index, keystore in enumerate(keystores)
        ]

    def _sheet_preview_header(self, index: int, total: int, parent: QWidget) -> QWidget:
        """Create the compact sheet header with signer icon and fingerprint."""
        keystores = self._wallet_keystores()
        if 0 <= index < len(keystores):
            keystore = keystores[index]
            hardware_signer = self._resolve_hardware_signer(keystore)
            fingerprint = keystore.fingerprint
            if fingerprint:
                widget = QWidget(parent)
                layout = QHBoxLayout(widget)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(6)
                layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

                icon = QLabel(widget)
                icon.setPixmap(svg_tools_hardware_signer.get_QIcon(hardware_signer.icon_name).pixmap(18, 18))
                layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignVCenter)

                label = QLabel(fingerprint, widget)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignVCenter)
                return widget

        fallback = QLabel(self.tr("{number} of {total}").format(number=index + 1, total=total), parent)
        fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return fallback

    def _create_sheet_preview_card(self, index: int, total: int) -> QWidget:
        card = QWidget(self.left_panel)
        layout = QVBoxLayout(card)

        layout.addWidget(
            self._sheet_preview_header(index, total, card), alignment=Qt.AlignmentFlag.AlignCenter
        )

        preview = AspectRatioSvgWidget(
            svg_content=svg_tools.get_svg_content("descriptor-backup.svg"),
            size_hint_width=92,
            size_hint_height=118,
            parent=card,
        )
        preview.setMinimumHeight(112)
        preview.setMaximumHeight(130)
        layout.addWidget(preview, alignment=Qt.AlignmentFlag.AlignCenter)

        if not self._is_single_sig():
            checkbox = QCheckBox(card)
            checkbox.setChecked(True)
            layout.addWidget(checkbox, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.sheet_selection_checkboxes.append(checkbox)
        return card

    def _rebuild_sheet_previews(self) -> None:
        previous_states = [checkbox.isChecked() for checkbox in self.sheet_selection_checkboxes]
        self.sheet_selection_checkboxes = []
        clear_layout(self.sheet_previews_layout)
        sheet_count = self._required_sheet_count()
        for index in range(sheet_count):
            card = self._create_sheet_preview_card(index, sheet_count)
            if index < len(previous_states):
                self.sheet_selection_checkboxes[index].setChecked(previous_states[index])
            self.sheet_previews_layout.addWidget(card)
        self.sheet_previews_scroll_area.content_widget.adjustSize()
        scrollbar = self.sheet_previews_scroll_area.horizontalScrollBar()
        scrollbar_height = scrollbar.sizeHint().height() if scrollbar else 0
        content_height = self.sheet_previews_scroll_area.content_widget.sizeHint().height()
        self.sheet_previews_scroll_area.setFixedHeight(content_height + scrollbar_height)

    def _selected_sheet_indexes(self) -> list[int]:
        if self._is_single_sig():
            return [0]
        return [
            index for index, checkbox in enumerate(self.sheet_selection_checkboxes) if checkbox.isChecked()
        ]

    def _location_color(self, _index: int) -> str:
        return self.refs.container.palette().color(QPalette.ColorRole.Highlight).name()

    def _accent_text_color(self) -> str:
        return self.refs.container.palette().color(QPalette.ColorRole.HighlightedText).name()

    def _create_location_widget(self, row: DistributionPlanRow) -> QWidget:
        widget = QWidget(self.distribution_table)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        badge = QLabel(str(row.location_index), widget)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(36, 36)
        badge_font = badge.font()
        badge_font.setBold(True)
        badge.setFont(badge_font)
        badge.setStyleSheet(
            f"border-radius: 18px; background-color: {self._location_color(row.location_index)}; color: {self._accent_text_color()};"
        )
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(row.location_label, widget)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
        return widget

    def _create_device_widget(self, row: DistributionPlanRow) -> QWidget:
        widget = QWidget(self.distribution_table)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        if not row.device_signer or not row.device_label:
            layout.addStretch(1)
            return widget

        icon = QLabel(widget)
        icon.setPixmap(svg_tools_hardware_signer.get_QIcon(row.device_signer.icon_name).pixmap(34, 34))
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        layout.addLayout(text_layout)

        title = QLabel(row.device_label, widget)
        title.setWordWrap(True)
        text_layout.addWidget(title)

        if row.fingerprint:
            subtitle = QLabel(row.fingerprint, widget)
            subtitle.setWordWrap(True)
            subtitle.setStyleSheet(f"color: {to_color_name(get_neutral_surface_colors().muted_text)};")
            text_layout.addWidget(subtitle)

        layout.addStretch(1)
        return widget

    def _create_backup_widget(self, row: DistributionPlanRow) -> QWidget:
        widget = QWidget(self.distribution_table)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        if not row.backup_label or not row.backup_subtitle:
            layout.addStretch(1)
            return widget

        icon = QLabel(widget)
        icon.setPixmap(svg_tools.get_QIcon("descriptor-backup.svg").pixmap(28, 34))
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        layout.addLayout(text_layout)

        title = QLabel(row.backup_label, widget)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        title.setWordWrap(True)
        text_layout.addWidget(title)

        subtitle = QLabel(row.backup_subtitle, widget)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {to_color_name(get_neutral_surface_colors().muted_text)};")
        text_layout.addWidget(subtitle)

        layout.addStretch(1)
        return widget

    def _view_seed_instruction_url(self, hardware_signer: HardwareSigner) -> str:
        base_url = hardware_signer.info_url or HardwareSigners.generic.info_url or ""
        return f"{base_url}#instruction-view-seed"

    def _create_view_seed_label(self, row: DistributionPlanRow) -> QWidget:
        if not row.device_signer or not row.show_seed_link:
            spacer = QWidget(self.distribution_table)
            spacer.setFixedWidth(0)
            return spacer

        help_label = IconLabel(parent=self.distribution_table)
        help_label.textLabel.setWordWrap(True)
        instruction_url = self._view_seed_instruction_url(row.device_signer)
        help_label.setText(link(instruction_url, self.tr("View seed words")))
        help_label.set_icon_as_help(
            tooltip=self.tr("Open instructions for viewing seed words on this signer."),
            click_url=instruction_url,
        )
        return help_label

    def _table_header(self) -> QWidget:
        widget = QWidget(self.distribution_table)
        widget.setStyleSheet(
            f"border-bottom: 1px solid {to_color_name(color_with_alpha(get_neutral_surface_colors().panel_border, 90))};"
        )
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(18)
        headers = [
            (self.tr("Location"), 2),
            (self.tr("Signer device"), 4),
            (self.tr("Backup sheet + seed words"), 4),
            ("", 2),
        ]
        for text, stretch in headers:
            label = QLabel(text, widget)
            header_font = label.font()
            header_font.setBold(True)
            label.setFont(header_font)
            layout.addWidget(label, stretch=stretch)
        widget.setObjectName("distributionTableHeader")
        return widget

    def _rows_scroll_area(self) -> InvisibleScrollArea:
        scroll_area = InvisibleScrollArea(self.distribution_table)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll_area

    def _table_row_widget(self, row: DistributionPlanRow, is_last: bool) -> QWidget:
        widget = QWidget(self.distribution_table)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(18)
        layout.addWidget(self._create_location_widget(row), stretch=2)
        layout.addWidget(self._create_device_widget(row), stretch=4)
        layout.addWidget(self._create_backup_widget(row), stretch=4)
        layout.addWidget(self._create_view_seed_label(row), stretch=2)
        if not is_last:
            widget.setStyleSheet(
                f"border-bottom: 1px solid {to_color_name(color_with_alpha(get_neutral_surface_colors().panel_border, 70))};"
            )
        return widget

    def _rebuild_distribution_table(self) -> None:
        clear_layout(self.distribution_table_layout)
        self.distribution_table_layout.addWidget(self._table_header())
        scroll_area = self._rows_scroll_area()
        rows_layout = QVBoxLayout(scroll_area.content_widget)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(0)
        rows = self._distribution_rows()
        for index, row in enumerate(rows):
            rows_layout.addWidget(self._table_row_widget(row, is_last=index == len(rows) - 1))
        rows_layout.addStretch(1)
        self.distribution_table_layout.addWidget(scroll_area)

    def _on_print_backup_sheets(self) -> None:
        if not self.refs.qt_wallet:
            Message(self.tr("Please complete the previous steps."), parent=self.refs.container)
            return
        selected_sheet_indexes = self._selected_sheet_indexes()
        if not selected_sheet_indexes:
            Message(self.tr("Please select at least one backup sheet to print."), parent=self.refs.container)
            return
        make_and_open_pdf(
            self.refs.qt_wallet.wallet,
            lang_code=QLocale().name() or DEFAULT_LANG_CODE,
            selected_keystore_indexes=selected_sheet_indexes,
        )
        self.backup_sheets_printed = True
        self._refresh_action_buttons()

    def _on_seed_words_attached_toggled(self, checked: bool) -> None:
        self.seed_words_attached_confirmed = checked
        self._refresh_action_buttons()

    def _refresh_action_buttons(self) -> None:
        self.checkbox_seed_words_attached.setEnabled(self.backup_sheets_printed)
        self.checkbox_seed_words_attached.setChecked(self.seed_words_attached_confirmed)
        self.button_next.setEnabled(self.backup_sheets_printed and self.seed_words_attached_confirmed)

    def _refresh_styles(self) -> None:
        surface_colors = get_neutral_surface_colors()
        muted_text = to_color_name(surface_colors.muted_text)
        divider = to_color_name(color_with_alpha(surface_colors.panel_border, 75))
        palette = self.refs.container.palette()
        accent_color = palette.color(QPalette.ColorRole.Highlight).name()
        accent_text_color = palette.color(QPalette.ColorRole.HighlightedText).name()
        link_color = palette.color(QPalette.ColorRole.Link).name()

        self.distribution_table.setStyleSheet(
            self.distribution_table.styleSheet()
            + f"\nQLabel a {{ color: {link_color}; text-decoration: none; }}"
        )
        self.left_section_badge.setStyleSheet(
            f"border-radius: 20px; background-color: {accent_color}; color: {accent_text_color};"
        )
        self.right_section_badge.setStyleSheet(
            f"border-radius: 20px; background-color: {accent_color}; color: {accent_text_color};"
        )
        self.label_description.setStyleSheet(f"color: {muted_text};")
        self.label_left_subtitle.setStyleSheet(f"color: {muted_text};")
        self.label_right_subtitle.setStyleSheet(f"color: {muted_text};")
        self.checkbox_seed_words_attached.setStyleSheet(
            f"QCheckBox {{ padding-top: 4px; border-top: 1px solid {divider}; }}"
        )

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        m, n = self.refs.qtwalletbase.get_mn_tuple()
        self.label_title.setText(self.tr("Congratulations, your wallet is ready. Now protect it!"))
        if self._is_single_sig():
            self.label_description.setText(
                self.tr(
                    "Your wallet is protected by its recovery sheet, which should be stored somewhere different from where your hardware signer is. Print it, attach the seed and store it in a secure, access controlled location. With the seed words you have full control over your wallet."
                )
            )
        else:
            self.label_description.setText(
                self.tr(
                    "Your wallet is protected by {n} backup sheets with attached seeds stored in different locations. Print them and place them in secure, access controlled locations. With {m} of them you have full control over your wallet."
                ).format(n=n, m=m)
            )
        self.label_left_title.setText(self.tr("Backup Recovery Sheet (required)"))
        self.label_left_subtitle.setText(
            self.tr(
                "Follow the steps below to ensure you create a secure backup to restore your funds in the worst case scenario."
            )
        )
        self.label_print_section.setText(
            html_f("A. ", bf=True)
            + self.tr("Print the recovery sheets associated with the devices that you possess and control.")
        )
        self.button_print_backup_sheets.setText(self.tr("1. Print backup sheets"))
        self.label_seed_words_section.setText(
            html_f("B. ", bf=True)
            + self.tr(
                "Once printed, handwrite the seed phrase from your device onto the sheet, or confirm it is already transcribed on a separate piece of paper stored with it."
            )
        )
        self.checkbox_seed_words_attached.setText(
            self.tr("Yes, I confirm seed words are attached to the printout")
        )

        if self._is_single_sig():
            self.label_right_title.setText(self.tr("Distribute to 2 separate locations"))
            self.label_right_subtitle.setText(
                self.tr(
                    "Store the signer device and the backup sheet with seed words in separate secure locations."
                )
            )
        else:
            self.label_right_title.setText(self.tr("Distribute to {n} separate locations").format(n=n))
            self.label_right_subtitle.setText(
                self.tr(
                    "Store each signer together with its backup sheet and seed words in the same location."
                )
            )

        self._refresh_styles()
        self._rebuild_sheet_previews()
        self._rebuild_distribution_table()
        self._refresh_action_buttons()

    def set_visibilities(self, should_be_visible: bool) -> None:
        """Refresh button state each time the step becomes visible."""
        if should_be_visible:
            self._refresh_action_buttons()
