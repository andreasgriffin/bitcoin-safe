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

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.bitcoin_quick_receive import BitcoinQuickReceive
from bitcoin_safe.gui.qt.card_base import CardExpansionMode, CardList
from bitcoin_safe.gui.qt.qt_wallet import SyncStatus
from bitcoin_safe.gui.qt.step_progress_bar import TutorialWidget
from bitcoin_safe.gui.qt.testnet_faucet import open_testnet_faucet
from bitcoin_safe.html_utils import html_f
from bitcoin_safe.network_config import get_testnet_faucet
from bitcoin_safe.pythonbdk_types import PythonUtxo
from bitcoin_safe.signals import UpdateFilter

from ..cbf_progress_bar import CBFProgressBar
from ..util import (
    Message,
    MessageType,
    add_centered_icons,
    one_time_signal_connection,
    set_no_margins,
    svg_tools,
)
from .wizard_step_cards import (
    TUTORIAL_TX_ICON_RECOGNIZED,
    TUTORIAL_TX_ICON_WAITING,
    TutorialTxCard,
    TutorialTxCardState,
    completed_tx_subtitle,
)
from .wizard_support import BaseTab, WizardTabInfo


class ReceiveTest(BaseTab):
    def __init__(
        self, refs: WizardTabInfo, loop_in_thread: LoopInThread, show_previous_step_button: bool
    ) -> None:
        """Initialize instance."""
        super().__init__(
            refs=refs, loop_in_thread=loop_in_thread, show_previous_step_button=show_previous_step_button
        )
        self.next_button = self.button_next
        self.quick_receive: BitcoinQuickReceive | None = None
        self.cbf_progress_bar: CBFProgressBar | None = None
        self.instructions_section: QGroupBox | None = None
        self.tx_section: QGroupBox | None = None
        self.tx_card_list: CardList | None = None
        self.tx_card: TutorialTxCard | None = None
        self.check_button: SpinningButton | None = None
        self.label_receive_intro: QLabel | None = None
        self.label_receive_why: QLabel | None = None
        self.faucet_button: QPushButton | None = None

    def get_faucet_network(self) -> bdk.Network:
        """Return the network used for receive-step faucet actions."""
        return self.refs.qtwalletbase.config.network

    def has_faucet(self) -> bool:
        """Return whether the current network provides a faucet."""
        return bool(get_testnet_faucet(network=self.get_faucet_network()))

    def open_faucet(self) -> None:
        """Open the faucet for the current test network."""
        open_testnet_faucet(self.get_faucet_network())

    def _on_sync_done(self, sync_status: SyncStatus) -> None:
        """On sync done."""
        del sync_status
        self.check_wallet_for_utxos()

    def get_received_txid(self) -> str | None:
        """Return the first recognized funding transaction for the receive test."""
        if not self.refs.qt_wallet:
            return None
        utxos = self.refs.qt_wallet.wallet.get_all_utxos(include_not_mine=False)
        if not utxos:
            return None
        return utxos[0].outpoint.txid_str

    def refresh_tx_card(self) -> bool:
        """Refresh the lightweight receive-test transaction card from wallet state."""
        if not self.tx_card or not self.check_button:
            return False

        txid = self.get_received_txid()
        if not txid:
            self.tx_card.apply_state(
                TutorialTxCardState(
                    title=self.tr("Receive Test"),
                    subtitle=self.tr("Waiting for funds to arrive in the wallet..."),
                    icon_name=TUTORIAL_TX_ICON_WAITING,
                    expansion_mode=CardExpansionMode.FIXED_COLLAPSED,
                    clickable=False,
                    expanded=False,
                    hidden=False,
                )
            )
            self.check_button.setVisible(True)
            return False

        self.tx_card.apply_state(
            TutorialTxCardState(
                title=self.tr("Receive Test"),
                subtitle=completed_tx_subtitle(self, txid),
                icon_name=TUTORIAL_TX_ICON_RECOGNIZED,
                expansion_mode=CardExpansionMode.FIXED_COLLAPSED,
                clickable=True,
                expanded=False,
            )
        )
        self.check_button.setVisible(False)
        return True

    def open_received_tx(self) -> None:
        """Open the recognized receive-test transaction in a regular tx viewer tab."""
        if not self.refs.qt_wallet:
            return
        txid = self.get_received_txid()
        if not txid:
            return
        if txdetails := self.refs.qt_wallet.wallet.get_tx(txid):
            self.refs.qtwalletbase.signals.open_tx_like.emit(txdetails)
            return
        self.refs.qtwalletbase.signals.open_tx_like.emit(txid)

    def check_wallet_for_utxos(self) -> list[PythonUtxo]:
        """Check wallet for utxos."""
        if not self.refs.qt_wallet:
            return []
        if not self.check_button:
            return []
        utxos = self.refs.qt_wallet.wallet.get_all_utxos(include_not_mine=False)
        self.check_button.setHidden(bool(utxos))
        self.next_button.setEnabled(bool(utxos))
        self.refresh_tx_card()
        return utxos

    def _start_sync(self) -> None:
        """Start sync."""
        if not self.refs.qt_wallet:
            Message(self.tr("No wallet setup yet"), type=MessageType.Error, parent=self.refs.container)
            return
        if not self.check_button:
            return

        if self.check_wallet_for_utxos():
            return

        self.check_button.set_enable_signal(self.refs.qtwalletbase.signal_after_sync)
        one_time_signal_connection(self.refs.qtwalletbase.signal_after_sync, self._on_sync_done)
        self.refs.qt_wallet.sync()

    def create(self) -> TutorialWidget:
        """Create."""
        widget = QWidget()
        widget_layout = QVBoxLayout(widget)
        widget_layout.setContentsMargins(10, 0, 0, 0)
        widget_layout.setSpacing(16)

        self.instructions_section = QGroupBox(widget)
        self.instructions_section.setMaximumHeight(350)
        self.instructions_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        instructions_layout = QHBoxLayout(self.instructions_section)
        instructions_layout.setSpacing(20)
        widget_layout.addWidget(self.instructions_section, stretch=1)

        left_widget_layout = QVBoxLayout()
        set_no_margins(left_widget_layout)
        instructions_layout.addLayout(left_widget_layout)

        if self.refs.qt_wallet:
            self.quick_receive = BitcoinQuickReceive(
                wallet_signals=self.refs.qt_wallet.wallet_signals,
                wallet=self.refs.qt_wallet.wallet,
                parent=widget,
                signals_min=self.refs.qt_wallet.signals,
            )
            self.quick_receive.set_manage_categories_visible(False)
            self.quick_receive.signal_manage_categories_requested.connect(
                self.refs.qt_wallet.category_manager.show
            )
            self.quick_receive.signal_add_category_requested.connect(
                self.refs.qt_wallet.category_manager.add_category
            )
            self.quick_receive.setMaximumWidth(250)
            self.quick_receive.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
            left_widget_layout.addWidget(self.quick_receive)

            self.cbf_progress_bar = CBFProgressBar(config=self.refs.qt_wallet.config, parent=widget)
            left_widget_layout.addWidget(self.cbf_progress_bar)
            self.signal_tracker.connect(
                self.refs.qt_wallet.signal_progress_info, self.cbf_progress_bar._set_progress_info
            )
        else:
            add_centered_icons(["ic--baseline-call-received.svg"], instructions_layout, max_sizes=[(50, 80)])
            if (_layout_item := instructions_layout.itemAt(0)) and (_widget := _layout_item.widget()):
                _widget.setMaximumWidth(150)

        right_widget = QWidget(self.instructions_section)
        right_widget_layout = QVBoxLayout(right_widget)
        set_no_margins(right_widget_layout)
        instructions_layout.addWidget(right_widget, stretch=1)

        self.label_receive_intro = QLabel(widget)
        self.label_receive_intro.setWordWrap(True)
        self.faucet_button = QPushButton(widget)
        self.faucet_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.faucet_button.clicked.connect(self.open_faucet)
        self.faucet_button.setHidden(not self.has_faucet())
        self.label_receive_why = QLabel(widget)
        self.label_receive_why.setWordWrap(True)

        right_widget_layout.addStretch(1)
        right_widget_layout.addWidget(self.label_receive_intro)
        right_widget_layout.addWidget(self.faucet_button, alignment=Qt.AlignmentFlag.AlignLeft)
        right_widget_layout.addWidget(self.label_receive_why)
        right_widget_layout.addStretch(1)

        self.tx_section = QGroupBox(widget)
        self.tx_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        tx_section_layout = QVBoxLayout(self.tx_section)
        tx_section_layout.setSpacing(10)
        widget_layout.addWidget(self.tx_section)
        widget_layout.addStretch()

        self.tx_card_list = CardList(self.tx_section)
        self.tx_card_list.content_layout.setSpacing(10)
        tx_section_layout.addWidget(self.tx_card_list)

        self.tx_card = TutorialTxCard(self.tx_card_list.scroll_area.content_widget)
        self.tx_card.signal_header_activated.connect(self.open_received_tx)
        self.tx_card_list.add_card(self.tx_card)

        self.check_button = SpinningButton("", timeout=20, svg_tools=svg_tools)
        self.check_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tx_card.header_right_layout.addWidget(self.check_button)

        self.next_button.setEnabled(False)
        self.check_button.clicked.connect(self._start_sync)

        tutorial_widget = TutorialWidget(
            self.refs.container, widget, self.buttonbox, buttonbox_always_visible=False
        )

        self.updateUi()
        self.refresh_tx_card()
        if self.quick_receive:
            self.quick_receive.update_content(UpdateFilter(refresh_all=True))
        return tutorial_widget

    def updateUi(self) -> None:
        """UpdateUi."""
        if self.is_closed:
            return
        super().updateUi()
        test_amount = Satoshis(self.refs.max_test_fund, self.refs.qtwalletbase.config.network).str_with_unit(
            btc_symbol=self.refs.qtwalletbase.config.bitcoin_symbol.value
        )
        if self.label_receive_intro:
            self.label_receive_intro.setText(
                html_f(
                    self.tr(
                        """Receive a <b>small</b> amount (less than {test_amount}) to 1 address of this wallet.<br>"""
                    ).format(test_amount=test_amount),
                    add_html_and_body=True,
                    p=True,
                    size=12,
                )
            )
        if self.label_receive_why:
            self.label_receive_why.setText(
                html_f(
                    self.tr(
                        """<br><b>Why?</b> <br>
                        To know if you control the funds, you have to test spending from the wallet.
                        <br>
                        So before you send a substantial amount of Bitcoin into the wallet, it is <b>crucial</b> to spend from the wallet and test all signers.
                        """  # noqa: E501
                    ),
                    add_html_and_body=True,
                    p=True,
                    size=12,
                )
            )
        if self.faucet_button:
            self.faucet_button.setText(self.tr("Receive from faucet"))
            self.faucet_button.setHidden(not self.has_faucet())
        if self.instructions_section:
            self.instructions_section.setTitle(self.tr("Receive instructions"))
        if self.tx_section:
            self.tx_section.setTitle(self.tr("Recognized Transaction"))
        if self.check_button:
            self.check_button.setText(self.tr("Check if received"))
        if self.quick_receive:
            self.quick_receive.updateUi()

    def set_visibilities(self, should_be_visible: bool) -> None:
        """Refresh receive content once the step is actually visible."""
        if should_be_visible and self.quick_receive:
            self.quick_receive.update_content(UpdateFilter(refresh_all=True))
            self.check_wallet_for_utxos()
