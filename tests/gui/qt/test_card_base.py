#
# Bitcoin-Safe
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

from unittest.mock import Mock

import bdkpython as bdk
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.card_base import CardBase, CardExpansionMode, CardList
from bitcoin_safe.gui.qt.new_wallet_welcome_screen import (
    METROVAULT_SIGNER_URL,
    NetworkChoiceCard,
    NetworkChoiceWelcomeScreen,
    NewWalletWelcomeScreen,
    WelcomeActionCard,
)
from bitcoin_safe.gui.qt.util import get_neutral_surface_colors, to_color_name
from bitcoin_safe.gui.qt.wizard.wizard_step_cards import TutorialTxCard, TutorialTxCardState
from bitcoin_safe.signals import Signals
from bitcoin_safe.theme import create_dark_palette, create_light_palette


def _make_card(title: str, body_height: int = 120) -> CardBase:
    card = CardBase()
    card.set_title(title)
    body = QLabel("body", card.content_widget)
    body.setFixedHeight(body_height)
    card.set_content_widget(body)
    card.set_body_content_visible(True)
    return card


def test_card_base_expansion_modes(qtbot: QtBot) -> None:
    card = _make_card("Expandable")
    qtbot.addWidget(card)
    card.show()

    assert card.is_expanded
    assert not card.content_widget.isHidden()
    assert card.separator.isHidden()

    card.collapse()
    assert not card.is_expanded
    assert card.content_widget.isHidden()

    card.set_expansion_mode(CardExpansionMode.FIXED_COLLAPSED)
    card.expand()
    assert not card.is_expanded
    assert card.content_widget.isHidden()

    card.set_expansion_mode(CardExpansionMode.FIXED_EXPANDED)
    card.collapse()
    assert card.is_expanded
    assert not card.content_widget.isHidden()


def test_card_base_collapsed_height_is_compact(qtbot: QtBot) -> None:
    card = _make_card("Sizing")
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)

    expanded_height = card.sizeHint().height()

    card.collapse()
    qtbot.wait(10)
    collapsed_height = card.sizeHint().height()

    assert collapsed_height < expanded_height
    assert card.content_widget.isHidden()


def test_card_list_only_one_expanded_at_a_time(qtbot: QtBot) -> None:
    card_list = CardList()
    card_list.set_only_one_expanded_at_a_time(True)
    cards = [_make_card(f"Card {index}") for index in range(3)]
    for card in cards:
        card_list.add_card(card)

    qtbot.addWidget(card_list)
    card_list.show()
    qtbot.waitExposed(card_list)

    card_list.collapse_all()
    assert all(not card.is_expanded for card in cards)

    card_list.expand_only(1)
    assert card_list.current_index() == 1
    assert not cards[0].is_expanded
    assert cards[1].is_expanded
    assert not cards[2].is_expanded

    qtbot.mouseClick(cards[2].header_title, Qt.MouseButton.LeftButton)
    assert card_list.current_index() == 2
    assert not cards[0].is_expanded
    assert not cards[1].is_expanded
    assert cards[2].is_expanded


def test_card_list_prefers_one_expanded_card_height(qtbot: QtBot) -> None:
    card_list = CardList()
    cards = [
        _make_card("Small", body_height=40),
        _make_card("Large", body_height=180),
        _make_card("Medium", body_height=90),
    ]
    for card in cards:
        card_list.add_card(card)
    card_list.collapse_all()

    qtbot.addWidget(card_list)
    card_list.show()
    qtbot.waitExposed(card_list)

    collapsed_total = sum(card.preferred_size_hint(expanded=False).height() for card in cards)
    one_expanded_total = cards[0].preferred_size_hint(expanded=True).height() + sum(
        card.preferred_size_hint(expanded=False).height() for card in cards[1:]
    )

    assert card_list.sizeHint().height() > collapsed_total
    assert card_list.sizeHint().height() >= one_expanded_total

    card_list.expand_only(1)
    assert card_list.sizeHint().height() >= cards[1].preferred_size_hint(expanded=True).height()
    assert card_list.sizeHint().height() > one_expanded_total


def test_send_test_card_fixed_collapsed_has_no_body_height(qtbot: QtBot) -> None:
    card = TutorialTxCard()
    card.set_header("Self-Send Test 1", "Pending", "bi--send.svg")
    card.set_content_widget(QLabel("content", card.content_widget))
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)

    expanded_height = card.sizeHint().height()

    card.set_expansion_mode(CardExpansionMode.FIXED_COLLAPSED)
    qtbot.wait(10)
    collapsed_height = card.sizeHint().height()

    assert collapsed_height < expanded_height
    assert card.content_widget.isHidden()


def test_send_test_card_clickable_header_emits_when_fixed_collapsed(qtbot: QtBot) -> None:
    card = TutorialTxCard()
    card.set_header("Self-Send Test 1", "Completed", "bi--clock-history.svg")
    card.set_expansion_mode(CardExpansionMode.FIXED_COLLAPSED)
    card.set_clickable_header(True)
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)

    with qtbot.waitSignal(card.signal_header_activated):
        qtbot.mouseClick(card.header_widget, Qt.MouseButton.LeftButton)


