#
# Bitcoin-Safe
# Copyright (C) 2023-2026 Andreas Griffin
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
from pathlib import Path
from typing import Protocol, cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QHideEvent, QPalette, QShowEvent
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.constants import APP_NAME
from bitcoin_safe.gui.qt.card_base import CardBase, CardExpansionMode
from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode, SidebarTree
from bitcoin_safe.gui.qt.styled_card_frame import BaseBorderCardFrame
from bitcoin_safe.gui.qt.util import (
    Message,
    MessageType,
    color_with_alpha,
    get_neutral_surface_colors,
    is_theme_change_event,
    should_process_theme_change,
    svg_tools,
    to_color_name,
)
from bitcoin_safe.hardware_signers import SUPPORTED_HARDWARE_SIGNERS_URL
from bitcoin_safe.signals import Signals

logger = logging.getLogger(__name__)

METROVAULT_SIGNER_URL = "https://bitcoin-safe.org/en/library/supported-hardware-signers/metrovault/"


class _ConfigWithWalletDir(Protocol):
    wallet_dir: str


class _WindowWithConfig(Protocol):
    config: _ConfigWithWalletDir


class WelcomeActionCard(CardBase):
    clicked = cast(SignalProtocol[[]], pyqtSignal())
    _disabled_opacity = 0.55

    def __init__(self, icon_name: str, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, expansion_mode=CardExpansionMode.FIXED_COLLAPSED)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_header_clickable(True)
        self.set_body_content_visible(False)
        self.signal_header_clicked.connect(self.clicked.emit)
        self.register_header_click_target(self)

        self.root_layout.setContentsMargins(18, 16, 18, 16)
        self.root_layout.setSpacing(0)
        self.header_layout.setSpacing(14)
        self.header_text_layout.setSpacing(4)

        self.label_icon = self.header_icon
        self.label_icon.setFixedWidth(40)
        self.set_icon(icon_name, size=(26, 26))
        self.label_title = self.header_title
        self.label_title.setWordWrap(True)
        self.label_title.setTextFormat(Qt.TextFormat.RichText)
        self.label_description = self.header_subtitle
        self.label_description.setWordWrap(True)
        self.label_description.setTextFormat(Qt.TextFormat.RichText)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._available = True
        self.updateUi()

    def set_content(self, title: str, description: str) -> None:
        """Set the card content."""
        self.label_title.setText(f"<b>{title}</b>")
        self.label_description.setText(description)

    def updateUi(self) -> None:
        """Refresh palette-derived card colors."""
        self._apply_visual_state()
        self._refresh_theme_dependent_ui()

    def set_available(self, available: bool) -> None:
        """Toggle between actionable and greyed-out states without disabling child links."""
        self._available = available
        self.set_header_clickable(available)
        self._apply_visual_state()

    def _is_header_activatable(self) -> bool:
        """Allow unavailable cards to intercept clicks and explain why they are disabled."""
        return not self._available or super()._is_header_activatable()

    def _apply_visual_state(self) -> None:
        self.background_color = get_neutral_surface_colors().panel_background
        self._opacity_effect.setOpacity(
            self._disabled_opacity if not self.isEnabled() or not self._available else 1.0
        )

    def changeEvent(self, a0: QEvent | None) -> None:
        """Refresh card styling when the theme or enabled state changes."""
        super().changeEvent(a0)
        if a0 is not None and (a0.type() == QEvent.Type.EnabledChange or is_theme_change_event(a0)):
            self._apply_visual_state()
            self._refresh_theme_dependent_ui()


