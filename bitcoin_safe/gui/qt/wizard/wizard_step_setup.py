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

import enum
from dataclasses import dataclass
from typing import cast

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.constants import FORM_LABEL_FIELD_SPACING
from bitcoin_safe.descriptors import get_default_address_type
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet
from bitcoin_safe.gui.qt.step_progress_bar import TutorialWidget

from ..styled_card_frame import BaseCardFrame
from ..util import (
    AspectRatioSvgWidget,
    Message,
    MessageType,
    color_with_alpha,
    get_neutral_surface_colors,
    svg_tools,
    to_color_name,
)
from .wizard_support import BaseTab, WizardTabInfo


@dataclass(frozen=True)
class WalletTemplateContent:
    option_title: str
    option_subtitle: str
    detail_title: str
    summary: str
    backup_note: str
    pros: tuple[str, ...]
    cons: tuple[str, ...]
    required_signers: int
    total_signers: int
    svg_content: str


class BaseWalletTemplateCardFrame(BaseCardFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected = False
        self.border_width = 1

    def _get_style_content(self):
        surface_colors = get_neutral_surface_colors()
        border_color = (
            self.palette().color(QPalette.ColorRole.Mid) if self._selected else surface_colors.panel_border
        )

        s = super()._get_style_content()
        s += f"\nborder: {self.border_width}px solid {to_color_name(border_color)};"
        return s


class WalletTemplateOption(BaseWalletTemplateCardFrame):
    signal_selected = cast(SignalProtocol[[object]], pyqtSignal(object))

    def __init__(self, template: object, svg_content: str, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.template = template

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        self.icon = AspectRatioSvgWidget(svg_content=svg_content, parent=self)
        self.icon.setFixedSize(35, 35)
        layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_widget = QWidget(self)
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.label_title = QLabel(text_widget)
        title_font = self.label_title.font()
        title_font.setBold(True)
        self.label_title.setFont(title_font)
        text_layout.addWidget(self.label_title)

        self.label_subtitle = QLabel(text_widget)
        self.label_subtitle.setWordWrap(True)
        text_layout.addWidget(self.label_subtitle)
        layout.addWidget(text_widget, stretch=1)

        for child in (self.icon, text_widget, self.label_title, self.label_subtitle):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.refresh_style()

    def set_texts(self, title: str, subtitle: str) -> None:
        """Set the option texts."""
        self.label_title.setText(title)
        self.label_subtitle.setText(subtitle)

    def set_selected(self, selected: bool) -> None:
        """Update the selected state."""
        if self._selected == selected:
            return
        self._selected = selected
        self.refresh_style()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        """Select the template when the card is clicked."""
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.signal_selected.emit(self.template)
            a0.accept()
            return
        super().mouseReleaseEvent(a0)

    def refresh_style(self) -> None:
        """Refresh the card styling."""
        surface_colors = get_neutral_surface_colors()
        title_color = self.palette().color(QPalette.ColorRole.WindowText).name()

        self.label_title.setStyleSheet(f"color: {title_color};")
        self.label_subtitle.setStyleSheet(f"color: {to_color_name(surface_colors.muted_text)};")

        self.background_color = surface_colors.panel_background if self._selected else None
        super().refresh_style()


class WalletTemplateStatCard(BaseWalletTemplateCardFrame):
    _peferred_width = 200

    def __init__(self, title: str, svg_content: str, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self._title = title
        self._svg_content = svg_content

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMaximumWidth(self._peferred_width)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self.icon = AspectRatioSvgWidget(parent=self)
        self.icon.setFixedSize(35, 35)
        layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignTop)

        text_widget = QWidget(self)
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        self.label_value = QLabel(text_widget)
        value_font = self.label_value.font()
        value_font.setBold(True)
        value_font.setPointSize(value_font.pointSize() + 2)
        self.label_value.setFont(value_font)
        header_layout.addWidget(self.label_value)

        self.label_title = QLabel(self._title, text_widget)
        title_font = self.label_title.font()
        title_font.setBold(True)
        self.label_title.setFont(title_font)
        header_layout.addWidget(self.label_title)
        header_layout.addStretch()
        text_layout.addLayout(header_layout)

        self.label_subtitle = QLabel(text_widget)
        text_layout.addWidget(self.label_subtitle)
        layout.addWidget(text_widget, stretch=1)

        self.refresh_style()

    def sizeHint(self) -> QSize:
        """SizeHint."""
        size = super().sizeHint()
        size.setWidth(self._peferred_width)
        return size

    def set_value(self, value: int, singular_noun: str, plural_noun: str) -> None:
        """Update the displayed count and noun."""
        self.label_value.setText(str(value))
        self.label_subtitle.setText(singular_noun if value == 1 else plural_noun)

    def set_title(self, title: str) -> None:
        """Update the title shown next to the count."""
        self._title = title
        self.label_title.setText(title)

    def set_svg_content(self, svg_content: str) -> None:
        """Update the card icon."""
        self._svg_content = svg_content
        self._refresh_icon()

    def refresh_style(self) -> None:
        """Refresh the card styling."""
        surface_colors = get_neutral_surface_colors()
        text_color = self.palette().color(QPalette.ColorRole.WindowText).name()
        self.label_value.setStyleSheet(f"color: {text_color};")
        self.label_title.setStyleSheet(f"color: {text_color};")
        self.label_subtitle.setStyleSheet(f"color: {to_color_name(surface_colors.muted_text)};")
        self._refresh_icon()
        super().refresh_style()

    def _refresh_icon(self) -> None:
        icon_color = self.palette().color(QPalette.ColorRole.WindowText).name()
        self.icon.setSvgContent(self._svg_content.replace("currentColor", icon_color))


class WalletSetupOptions(BaseTab):
    def __init__(
        self, refs: WizardTabInfo, loop_in_thread: LoopInThread, show_previous_step_button: bool
    ) -> None:
        """Initialize instance."""
        super().__init__(
            refs=refs, loop_in_thread=loop_in_thread, show_previous_step_button=show_previous_step_button
        )
        self.show_previous_step_button = False

    class WalletTemplate(enum.Enum):
        single_sig = enum.auto()
        two_of_three = enum.auto()
        three_of_five = enum.auto()

    class WalletTemplateStatIcon(enum.Enum):
        required_signers = enum.auto()
        recovery_signers = enum.auto()
        total_signers = enum.auto()

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(28, 24, 28, 24)
        widget_layout.setSpacing(22)
        widget_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        grid = QGridLayout()
        grid.setVerticalSpacing(14)
        grid.setColumnMinimumWidth(1, FORM_LABEL_FIELD_SPACING)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(2, 1)

        self.label_wallet_name = QLabel(widget)
        self.edit_wallet_name = QLineEdit(widget)
        self.edit_wallet_name.textChanged.connect(self._on_wallet_name_changed)

        self.label_templates = QLabel(widget)
        title_font = self.label_templates.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        self.label_templates.setFont(title_font)

        self.label_template_hint = QLabel(widget)
        self.label_template_hint.setWordWrap(True)

        self.label_template_description = QLabel(widget)
        self.label_template_description.setWordWrap(True)

        self.label_template_backup = QLabel(widget)
        self.label_template_backup.setWordWrap(True)

        self.label_template_pros = QLabel(widget)
        self.label_template_pros.setWordWrap(True)
        self.label_template_pros.setTextFormat(Qt.TextFormat.RichText)

        self.label_template_cons = QLabel(widget)
        self.label_template_cons.setWordWrap(True)
        self.label_template_cons.setTextFormat(Qt.TextFormat.RichText)

        self.template_divider = QFrame(widget)
        self.template_divider.setFixedWidth(1)

        self.template_options: dict[WalletSetupOptions.WalletTemplate, WalletTemplateOption] = {}
        self._selected_template_value = self.WalletTemplate.two_of_three
        self.card_required_signers = WalletTemplateStatCard(
            title=self.tr("Required"),
            svg_content="",
            parent=widget,
        )
        self.card_recovery_signers = WalletTemplateStatCard(
            title=self.tr("Recovery"),
            svg_content="",
            parent=widget,
        )
        self.card_total_signers = WalletTemplateStatCard(
            title=self.tr("Total"),
            svg_content="",
            parent=widget,
        )

        grid.addWidget(self.label_wallet_name, 0, 0)
        grid.addWidget(self.edit_wallet_name, 0, 2)
        widget_layout.addLayout(grid)

        template_layout = QHBoxLayout()
        template_layout.setContentsMargins(0, 0, 0, 0)
        template_layout.setSpacing(24)

        left_widget = QWidget(widget)
        left_widget.setMinimumWidth(280)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        left_layout.addWidget(self.label_templates)
        left_layout.addWidget(self.label_template_hint)

        self.template_options_layout = QVBoxLayout()
        self.template_options_layout.setContentsMargins(0, 0, 0, 0)
        self.template_options_layout.setSpacing(12)
        left_layout.addLayout(self.template_options_layout)
        left_layout.addStretch()

        right_widget = QWidget(widget)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)

        detail_font = self.label_template_description.font()
        detail_font.setBold(True)
        detail_font.setPointSize(detail_font.pointSize() + 2)
        self.label_template_description.setFont(detail_font)

        right_layout.addWidget(self.label_template_description)
        self.summary_cards_layout = QHBoxLayout()
        self.summary_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_cards_layout.setSpacing(10)
        self.summary_cards_layout.addWidget(self.card_required_signers)
        self.summary_cards_layout.addWidget(self.card_recovery_signers)
        self.summary_cards_layout.addWidget(self.card_total_signers)
        self.summary_cards_layout.addStretch()
        right_layout.addLayout(self.summary_cards_layout)
        right_layout.addWidget(self.label_template_backup)
        right_layout.addWidget(self.label_template_pros)
        right_layout.addWidget(self.label_template_cons)
        right_layout.addSpacing(6)
        right_layout.addStretch()

        template_layout.addWidget(left_widget)
        template_layout.addWidget(self.template_divider)
        template_layout.addWidget(right_widget, stretch=1)
        widget_layout.addLayout(template_layout)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )

        self.button_next.clicked.disconnect()
        self.button_next.clicked.connect(self._on_continue)
        self.button_next.setDefault(True)

        self._create_template_options()
        self._set_ui_from_protowallet()
        self.updateUi()
        return tutorial_widget

    def _create_template_options(self) -> None:
        if self.template_options:
            return
        for template in self.WalletTemplate:
            content = self._template_content(template)
            option = WalletTemplateOption(
                template=template,
                svg_content=content.svg_content,
            )
            option.signal_selected.connect(self._on_template_option_selected)
            self.template_options_layout.addWidget(option)
            self.template_options[template] = option

    def _template_content(self, template: WalletTemplate) -> WalletTemplateContent:
        details = {
            self.WalletTemplate.single_sig: WalletTemplateContent(
                option_title=self.tr("Simple cold storage"),
                option_subtitle=self.tr("1 Signer"),
                detail_title=self.tr("Simple cold storage (1 Signer)"),
                summary=self.tr("Self-custody with 1 signer and 1 seed backup."),
                backup_note=self.tr(
                    "Store the seed backup separately from the device to avoid one-point failure."
                ),
                pros=(self.tr("Low complexity"),),
                cons=(
                    self.tr("If the signer device and seed backup is lost, then the funds are lost"),
                    self.tr("Requires 1 secure access-controlled place to store the seed backup"),
                ),
                required_signers=1,
                total_signers=1,
                svg_content=svg_tools.get_svg_content("shield-single-sig.svg"),
            ),
            self.WalletTemplate.two_of_three: WalletTemplateContent(
                option_title=self.tr("Long-term cold storage"),
                option_subtitle=self.tr("2-of-3 Multi Signature"),
                detail_title=self.tr("Long-term cold storage (2-of-3 Multi Signature)"),
                summary=self.tr("Robust wallet for long-term self-custody."),
                backup_note=self.tr(
                    "The recovery sheet with the wallet descriptor should be stored with each seed backup."
                ),
                pros=(self.tr("Can tolerate loss of 1 signing device and its backup seed"),),
                cons=(
                    self.tr("Medium complexity"),
                    self.tr("Requires 3 secure access-controlled places to store the seed backups"),
                ),
                required_signers=2,
                total_signers=3,
                svg_content=svg_tools.get_svg_content("shield-2-of-3.svg"),
            ),
            self.WalletTemplate.three_of_five: WalletTemplateContent(
                option_title=self.tr("Super robust storage"),
                option_subtitle=self.tr("3-of-5 Multi Signature"),
                detail_title=self.tr("Super robust storage (3-of-5 Multi Signature)"),
                summary=self.tr("Robust wallet for long-term self-custody."),
                backup_note=self.tr(
                    "The recovery sheet with the wallet descriptor should be stored with each seed backup."
                ),
                pros=(self.tr("Can tolerate loss of 2 signing devices and its backup seeds"),),
                cons=(
                    self.tr("High complexity"),
                    self.tr("Requires 5 secure access-controlled places to store the seed backups"),
                ),
                required_signers=3,
                total_signers=5,
                svg_content=svg_tools.get_svg_content("shield-3-of-5.svg"),
            ),
        }
        return details[template]

    def _template_from_protowallet(self) -> WalletTemplate:
        m, n = self.refs.qtwalletbase.get_mn_tuple()
        if (m, n) == (1, 1):
            return self.WalletTemplate.single_sig
        if (m, n) == (2, 3):
            return self.WalletTemplate.two_of_three
        return self.WalletTemplate.three_of_five

    def _selected_template(self) -> WalletTemplate:
        return self._selected_template_value

    def _stat_card_svg_content(self, template: WalletTemplate, icon_type: WalletTemplateStatIcon) -> str:
        icon_filenames = {
            self.WalletTemplate.single_sig: {
                self.WalletTemplateStatIcon.required_signers: "shield-single-sig - signers.svg",
                self.WalletTemplateStatIcon.recovery_signers: "shield-single-sig - recovery.svg",
                self.WalletTemplateStatIcon.total_signers: "shield-single-sig.svg",
            },
            self.WalletTemplate.two_of_three: {
                self.WalletTemplateStatIcon.required_signers: "shield-2-of-3 - signers.svg",
                self.WalletTemplateStatIcon.recovery_signers: "shield-2-of-3 - recovery.svg",
                self.WalletTemplateStatIcon.total_signers: "shield-2-of-3.svg",
            },
            self.WalletTemplate.three_of_five: {
                self.WalletTemplateStatIcon.required_signers: "shield-3-of-5 - signers.svg",
                self.WalletTemplateStatIcon.recovery_signers: "shield-3-of-5 - recovery.svg",
                self.WalletTemplateStatIcon.total_signers: "shield-3-of-5.svg",
            },
        }
        return svg_tools.get_svg_content(icon_filenames[template][icon_type])

    def _set_ui_from_protowallet(self) -> None:
        self.edit_wallet_name.setText(self.refs.qtwalletbase.get_editable_protowallet().id)
        self._set_selected_template(self._template_from_protowallet())

    def _on_wallet_name_changed(self, wallet_name: str) -> None:
        wallet_name = wallet_name.strip()
        self.refs.qtwalletbase.get_editable_protowallet().id = wallet_name
        if isinstance(self.refs.qtwalletbase, QTProtoWallet):
            self.refs.qtwalletbase.set_wallet_id(wallet_name)

    def _on_template_option_selected(self, template: object) -> None:
        self._set_selected_template(cast(WalletSetupOptions.WalletTemplate, template))

    def _set_selected_template(self, template: WalletTemplate) -> None:
        self._selected_template_value = template
        for current_template, option in self.template_options.items():
            option.set_selected(current_template == template)
        self._refresh_summary()
        self._sync_step_labels()

    def _refresh_summary(self) -> None:
        selected_template = self._selected_template()
        content = self._template_content(selected_template)
        self.label_template_description.setText(content.detail_title)
        self.label_template_backup.setText(f"{content.summary}\n\n{content.backup_note}")
        self.label_template_pros.setText(self._bulletpoints_html(content.pros, title=self.tr("Pros")))
        self.label_template_cons.setText(self._bulletpoints_html(content.cons, title=self.tr("Cons")))
        self.card_required_signers.set_svg_content(
            self._stat_card_svg_content(selected_template, self.WalletTemplateStatIcon.required_signers)
        )
        self.card_required_signers.set_value(
            value=content.required_signers,
            singular_noun=self.tr("signer"),
            plural_noun=self.tr("signers"),
        )
        self.card_recovery_signers.set_svg_content(
            self._stat_card_svg_content(selected_template, self.WalletTemplateStatIcon.recovery_signers)
        )
        self.card_recovery_signers.set_value(
            value=max(content.total_signers - content.required_signers, 0),
            singular_noun=self.tr("signer"),
            plural_noun=self.tr("signers"),
        )
        self.card_total_signers.set_svg_content(
            self._stat_card_svg_content(selected_template, self.WalletTemplateStatIcon.total_signers)
        )
        self.card_total_signers.set_value(
            value=content.total_signers,
            singular_noun=self.tr("signer"),
            plural_noun=self.tr("signers"),
        )

    def _sync_step_labels(self) -> None:
        if wizard := self.wizard_parent():
            wizard.updateUi(mn_tuple=self._selected_mn_tuple())

    def _selected_mn_tuple(self) -> tuple[int, int]:
        content = self._template_content(self._selected_template())
        return (content.required_signers, content.total_signers)

    def _apply_selection(self, update_wizard: bool = False) -> None:
        protowallet = self.refs.qtwalletbase.get_editable_protowallet()
        wallet_name = self.edit_wallet_name.text().strip()
        m, n = self._selected_mn_tuple()

        protowallet.id = wallet_name
        protowallet.set_number_of_keystores(n)
        protowallet.set_threshold(m)
        protowallet.set_address_type(get_default_address_type(is_multisig=n > 1))
        if isinstance(self.refs.qtwalletbase, QTProtoWallet):
            self.refs.qtwalletbase.set_wallet_id(wallet_name)
        if update_wizard and (wizard := self.wizard_parent()):
            wizard.updateUi()

    def _on_continue(self) -> None:
        if not self.edit_wallet_name.text().strip():
            Message(
                self.tr("Please choose a wallet name"),
                type=MessageType.Warning,
                parent=self.refs.container,
            )
            return
        self._apply_selection(update_wizard=True)
        self.refs.go_to_next_index()

    def set_visibilities(self, should_be_visible: bool) -> None:
        """Refresh the summary each time the step is shown."""
        if should_be_visible:
            self._set_ui_from_protowallet()

    def updateUi(self) -> None:
        """UpdateUi."""
        if self.is_closed:
            return
        super().updateUi()
        self.label_wallet_name.setText(self.tr("Wallet name"))
        self.label_templates.setText(self.tr("Choose a wallet template"))
        self.label_template_hint.setText(self.tr("Select a template from the list."))
        self.card_required_signers.set_title(self.tr("Required"))
        self.card_recovery_signers.set_title(self.tr("Recovery"))
        self.card_total_signers.set_title(self.tr("Total"))
        self.button_next.setText(self.tr("Continue"))
        self.button_previous.setText(self.tr("Previous Step"))

        self._refresh_card_style()
        for template, option in self.template_options.items():
            content = self._template_content(template)
            option.set_texts(content.option_title, content.option_subtitle)
            option.refresh_style()
        self._refresh_summary()

    def _refresh_card_style(self) -> None:
        palette = self.refs.container.palette()
        surface_colors = get_neutral_surface_colors()
        divider = to_color_name(color_with_alpha(palette.color(QPalette.ColorRole.Mid), 70))
        title_color = palette.color(QPalette.ColorRole.WindowText).name()
        hint_color = to_color_name(surface_colors.muted_text)
        self.template_divider.setStyleSheet(f"background-color: {divider};")
        self.label_template_description.setStyleSheet(f"color: {title_color};")
        self.label_template_hint.setStyleSheet(f"color: {hint_color};")
        self.label_template_backup.setStyleSheet(f"color: {hint_color};")
        self.card_required_signers.refresh_style()
        self.card_recovery_signers.refresh_style()
        self.card_total_signers.refresh_style()

    def _bulletpoints_html(self, items: tuple[str, ...], title: str) -> str:
        bullet_items = "".join(f"<li>{item}</li>" for item in items)
        return f"<b>{title}</b><ul style='margin-top: 8px; padding-left: 20px;'>{bullet_items}</ul>"