def test_tutorial_tx_card_apply_state_updates_all_card_properties(qtbot: QtBot) -> None:
    card = TutorialTxCard()
    card.set_content_widget(QLabel("content", card.content_widget))
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)

    card.apply_state(
        TutorialTxCardState(
            title="Receive Test",
            subtitle="Completed - txid deadbeef",
            icon_name="confirmed.svg",
            expansion_mode=CardExpansionMode.FIXED_COLLAPSED,
            clickable=True,
            expanded=False,
            hidden=False,
        )
    )

    pixmap = card.header_icon.pixmap()

    assert card.header_title.text() == "Receive Test"
    assert card.header_subtitle.text() == "Completed - txid deadbeef"
    assert pixmap is not None and not pixmap.isNull()
    assert card.expansion_mode() == CardExpansionMode.FIXED_COLLAPSED
    assert not card.is_expanded
    assert card.content_widget.isHidden()
    assert card.header_widget.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert not card.isHidden()

    card.apply_state(
        TutorialTxCardState(
            title="Hidden",
            subtitle="",
            icon_name="bi--send.svg",
            expansion_mode=CardExpansionMode.FIXED_EXPANDED,
            clickable=False,
            expanded=True,
            hidden=True,
        )
    )

    assert card.isHidden()
    assert card.expansion_mode() == CardExpansionMode.FIXED_EXPANDED
    assert card.is_expanded
    assert not card.content_widget.isHidden()
    assert card.header_widget.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_welcome_action_card_uses_card_base_clickable_header(qtbot: QtBot) -> None:
    card = WelcomeActionCard("bi--wallet2.svg")
    card.set_content("Demo", "Description")
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)

    assert card.expansion_mode() == CardExpansionMode.FIXED_COLLAPSED
    assert card.content_widget.isHidden()
    assert card.label_title.text() == "<b>Demo</b>"
    assert card.label_description.text() == "Description"

    with qtbot.waitSignal(card.clicked):
        qtbot.mouseClick(card.header_title, Qt.MouseButton.LeftButton)


def test_welcome_action_card_update_ui_refreshes_background(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    card = WelcomeActionCard("bi--wallet2.svg")
    qtbot.addWidget(card)
    card.set_content("Demo", "Description")

    def apply_palette(window: str, text: str) -> tuple[str, str, str]:
        palette = QPalette(original_palette)
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.Base, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        palette.setColor(QPalette.ColorRole.Text, QColor(text))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(text))
        app.setPalette(palette)
        card.changeEvent(QEvent(QEvent.Type.PaletteChange))
        return (
            to_color_name(card.background_color),
            card.label_title.palette().color(card.label_title.foregroundRole()).name(),
            card.label_description.palette().color(card.label_description.foregroundRole()).name(),
        )

    try:
        light_background, light_title_style, light_description_style = apply_palette("#ffffff", "#111111")
        dark_background, dark_title_style, dark_description_style = apply_palette("#111111", "#f5f5f5")
    finally:
        app.setPalette(original_palette)
        card.changeEvent(QEvent(QEvent.Type.PaletteChange))

    assert light_background != dark_background
    assert light_title_style != dark_title_style
    assert light_description_style != dark_description_style