class NetworkChoiceCard(CardBase):
    clicked = cast(SignalProtocol[[]], pyqtSignal())
    _refreshing_style = False

    def __init__(self, icon_name: str, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, expansion_mode=CardExpansionMode.FIXED_EXPANDED)
        self._refreshing_style = False
        self.signal_header_clicked.connect(self.clicked.emit)
        self.set_header_clickable(True)
        self.register_header_click_target(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(340)
        self._border_radius = 8
        self.header_widget.hide()
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setContentsMargins(28, 24, 28, 24)
        self.content_layout.setSpacing(0)

        self.label_icon = QLabel(self.content_widget)
        self.label_icon.setFixedSize(34, 34)
        self.label_icon.setPixmap(svg_tools.get_QIcon(icon_name).pixmap(34, 34))
        self.content_layout.addWidget(self.label_icon, alignment=Qt.AlignmentFlag.AlignLeft)

        self.content_layout.addSpacing(16)

        self.label_eyebrow = QLabel(self.content_widget)
        eyebrow_font = self.label_eyebrow.font()
        eyebrow_font.setPointSize(max(eyebrow_font.pointSize() - 1, 8))
        eyebrow_font.setCapitalization(eyebrow_font.Capitalization.AllUppercase)
        self.label_eyebrow.setFont(eyebrow_font)
        self.content_layout.addWidget(self.label_eyebrow)

        self.content_layout.addSpacing(8)

        self.label_title = QLabel(self.content_widget)
        title_font = self.label_title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 6)
        self.label_title.setFont(title_font)
        self.label_title.setWordWrap(True)
        self.content_layout.addWidget(self.label_title)

        self.content_layout.addSpacing(14)

        self.label_description = QLabel(self.content_widget)
        self.label_description.setWordWrap(True)
        self.content_layout.addWidget(self.label_description)

        self.content_layout.addSpacing(14)

        self.label_bullets = QLabel(self.content_widget)
        self.label_bullets.setWordWrap(True)
        self.label_bullets.setTextFormat(Qt.TextFormat.RichText)
        self.content_layout.addWidget(self.label_bullets)
        self.content_layout.addStretch(1)
        self.content_layout.addSpacing(18)

        self.cta_panel = BaseBorderCardFrame(self.content_widget)
        self.cta_panel._border_radius = 8
        cta_layout = QVBoxLayout(self.cta_panel)
        cta_layout.setContentsMargins(18, 12, 18, 12)
        cta_layout.setSpacing(3)

        self.label_cta_title = QLabel(self.cta_panel)
        cta_title_font = self.label_cta_title.font()
        cta_title_font.setBold(True)
        self.label_cta_title.setFont(cta_title_font)
        self.label_cta_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cta_layout.addWidget(self.label_cta_title)

        self.label_cta_caption = QLabel(self.cta_panel)
        cta_caption_font = self.label_cta_caption.font()
        cta_caption_font.setPointSize(max(cta_caption_font.pointSize() - 1, 8))
        self.label_cta_caption.setFont(cta_caption_font)
        self.label_cta_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cta_layout.addWidget(self.label_cta_caption)

        self.content_layout.addWidget(self.cta_panel)

        for widget in (
            self.content_widget,
            self.label_icon,
            self.label_eyebrow,
            self.label_title,
            self.label_description,
            self.label_bullets,
            self.cta_panel,
            self.label_cta_title,
            self.label_cta_caption,
        ):
            self.register_header_click_target(widget)
            widget.setCursor(Qt.CursorShape.PointingHandCursor)

        self.updateUi()

    def set_content(
        self,
        eyebrow: str,
        title: str,
        description: str,
        bullet_points: list[str],
        cta_title: str,
        cta_caption: str,
    ) -> None:
        """Set the card content."""
        self.label_eyebrow.setText(eyebrow)
        self.label_title.setText(title)
        self.label_description.setText(description)
        items = "".join(f"<li>{item}</li>" for item in bullet_points)
        self.label_bullets.setText(
            f"<ul style='margin-top: 0px; margin-bottom: 0px; padding-left: 16px;'>{items}</ul>"
        )
        self.label_cta_title.setText(cta_title)
        self.label_cta_caption.setText(cta_caption)

    def changeEvent(self, a0: QEvent | None) -> None:
        """Refresh card styling when the theme changes."""
        super().changeEvent(a0)
        if (
            not self._refreshing_style
            and a0 is not None
            and is_theme_change_event(a0, include_enabled_change=True)
        ):
            self.updateUi()

    def _get_style_content(self) -> str:
        surface_colors = get_neutral_surface_colors()
        style_content = super()._get_style_content()
        style_content += f"\nborder: 1px solid {to_color_name(surface_colors.panel_border)};"
        return style_content

    def refresh_style(self) -> None:
        """Refresh palette-aware styling."""
        if not hasattr(self, "cta_panel") or self._refreshing_style:
            return
        self._refreshing_style = True
        try:
            super().refresh_style()
            self.cta_panel.refresh_style()
        finally:
            self._refreshing_style = False

    def updateUi(self) -> None:
        """Refresh palette-derived card colors and text styling."""
        if not hasattr(self, "cta_panel") or self._refreshing_style:
            return
        surface_colors = get_neutral_surface_colors()
        palette = self.palette()
        eyebrow_color = to_color_name(color_with_alpha(palette.color(QPalette.ColorRole.WindowText), 120))
        muted_color = to_color_name(surface_colors.muted_text)
        cta_caption_color = to_color_name(color_with_alpha(palette.color(QPalette.ColorRole.WindowText), 145))
        self.background_color = surface_colors.content_background
        self.cta_panel.background_color = surface_colors.panel_background

        self.refresh_style()
        self.label_eyebrow.setStyleSheet(f"color: {eyebrow_color}; font-weight: 600; letter-spacing: 0.08em;")
        self.label_description.setStyleSheet(f"color: {muted_color};")
        self.label_bullets.setStyleSheet(f"color: {muted_color};")
        self.label_cta_caption.setStyleSheet(f"color: {cta_caption_color};")


