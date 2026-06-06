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
from functools import partial

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.util import question_dialog
from PyQt6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.card_base import CardExpansionMode, CardList
from bitcoin_safe.gui.qt.qt_wallet import SyncStatus
from bitcoin_safe.gui.qt.step_progress_bar import TutorialWidget, VisibilityOption
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer, ViewerPresentation

from ..util import set_no_margins
from .wizard_step_cards import (
    TUTORIAL_TX_ICON_RECOGNIZED,
    TUTORIAL_TX_ICON_SEND,
    TutorialTxCard,
    TutorialTxCardState,
    completed_tx_subtitle,
    pending_tx_subtitle,
)
from .wizard_support import BaseTab, WizardTabInfo

logger = logging.getLogger(__name__)


class SendTest(BaseTab):
    def __init__(
        self,
        test_number: int,
        refs: WizardTabInfo,
        loop_in_thread: LoopInThread,
        show_previous_step_button: bool,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            refs, loop_in_thread=loop_in_thread, show_previous_step_button=show_previous_step_button
        )
        self.test_number = test_number
        self.embedded_viewer: UITx_Viewer | None = None
        self.viewer_container: QWidget | None = None
        self.viewer_layout: QVBoxLayout | None = None
        self.history_cards: dict[int, TutorialTxCard] = {}
        self._history_card_order: list[int] = []

    def set_visibilities(self, should_be_visible: bool) -> None:
        """Set visibilities."""
        if not self.refs.qt_wallet:
            return

        wizard = self.wizard_parent()
        has_pending_tx = bool(wizard and self.test_number in wizard.pending_txid_by_send_test)
        if should_be_visible:
            if wizard:
                wizard._configure_creator_for_embedded_send_test(True)
            if wizard and wizard.get_send_test_txid(self.test_number) in wizard.recognized_txids:
                self.close_embedded_viewer(refresh=False)
                self.refresh_cards()
                return
            if self.embedded_viewer or has_pending_tx:
                self.refresh_cards()
                return
            uitx = self.refs.qt_wallet.uitx_creator
            uitx.setParent(None)
            self.active_card.set_content_widget(uitx)
            uitx.setHidden(False)
            self.refresh_cards()
            return

        self.buttonbox.setVisible(False)
        if self.active_card.content_layout.indexOf(self.refs.qt_wallet.uitx_creator) == -1:
            return
        if wizard:
            wizard._configure_creator_for_embedded_send_test(False)
        self.active_card.clear_content_widget(self.refs.qt_wallet.uitx_creator)
        self.refs.qt_wallet.send_node.setWidget(self.refs.qt_wallet.uitx_creator)
        self.refs.qt_wallet.uitx_creator.clear_ui()

    def _callback(self) -> None:
        """Callback."""
        if not self.refs.qt_wallet:
            return

        self.set_visibilities(True)
        if self.refs.qt_wallet.wallet.client and self.refs.qt_wallet.wallet.client.sync_status in [
            SyncStatus.unknown,
            SyncStatus.unsynced,
        ]:
            logger.debug(
                f"Skipping tutorial callback for send test, "
                f"because {self.refs.qt_wallet.wallet.id} sync_status={self.refs.qt_wallet.wallet.client.sync_status}"
            )
            return

        if wizard := self.wizard_parent():
            if wizard.get_send_test_txid(self.test_number):
                wizard.on_send_test_step_activated(self.test_number)
                return

        txos = self.refs.qt_wallet.wallet.get_all_txos_dict(include_not_mine=False).values()
        spend_txos = [txo for txo in txos if txo.is_spent_by_txid]
        if spend_txos and len(spend_txos) >= self.test_number + 1:
            if question_dialog(
                text=self.tr(
                    "You made {n} outgoing transactions already. Would you like to skip this spend test?"
                ).format(n=len(spend_txos)),
                title=self.tr("Skip spend test?"),
                true_button=QMessageBox.StandardButton.Yes,
                false_button=QMessageBox.StandardButton.No,
            ):
                self.refs.go_to_next_index()
                return

        if wizard := self.wizard_parent():
            wizard.on_send_test_step_activated(self.test_number)
            return

        if wizard := self.wizard_parent():
            wizard.fill_tx()

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        self.widget_layout = QVBoxLayout(widget)
        set_no_margins(self.widget_layout)
        self.widget_layout.setSpacing(12)

        self.card_list = CardList(widget)
        self.card_list.content_layout.setSpacing(10)
        self.widget_layout.addWidget(self.card_list)

        self.active_card = TutorialTxCard(widget)
        self.active_card.set_expansion_mode(CardExpansionMode.FIXED_EXPANDED)
        self.active_card.set_clickable_header(False)
        self.active_card.signal_header_activated.connect(partial(self._open_active_tx, self.test_number))
        self.card_list.add_card(self.active_card)

        self.viewer_container = QWidget(self.active_card.content_widget)
        self.viewer_layout = QVBoxLayout(self.viewer_container)
        set_no_margins(self.viewer_layout)
        self.viewer_container.setHidden(True)
        self.active_card.content_layout.addWidget(self.viewer_container, stretch=1)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )
        tutorial_widget.set_callback(self._callback)
        tutorial_widget.synchronize_visiblity(
            VisibilityOption(tutorial_widget.button_box, on_focus_set_visible=False)
        )

        if self.refs.qt_wallet:
            tutorial_widget.synchronize_visiblity(
                VisibilityOption(self.refs.qt_wallet.uitx_creator.button_box, on_focus_set_visible=False)
            )

        self.updateUi()
        return tutorial_widget

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.refresh_cards()

    def set_status_text(self, text: str | None) -> None:
        """Set the transient status text shown below the send-test description."""
        self.refresh_cards(status_text=text)

    def _card_title(self, test_number: int) -> str:
        return self.tr("Self-Send Test {number}").format(number=test_number + 1)

    def _status_icon_name(self, txid: str | None) -> str:
        wizard = self.wizard_parent()
        if not wizard or not txid:
            return TUTORIAL_TX_ICON_SEND
        if not self.refs.qt_wallet or txid not in wizard.recognized_txids:
            return TUTORIAL_TX_ICON_SEND
        return TUTORIAL_TX_ICON_RECOGNIZED

    def _open_active_tx(self, test_number: int) -> None:
        """Open the current send-test transaction when its header is clicked."""
        if wizard := self.wizard_parent():
            wizard.open_send_test_tx(test_number)

    def refresh_cards(self, status_text: str | None = None) -> None:
        """Refresh the card list for the current send-test step."""
        wizard = self.wizard_parent()
        if not wizard:
            return

        active_txid = wizard.get_send_test_txid(self.test_number)
        default_subtitle = status_text or self.tr("Create the transaction in this card.")
        if active_txid:
            if active_txid in wizard.recognized_txids:
                default_subtitle = completed_tx_subtitle(self, active_txid)
            elif self.embedded_viewer:
                default_subtitle = self.tr("Sign and broadcast the transaction below.")
            else:
                default_subtitle = self.tr("Waiting for the transaction to be prepared.")

        is_completed = bool(active_txid and active_txid in wizard.recognized_txids)
        if is_completed:
            self.close_embedded_viewer(refresh=False)
        self.active_card.apply_state(
            TutorialTxCardState(
                title=self._card_title(self.test_number),
                subtitle=default_subtitle,
                icon_name=self._status_icon_name(active_txid),
                expansion_mode=(
                    CardExpansionMode.FIXED_COLLAPSED if is_completed else CardExpansionMode.FIXED_EXPANDED
                ),
                clickable=is_completed,
                expanded=not is_completed,
            )
        )
        self.button_next.setEnabled(is_completed)
        self.buttonbox.setVisible(is_completed)

        visible_previous_numbers = [
            previous_number
            for previous_number in range(self.test_number)
            if wizard.get_send_test_txid(previous_number)
        ]
        for previous_number in list(self._history_card_order):
            if previous_number in visible_previous_numbers:
                continue
            card = self.history_cards.pop(previous_number)
            self.card_list.remove_card(card)
            card.hide()
            card.setParent(None)
            self._history_card_order.remove(previous_number)

        for previous_number in visible_previous_numbers:
            txid = wizard.get_send_test_txid(previous_number)
            if not txid:
                continue
            history_card = self.history_cards.get(previous_number)
            if history_card is None:
                history_card = TutorialTxCard(self.card_list.scroll_area.content_widget)
                history_card.set_expansion_mode(CardExpansionMode.FIXED_COLLAPSED)
                history_card.set_clickable_header(True)
                history_card.signal_header_activated.connect(
                    partial(wizard.open_send_test_tx, previous_number)
                )
                self.history_cards[previous_number] = history_card
                self._history_card_order.append(previous_number)
                self.card_list.insert_card(self.card_list.count() - 1, history_card)

            subtitle = (
                completed_tx_subtitle(self, txid)
                if txid in wizard.recognized_txids
                else pending_tx_subtitle(self, txid)
            )
            history_card.apply_state(
                TutorialTxCardState(
                    title=self._card_title(previous_number),
                    subtitle=subtitle,
                    icon_name=self._status_icon_name(txid),
                    expansion_mode=CardExpansionMode.FIXED_COLLAPSED,
                    clickable=True,
                    expanded=False,
                )
            )

    def show_embedded_viewer(self, viewer: UITx_Viewer) -> None:
        """Show the embedded viewer for this send test."""
        self.close_embedded_viewer()
        if self.viewer_container is None or self.viewer_layout is None:
            return
        self.embedded_viewer = viewer
        viewer.set_presentation(ViewerPresentation.embedded_card)
        self.viewer_layout.addWidget(viewer)
        self.viewer_container.show()
        viewer.show()
        self.active_card.set_content_widget(self.viewer_container)
        self.refresh_cards()

    def close_embedded_viewer(self, refresh: bool = True) -> None:
        """Close and detach the embedded viewer, if present."""
        if self.viewer_container is None or self.viewer_layout is None:
            self.embedded_viewer = None
            return
        if not self.embedded_viewer:
            self.viewer_container.setHidden(True)
            return
        embedded_viewer = self.embedded_viewer
        self.embedded_viewer = None
        self.viewer_layout.removeWidget(embedded_viewer)
        embedded_viewer.close()
        self.viewer_container.setHidden(True)
        if refresh:
            self.refresh_cards()

    def close(self) -> None:
        """Close."""
        self.close_embedded_viewer(refresh=False)
        self.viewer_layout = None
        self.viewer_container = None
        super().close()