def test_welcome_action_card_uses_disabled_opacity_when_disabled(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    card = WelcomeActionCard("bi--wallet2.svg")
    qtbot.addWidget(card)
    card.set_content("Hot Single Signature Wallet", "Disabled on Mainnet")

    try:
        card.setEnabled(True)
        qtbot.wait(10)
        effect = card.graphicsEffect()
        assert isinstance(effect, QGraphicsOpacityEffect)
        enabled_opacity = effect.opacity()

        card.setEnabled(False)
        qtbot.wait(10)
        disabled_opacity = effect.opacity()
    finally:
        app.setPalette(original_palette)
        card.changeEvent(QEvent(QEvent.Type.PaletteChange))

    assert enabled_opacity == 1.0
    assert disabled_opacity == WelcomeActionCard._disabled_opacity


def test_welcome_action_card_keeps_disabled_opacity_for_explicit_theme_palettes(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    card = WelcomeActionCard("bi--wallet2.svg")
    qtbot.addWidget(card)
    card.set_content("Hot Single Signature Wallet", "Disabled on Mainnet")
    card.setEnabled(False)

    try:
        app.setPalette(create_light_palette(original_palette))
        card.changeEvent(QEvent(QEvent.Type.ApplicationPaletteChange))
        effect = card.graphicsEffect()
        assert isinstance(effect, QGraphicsOpacityEffect)
        light_disabled_opacity = effect.opacity()

        app.setPalette(create_dark_palette(original_palette))
        card.changeEvent(QEvent(QEvent.Type.ApplicationPaletteChange))
        dark_disabled_opacity = effect.opacity()
    finally:
        app.setPalette(original_palette)
        card.changeEvent(QEvent(QEvent.Type.ApplicationPaletteChange))

    assert light_disabled_opacity == WelcomeActionCard._disabled_opacity
    assert dark_disabled_opacity == WelcomeActionCard._disabled_opacity


def test_network_choice_card_update_ui_refreshes_backgrounds(qtbot: QtBot) -> None:
    card = NetworkChoiceCard("bitcoin-bitcoin.svg")
    qtbot.addWidget(card)

    card.background_color = None
    card.cta_panel.background_color = None
    card.changeEvent(QEvent(QEvent.Type.PaletteChange))

    surface_colors = get_neutral_surface_colors()
    assert to_color_name(card.background_color) == to_color_name(surface_colors.content_background)
    assert to_color_name(card.cta_panel.background_color) == to_color_name(surface_colors.panel_background)


def test_new_wallet_welcome_screen_refreshes_cards_on_palette_change(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    screen = NewWalletWelcomeScreen(network=bdk.Network.TESTNET, signals=Signals())
    qtbot.addWidget(screen)

    def apply_palette(window: str, text: str) -> str:
        palette = QPalette(original_palette)
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.Base, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        palette.setColor(QPalette.ColorRole.Text, QColor(text))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(text))
        app.setPalette(palette)
        screen.hide()
        QApplication.sendEvent(screen, QEvent(QEvent.Type.ApplicationPaletteChange))
        screen.show()
        qtbot.waitExposed(screen)
        qtbot.wait(10)
        return screen.card_demo_wallet.styleSheet()

    try:
        light_stylesheet = apply_palette("#ffffff", "#111111")
        dark_stylesheet = apply_palette("#111111", "#f5f5f5")
    finally:
        app.setPalette(original_palette)
        screen.hide()
        QApplication.sendEvent(screen, QEvent(QEvent.Type.ApplicationPaletteChange))

    assert light_stylesheet != dark_stylesheet
    assert to_color_name(screen.card_demo_wallet.background_color) == to_color_name(
        get_neutral_surface_colors().panel_background
    )


def test_network_choice_welcome_screen_refreshes_cards_on_palette_change(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert app is not None
    original_palette = QPalette(app.palette())

    screen = NetworkChoiceWelcomeScreen(signals=Signals())
    qtbot.addWidget(screen)

    def apply_palette(window: str, text: str) -> str:
        palette = QPalette(original_palette)
        palette.setColor(QPalette.ColorRole.Window, QColor(window))
        palette.setColor(QPalette.ColorRole.Base, QColor(window))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
        palette.setColor(QPalette.ColorRole.Text, QColor(text))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(text))
        app.setPalette(palette)
        screen.hide()
        QApplication.sendEvent(screen, QEvent(QEvent.Type.ApplicationPaletteChange))
        screen.show()
        qtbot.waitExposed(screen)
        qtbot.wait(10)
        return screen.card_secure_wallet.styleSheet()

    try:
        light_stylesheet = apply_palette("#ffffff", "#111111")
        dark_stylesheet = apply_palette("#111111", "#f5f5f5")
    finally:
        app.setPalette(original_palette)
        screen.hide()
        QApplication.sendEvent(screen, QEvent(QEvent.Type.ApplicationPaletteChange))

    assert light_stylesheet != dark_stylesheet
    assert to_color_name(screen.card_secure_wallet.cta_panel.background_color) == to_color_name(
        get_neutral_surface_colors().panel_background
    )


def test_mainnet_hot_wallet_card_keeps_help_link_clickable(qtbot: QtBot, monkeypatch) -> None:
    screen = NewWalletWelcomeScreen(network=bdk.Network.BITCOIN, signals=Signals())
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)

    hot_wallet_clicked = Mock()
    message_mock = Mock()
    open_mock = Mock()
    screen.signal_onclick_hot_wallet.connect(hot_wallet_clicked)
    monkeypatch.setattr("bitcoin_safe.gui.qt.new_wallet_welcome_screen.Message", message_mock)
    monkeypatch.setattr("bitcoin_safe.gui.qt.icon_label.webopen", open_mock)

    assert screen.hot_wallet_help_label.isVisible()
    assert screen.hot_wallet_help_label.textLabel.text() == "No signer available?"
    assert screen.card_hot_wallet.graphicsEffect() is not None
    assert screen.card_hot_wallet.header_title.cursor().shape() == Qt.CursorShape.ArrowCursor

    qtbot.mouseClick(screen.card_hot_wallet.header_title, Qt.MouseButton.LeftButton)
    hot_wallet_clicked.assert_not_called()
    message_mock.assert_called_once()
    assert "Hot wallets are disabled on Bitcoin Mainnet." in message_mock.call_args.args[0]
    assert message_mock.call_args.kwargs["type"].name == "Warning"

    qtbot.mouseClick(screen.hot_wallet_help_label.textLabel, Qt.MouseButton.LeftButton)
    open_mock.assert_called_once_with(METROVAULT_SIGNER_URL)