class NetworkChoiceWelcomeScreen(QWidget):
    signal_onclick_secure_wallet = cast(SignalProtocol[[]], pyqtSignal())
    signal_onclick_safe_playground = cast(SignalProtocol[[]], pyqtSignal())
    signal_remove_me = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(self, signals: Signals, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setVisible(False)
        self.signals = signals

        self.name = "Network choice tab"
        self.create_ui()

        self.card_secure_wallet.clicked.connect(self.on_click_secure_wallet)
        self.card_safe_playground.clicked.connect(self.on_click_safe_playground)

    def remove_me(self) -> None:
        """Remove me."""
        self.signal_remove_me.emit(self)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self.updateUi()

    def on_click_secure_wallet(self) -> None:
        """Continue on mainnet."""
        self.signal_onclick_secure_wallet.emit()
        self.signal_remove_me.emit(self)

    def on_click_safe_playground(self) -> None:
        """Switch to the playground network."""
        self.signal_onclick_safe_playground.emit()
        self.signal_remove_me.emit(self)

    def add_network_choice_welcome_tab(self, main_tabs: SidebarTree[object]) -> None:
        """Add the network-choice tab."""
        if node := main_tabs.root.findNodeByWidget(self):
            node.select()
            return
        main_tabs.root.addChildNode(
            SidebarNode(
                icon="file.svg",
                title=self.tr("Create new wallet"),
                data=self,
                widget=self,
                closable=True,
            )
        )

    def create_ui(self) -> None:
        """Create ui."""
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(14)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.label_title = QLabel(self)
        title_font = self.label_title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 6)
        self.label_title.setFont(title_font)

        self.label_subtitle = QLabel(self)
        subtitle_font = self.label_subtitle.font()
        self.label_subtitle.setFont(subtitle_font)
        self.label_subtitle.setWordWrap(True)

        self.cards_container = QWidget(self)
        self.cards_layout = QHBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(18)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.card_secure_wallet = NetworkChoiceCard("bitcoin-bitcoin.svg", self.cards_container)
        self.card_safe_playground = NetworkChoiceCard("bitcoin-gray.svg", self.cards_container)

        self.cards_layout.addWidget(self.card_secure_wallet, stretch=1)
        self.cards_layout.addWidget(self.card_safe_playground, stretch=1)

        self._layout.addWidget(self.label_title)
        self._layout.addWidget(self.label_subtitle)
        self._layout.addWidget(self.cards_container)
        self._layout.addStretch()

        self.updateUi()
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.label_title.setText(self.tr("Where would you like to start?"))
        self.label_subtitle.setText(
            self.tr(
                "Start transact with sound money or learn in a secure playground. Either way, you can always create another wallet later."
            )
        )
        self.card_secure_wallet.updateUi()
        self.card_safe_playground.updateUi()

        self.card_secure_wallet.set_content(
            eyebrow=self.tr("Real sound money (BTC)"),
            title=self.tr("Manage Real Funds"),
            description=self.tr(
                "Already familiar with Bitcoin? Set up a wallet that holds and moves real value with confidence."
            ),
            bullet_points=[
                self.tr("Send and receive real bitcoin"),
                self.tr("Best for long-term storage"),
                self.tr("Transactions are permanent"),
                self.tr("Keep your seed phrase safe"),
            ],
            cta_title=self.tr("Setup a Wallet"),
            cta_caption=self.tr("Uses onchain Mainnet network"),
        )
        self.card_safe_playground.set_content(
            eyebrow=self.tr("Test coins (tBTC) have no value"),
            title=self.tr("Explore Playground"),
            description=self.tr(
                "Practice in a risk-free environment and see exactly how everything works. Try sending, receiving, changing fees using test coins that you can lose without regret."
            ),
            bullet_points=[
                self.tr("Explore with a demo wallet"),
                self.tr("Test coins, no monetary value"),
                self.tr("Learn safely, risk-free"),
            ],
            cta_title=self.tr("Start Exploring"),
            cta_caption=self.tr("Uses Signet test network"),
        )

    def changeEvent(self, a0: QEvent | None) -> None:
        """Refresh child cards when the application theme changes."""
        super().changeEvent(a0)
        if should_process_theme_change(self, a0):
            self.updateUi()


