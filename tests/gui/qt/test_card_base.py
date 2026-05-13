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
from PyQt6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.card_base import CardBase, CardExpansionMode, CardList
from bitcoin_safe.gui.qt.new_wallet_welcome_screen import WelcomeActionCard
from bitcoin_safe.gui.qt.wizard.wizard_step_cards import TutorialTxCard, TutorialTxCardState


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


def test_card_list_current_expanded_card_absorbs_extra_height(qtbot: QtBot) -> None:
    card_list = CardList()
    cards = [_make_card(f"Card {index}", body_height=80) for index in range(2)]
    for card in cards:
        card_list.add_card(card)

    qtbot.addWidget(card_list)
    card_list.resize(600, 700)
    card_list.show()
    qtbot.waitExposed(card_list)
    qtbot.wait(10)

    card_list.set_current_index(1)
    qtbot.wait(10)

    assert cards[1].height() > cards[1].sizeHint().height()
    assert cards[1].height() > cards[0].height()


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