class NewWalletWelcomeScreen(QWidget):
    signal_onclick_hot_wallet = cast(SignalProtocol[[]], pyqtSignal())
    signal_onclick_connect_devices = cast(SignalProtocol[[]], pyqtSignal())
    signal_onclick_custom_signature = cast(SignalProtocol[[]], pyqtSignal())
    signal_onclick_demo_wallet = cast(SignalProtocol[[]], pyqtSignal())
    signal_remove_me = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))
    visibilityChanged = cast(SignalProtocol[[bool]], pyqtSignal(bool))

    def __init__(
        self,
        network: bdk.Network,
        signals: Signals,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setVisible(False)
        self.signals = signals

        self.name = "New wallet tab"
        self.network = network

        self.create_ui()

        self.card_hot_wallet.clicked.connect(self.on_click_hot_wallet)
        self.card_connect_devices.clicked.connect(self.on_click_connect_devices)
        self.card_custom_wallet.clicked.connect(self.on_click_custom_wallet)
        self.card_demo_wallet.clicked.connect(self.on_click_demo_wallet)
        logger.debug(f"initialized welcome_screen = {self.__class__.__name__}")

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self.updateUi()
        self.visibilityChanged.emit(True)

    def hideEvent(self, a0: QHideEvent | None) -> None:
        super().hideEvent(a0)
        self.visibilityChanged.emit(False)

    @property
    def wallet_name(self) -> str:
        """Wallet name."""
        return self.edit_wallet_name.text().strip()

    def set_wallet_name(self, wallet_name: str) -> None:
        """Set the suggested wallet name."""
        self.edit_wallet_name.setText(wallet_name)

    def remove_me(self) -> None:
        """Remove me."""
        self.signal_remove_me.emit(self)

    def on_click_hot_wallet(self) -> None:
        """Create a hot wallet."""
        if self.network == bdk.Network.BITCOIN:
            Message(
                self.tr(
                    "Hot wallets are disabled on Bitcoin Mainnet.\n"
                    "You can switch to Testnet to test {app_name} without using real Bitcoin."
                ).format(app_name=APP_NAME),
                type=MessageType.Warning,
                parent=self,
            )
            return
        self.signal_onclick_hot_wallet.emit()
        self.signal_remove_me.emit(self)

    def on_click_connect_devices(self) -> None:
        """Open the device connection flow."""
        self.signal_onclick_connect_devices.emit()
        self.signal_remove_me.emit(self)

    def on_click_custom_wallet(self) -> None:
        """Open the custom or recovery flow."""
        self.signal_onclick_custom_signature.emit()
        self.signal_remove_me.emit(self)

    def open_custom_wallet_dialog(self) -> None:
        """Compatibility entry point for callers that expect a wallet-name dialog."""
        main_window = self.window()
        wallet_dir = Path(".")
        if main_window is not None and hasattr(main_window, "config"):
            configured_window = cast(_WindowWithConfig, main_window)
            wallet_dir = Path(configured_window.config.wallet_dir)
        dialog = WalletIdDialog(wallet_dir=wallet_dir, parent=self)

        def on_finished(result: int) -> None:
            if result == int(QDialog.DialogCode.Accepted):
                self.set_wallet_name(dialog.wallet_id)
                self.on_click_custom_wallet()
            dialog.deleteLater()

        dialog.finished.connect(on_finished)
        dialog.open()

    def on_click_demo_wallet(self) -> None:
        """Open the demo wallet."""
        self.signal_onclick_demo_wallet.emit()
        self.signal_remove_me.emit(self)

    def add_new_wallet_welcome_tab(self, main_tabs: SidebarTree[object]) -> None:
        """Add new wallet welcome tab."""
        if node := main_tabs.root.findNodeByWidget(self):
            node.select()
            return
        main_tabs.root.addChildNode(
            SidebarNode(
                icon="file.svg",
                title=self.tr("Create new wallet"),
                data=self,
                widget=self,
                closable=True,
            )
        )

    def create_ui(self) -> None:
        """Create ui."""
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(16)

        self.left_column = QWidget(self)
        self.left_column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.left_layout = QVBoxLayout(self.left_column)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(16)

        self.header_wallet_name = QLabel(self.left_column)
        self.header_wallet_name.setTextFormat(Qt.TextFormat.RichText)

        self.edit_wallet_name = QLineEdit(self.left_column)
        self.edit_wallet_name.setPlaceholderText(self.tr("wallet_name"))

        self.card_demo_wallet = WelcomeActionCard("bi--wallet2.svg", self.left_column)
        self.card_hot_wallet = WelcomeActionCard("bi--dice-5.svg", self.left_column)
        self.card_connect_devices = WelcomeActionCard(
            "hardware_signers/generic-hardware-wallet-icon.svg", self.left_column
        )
        self.card_custom_wallet = WelcomeActionCard("material-symbols--signature.svg", self.left_column)
        self.hot_wallet_help_label = IconLabel(parent=self.card_hot_wallet.header_widget)
        self.hot_wallet_help_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.card_hot_wallet.header_right_layout.addWidget(self.hot_wallet_help_label)
        self.connect_devices_help_label = IconLabel(parent=self.card_connect_devices.header_widget)
        self.connect_devices_help_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.card_connect_devices.header_right_layout.addWidget(self.connect_devices_help_label)
        self.pushButton_demo_wallet = self.on_click_demo_wallet
        self.pushButton_hot_wallet = self.on_click_hot_wallet
        self.pushButton_connect_devices = self.on_click_connect_devices
        self.pushButton_custom_wallet = self.open_custom_wallet_dialog

        self.left_layout.addWidget(self.header_wallet_name)
        self.left_layout.addWidget(self.edit_wallet_name)
        self.left_layout.addSpacing(8)
        self.left_layout.addWidget(self.card_demo_wallet)
        self.left_layout.addWidget(self.card_hot_wallet)
        self.left_layout.addWidget(self.card_connect_devices)
        self.left_layout.addWidget(self.card_custom_wallet)
        self.left_layout.addStretch()

        self._layout.addWidget(self.left_column)

        self.updateUi()
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.header_wallet_name.setText(f"<b>{self.tr('Wallet name')}</b>")

        on_mainnet = self.network == bdk.Network.BITCOIN
        on_testnet = not on_mainnet

        self.card_demo_wallet.setVisible(on_testnet)
        self.card_hot_wallet.set_available(on_testnet)
        self.card_demo_wallet.updateUi()
        self.card_hot_wallet.updateUi()
        self.card_connect_devices.updateUi()
        self.card_custom_wallet.updateUi()

        self.card_demo_wallet.set_content(
            title=self.tr("Public Demo wallet"),
            description=self.tr("Play with an existing wallet that has some test coins to explore safely."),
        )
        self.card_hot_wallet.set_content(
            title=self.tr("Hot Single Signature Wallet"),
            description=(
                self.tr(
                    "Quickly generate a wallet for immediate use, no existing keys required.<br>"
                    "<small>Generating and storing keys on an internet-connected computer is insecure. "
                    "A general-purpose computer is not designed to hold secrets representing money.</small>"
                )
                if on_testnet
                else self.tr(
                    "Quickly generate a wallet for immediate use, no existing keys required.<br>"
                    "<small>Disabled on Mainnet because an internet-connected computer is not designed "
                    "to safely hold secrets representing money.</small>"
                )
            ),
        )
        self.hot_wallet_help_label.setVisible(on_mainnet)
        self.hot_wallet_help_label.setText(self.tr("No signer available?"))
        self.hot_wallet_help_label.set_icon_as_help(
            self.tr("Learn how to turn an Android phone into a dedicated bitcoin signer."),
            METROVAULT_SIGNER_URL,
        )
        self.card_connect_devices.set_content(
            title=self.tr("Connect Device(s)"),
            description=self.tr("Guided setup for your self-custody wallet."),
        )
        self.connect_devices_help_label.setText(self.tr("Supported signers"))
        self.connect_devices_help_label.set_icon_as_help(
            self.tr("Open the list of supported hardware wallets and signers."),
            SUPPORTED_HARDWARE_SIGNERS_URL,
        )
        self.card_custom_wallet.set_content(
            title=self.tr("Custom / Recovery"),
            description=self.tr("Restore a wallet from hardware wallet(s) or a descriptor."),
        )

    def changeEvent(self, a0: QEvent | None) -> None:
        """Refresh child cards when the application theme changes."""
        super().changeEvent(a0)
        if should_process_theme_change(self, a0):
            self.updateUi()
