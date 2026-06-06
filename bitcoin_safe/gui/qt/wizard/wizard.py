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
import logging
import uuid
from math import ceil
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialogButtonBox, QPushButton

from bitcoin_safe.gui.qt.qt_wallet import QTWallet, QtWalletBase
from bitcoin_safe.gui.qt.send_test_schedule import (
    SendTestStepPlan,
    build_send_test_fingerprint_groups,
    build_send_test_signer_groups,
)
from bitcoin_safe.gui.qt.wizard.wizard_base import WizardBase
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason

from ....pythonbdk_types import Recipient
from ....tx import PostBroadcastEnum, PostCreateEnum, TxBuilderInfos, TxUiInfos
from ..step_progress_bar import TutorialWidget
from ..util import Message, MessageType
from .wizard_step_distribution import DistributeSeeds, RegisterMultisig
from .wizard_step_import import ImportXpubs
from .wizard_step_plugins import PluginListStep
from .wizard_step_receive import ReceiveTest
from .wizard_step_send import SendTest
from .wizard_step_setup import WalletSetupOptions
from .wizard_support import BaseTab, WizardTabInfo

logger = logging.getLogger(__name__)


class TutorialStep(enum.Enum):
    wallet_setup = enum.auto()
    import_xpub = enum.auto()
    register = enum.auto()
    plugins = enum.auto()
    receive = enum.auto()
    send = enum.auto()
    send2 = enum.auto()
    send3 = enum.auto()
    send4 = enum.auto()
    send5 = enum.auto()
    send6 = enum.auto()
    send7 = enum.auto()
    send8 = enum.auto()
    send9 = enum.auto()
    send10 = enum.auto()
    distribute = enum.auto()

    @classmethod
    def ordered_steps(cls) -> tuple[TutorialStep, ...]:
        """Return the tutorial steps in display order."""
        return tuple(cls)

    @classmethod
    def send_test_steps(cls) -> tuple[TutorialStep, ...]:
        """Return the ordered send-test tutorial steps."""
        ordered_steps = cls.ordered_steps()
        start_index = ordered_steps.index(cls.send)
        end_index = ordered_steps.index(cls.send10) + 1
        return ordered_steps[start_index:end_index]


class Wizard(WizardBase):
    signal_create_wallet = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_step_change = cast(SignalProtocol[[int]], pyqtSignal(int))

    def __init__(
        self,
        qtwalletbase: QtWalletBase,
        max_test_fund: int = 1_000_000,
        qt_wallet: QTWallet | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            step_labels=[""] * 3,
            signals_min=qtwalletbase.signals,
            loop_in_thread=qt_wallet.loop_in_thread if qt_wallet else qtwalletbase.loop_in_thread,
            clickable=False,
        )
        logger.debug(f"__init__ {self.__class__.__name__}")
        self.qtwalletbase = qtwalletbase
        self.qt_wallet = qt_wallet
        self.send_test_signal_tracker = SignalTracker()
        self._send_test_signals_connected = False
        self._is_closing = False
        self.active_request_id: str | None = None
        self.active_send_test_index: int | None = None
        self.pending_txid_by_send_test: dict[int, str] = {}
        self.recognized_txids: set[str] = set()

        self.qtwalletbase.tabs.addChildNode(self.node)
        self.node.setHidable(bool(self.qt_wallet))

        _m, n = self.qtwalletbase.get_mn_tuple()

        self.send_test_previous_button = QPushButton(self)
        self.send_test_previous_button.clicked.connect(self.go_to_previous_index)
        self.send_test_previous_button.setVisible(False)

        refs = WizardTabInfo(
            container=self.step_container,
            qtwalletbase=qtwalletbase,
            go_to_next_index=self.go_to_next_index,
            go_to_previous_index=self.go_to_previous_index,
            signal_create_wallet=self.signal_create_wallet,
            qt_wallet=self.qt_wallet,
            max_test_fund=max_test_fund,
        )

        self.tab_generators: dict[TutorialStep, BaseTab] = {}
        if self.qt_wallet:
            if n > 1:
                self.tab_generators[TutorialStep.register] = RegisterMultisig(
                    refs=refs, loop_in_thread=self.loop_in_thread, show_previous_step_button=True
                )
            self.tab_generators[TutorialStep.receive] = ReceiveTest(
                refs=refs, loop_in_thread=self.loop_in_thread, show_previous_step_button=True
            )
            for test_number, tutorial_step in enumerate(self.get_send_tests_steps()):
                self.tab_generators[tutorial_step] = SendTest(
                    test_number=test_number,
                    refs=refs,
                    loop_in_thread=self.loop_in_thread,
                    show_previous_step_button=True,
                )
            self.tab_generators[TutorialStep.distribute] = DistributeSeeds(
                refs=refs, loop_in_thread=self.loop_in_thread, show_previous_step_button=True
            )
            self.tab_generators[TutorialStep.plugins] = PluginListStep(
                refs=refs,
                loop_in_thread=self.loop_in_thread,
                show_previous_step_button=(
                    self.get_previous_displayed_step(TutorialStep.plugins) == TutorialStep.register
                ),
            )
        else:
            self.tab_generators[TutorialStep.wallet_setup] = WalletSetupOptions(
                refs=refs, loop_in_thread=self.loop_in_thread, show_previous_step_button=False
            )
            self.tab_generators[TutorialStep.import_xpub] = ImportXpubs(
                refs=refs, loop_in_thread=self.loop_in_thread, show_previous_step_button=True
            )

        self.updateUi()

        self.widgets: dict[TutorialStep, TutorialWidget] = {
            step: generator.create() for step, generator in self.tab_generators.items()
        }
        for step, widget in self.widgets.items():
            self.step_container.set_custom_widget(self.index_of_step(step), widget)

        if self.qtwalletbase.tutorial_index is not None:
            self.set_current_index(self.qtwalletbase.tutorial_index)

        self.step_container.signal_set_current_widget.connect(self._save)
        self.signal_step_change.connect(self.qtwalletbase.set_tutorial_index)
        self.node.hideClicked.connect(self.on_hide_clicked)

        self.updateUi()
        self.set_visibilities()

        self.signal_tracker.connect(self.qtwalletbase.signals.language_switch, self.updateUi)
        if self.qt_wallet:
            if self.qt_wallet.plugin_manager:
                for client in self.qt_wallet.plugin_manager.clients:
                    self.signal_tracker.connect(
                        client.signal_enabled_changed, self._on_plugin_enabled_changed
                    )
            self.signal_tracker.connect(
                self.qtwalletbase.wallet_functions.wallet_signals[self.qt_wallet.wallet.id].updated,
                self.on_utxo_update,
            )

    def on_hide_clicked(self, obj: object) -> None:
        """On hide clicked."""
        del obj
        self.toggle_tutorial()

    def _on_plugin_enabled_changed(self, enabled: bool) -> None:
        """Refresh sidebar visibility when a plugin toggles while the tutorial is open."""
        del enabled
        if self.should_be_visible:
            self.set_visibilities()

    def _save(self, widget: object) -> None:
        """Save."""
        del widget
        if self.qt_wallet:
            self.qt_wallet.save()

    def show_warning_not_initialized(self) -> None:
        """Show warning not initialized."""
        Message(self.tr("You must have an initilized wallet first"), type=MessageType.Warning, parent=self)

    def _connect_send_test_signals(self) -> None:
        """Connect temporary send-test signal routing while the wizard is visible."""
        if not self.qt_wallet or self._send_test_signals_connected:
            return
        self.send_test_signal_tracker.connect(self.qt_wallet.signal_psbt_created, self.on_signal_psbt_created)
        self._send_test_signals_connected = True

    def _disconnect_send_test_signals(self) -> None:
        """Disconnect temporary send-test signal routing."""
        self.send_test_signal_tracker.disconnect_all()
        self._send_test_signals_connected = False

    def _reset_send_test_runtime_state(self) -> None:
        """Forget transient send-test routing state."""
        self.active_request_id = None
        self.active_send_test_index = None
        self.pending_txid_by_send_test.clear()
        self.recognized_txids.clear()

    def _clear_active_send_test_request(self) -> None:
        """Drop any in-flight send-test PSBT request."""
        self.active_request_id = None
        self.active_send_test_index = None

    def _send_test_step(self, test_number: int) -> SendTest | None:
        """Return the send-test step for the given index."""
        send_steps = self.get_send_tests_steps()
        if test_number < 0 or test_number >= len(send_steps):
            return None
        step = self.tab_generators.get(send_steps[test_number])
        return step if isinstance(step, SendTest) else None

    def _receive_step(self) -> ReceiveTest | None:
        """Return the receive-test step if present."""
        step = self.tab_generators.get(TutorialStep.receive)
        return step if isinstance(step, ReceiveTest) else None

    def _detach_creator_from_send_test(self, step: SendTest) -> None:
        """Move the shared tx creator back to the wallet send node."""
        if not self.qt_wallet:
            return
        uitx_creator = self.qt_wallet.uitx_creator
        if step.active_card.content_layout.indexOf(uitx_creator) == -1:
            return
        step.active_card.clear_content_widget(uitx_creator)
        self.qt_wallet.send_node.setWidget(uitx_creator)

    def _update_send_test_step_status(self, test_number: int, text: str | None) -> None:
        """Set the visible status text for a send-test step."""
        if step := self._send_test_step(test_number):
            step.set_status_text(text)

    def _refresh_all_send_test_cards(self) -> None:
        """Refresh every send-test card to reflect the latest tx state."""
        for send_step in self.get_send_tests_steps():
            step = self.tab_generators.get(send_step)
            if isinstance(step, SendTest):
                step.refresh_cards()

    def _configure_creator_for_embedded_send_test(self, embedded: bool) -> None:
        """Adjust tx creator chrome for the wizard's embedded send-test card."""
        if not self.qt_wallet:
            return
        creator = self.qt_wallet.uitx_creator

        creator.set_fee_notification_bars_enabled(not embedded)
        creator.button_box.setVisible(True)
        creator.button_back.setVisible(not embedded)
        creator.set_show_reset_button(not embedded)
        if embedded:
            if self.send_test_previous_button not in creator.button_box.buttons():
                creator.button_box.addButton(
                    self.send_test_previous_button, QDialogButtonBox.ButtonRole.ResetRole
                )
            self.send_test_previous_button.setVisible(True)
            return

        creator.button_box.removeButton(self.send_test_previous_button)
        self.send_test_previous_button.setVisible(False)

    def open_send_test_tx(self, test_number: int) -> None:
        """Open a tutorial send-test transaction in a regular tx viewer tab."""
        if not self.qt_wallet:
            return
        txid = self.get_send_test_txid(test_number)
        if not txid:
            return
        if txdetails := self.qt_wallet.wallet.get_tx(txid):
            self.qtwalletbase.signals.open_tx_like.emit(txdetails)
            return
        self.qtwalletbase.signals.open_tx_like.emit(txid)

    def get_send_test_txid(self, test_number: int) -> str | None:
        """Return the tracked txid for a send test, restoring it from wallet state when needed."""
        if txid := self.pending_txid_by_send_test.get(test_number):
            return txid
        if not self.qt_wallet:
            return None

        restored_txid: str | None = None
        for txo in self.qt_wallet.wallet.get_all_txos_dict().values():
            if self.qt_wallet.wallet.labels.get_label(txo.address) == self.tx_text(test_number):
                restored_txid = txo.outpoint.txid_str

        if not restored_txid:
            return None

        self.pending_txid_by_send_test[test_number] = restored_txid
        if self.qt_wallet.wallet.get_tx(restored_txid):
            self.recognized_txids.add(restored_txid)
        return restored_txid

    def on_send_test_step_activated(self, test_number: int) -> None:
        """Initialize or restore the active send-test step when it gains focus."""
        self._refresh_all_send_test_cards()
        if pending_txid := self.get_send_test_txid(test_number):
            if pending_txid in self.recognized_txids:
                if step := self._send_test_step(test_number):
                    step.close_embedded_viewer(refresh=False)
                self._update_send_test_step_status(
                    test_number, self.tr("Transaction recognized by the wallet.")
                )
            else:
                self._update_send_test_step_status(
                    test_number, self.tr("Waiting for the wallet to recognize the broadcast transaction.")
                )
            return

        self.fill_tx_for_test(test_number)

    def fill_tx_for_test(self, test_number: int) -> None:
        """Prepare the shared tx creator for the given send-test index."""
        self.active_request_id = uuid.uuid4().hex
        self.active_send_test_index = test_number
        self._configure_creator_for_embedded_send_test(True)
        self.open_tx(test_number)
        self._update_send_test_step_status(
            test_number, self.tr("Review the transaction and create it when you are ready.")
        )
        self._refresh_all_send_test_cards()

    def on_signal_psbt_created(self, builder_infos: TxBuilderInfos) -> None:
        """Handle PSBT creation for the currently active send-test flow."""
        if self._is_closing or not self.qt_wallet or not self.should_be_visible:
            return
        hidden = builder_infos.hidden_tx_infos
        if hidden is None or hidden.post_create_action != PostCreateEnum.no_action:
            return
        if hidden.wizard_request_id != self.active_request_id:
            return
        if hidden.wizard_send_test_index != self.active_send_test_index:
            return
        test_number = hidden.wizard_send_test_index
        if test_number is None:
            return

        txid = str(builder_infos.psbt.extract_tx().compute_txid())
        self._clear_active_send_test_request()

        if txid in self.recognized_txids:
            return

        self.pending_txid_by_send_test[test_number] = txid
        step = self._send_test_step(test_number)
        if not step:
            return

        self._detach_creator_from_send_test(step)
        viewer = self.qt_wallet.create_viewer_from_builder_infos(builder_infos, parent=step.viewer_container)
        viewer.post_broadcast_action = PostBroadcastEnum.no_action
        step.show_embedded_viewer(viewer)
        self._update_send_test_step_status(
            test_number,
            self.tr("Transaction created. Sign and broadcast it below, then wait for wallet recognition."),
        )
        self._refresh_all_send_test_cards()

    def toggle_tutorial(self) -> None:
        """Toggle tutorial."""
        if self.get_wallet_tutorial_index() is None:
            self.qtwalletbase.tutorial_index = self.index_of_step(self.guess_current_step())
            self.set_current_index(self.qtwalletbase.tutorial_index)
        else:
            self.qtwalletbase.tutorial_index = None

        self.set_visibilities()
        if self.should_be_visible:
            self.node.select()

    def guess_current_step(self) -> TutorialStep:
        """Guess current step."""
        step = TutorialStep.wallet_setup
        if self.qt_wallet:
            step = TutorialStep.receive

            if self.qt_wallet.wallet.get_balance().total > 0:
                step = TutorialStep.send

        return step

    def on_utxo_update(self, update_filter: UpdateFilter) -> None:
        """On utxo update."""
        if not self.qt_wallet or not self.should_be_visible:
            return

        should_update = bool(
            update_filter.refresh_all
            or update_filter.outpoints
            or update_filter.txids
            or update_filter.reason
            in {
                UpdateFilterReason.TransactionChange,
                UpdateFilterReason.ChainHeightAdvanced,
                UpdateFilterReason.ForceRefresh,
                UpdateFilterReason.WalletOpened,
            }
        )
        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter")

        if receive_step := self._receive_step():
            if self.current_step() == TutorialStep.receive:
                receive_step.check_wallet_for_utxos()

        send_test_steps = self.get_send_tests_steps()
        for test_number, send_step in enumerate(send_test_steps):
            txid = self.get_send_test_txid(test_number)
            if not txid or not self.qt_wallet.wallet.get_tx(txid):
                continue
            self.recognized_txids.add(txid)
            if self.current_step() == send_step:
                if step := self._send_test_step(test_number):
                    step.close_embedded_viewer(refresh=False)
                self._update_send_test_step_status(
                    test_number, self.tr("Transaction recognized by the wallet.")
                )

        self._refresh_all_send_test_cards()

    def current_step(self) -> TutorialStep:
        """Current step."""
        return self.get_step_of_index(self.step_container.current_index())

    def get_available_steps(self) -> list[TutorialStep]:
        """Return the steps that currently have backing widgets."""
        return list(self.tab_generators.keys())

    def index_of_step(self, step: TutorialStep) -> int:
        """Index of step."""
        return self.get_displayed_steps().index(step)

    def get_step_of_index(self, index: int) -> TutorialStep:
        """Get step of index."""
        members = self.get_displayed_steps()
        if index < 0:
            index = 0
        if index >= len(members):
            index = len(members) - 1
        return members[index]

    def get_previous_displayed_step(self, step: TutorialStep) -> TutorialStep | None:
        """Return the displayed step that comes immediately before the given step."""
        members = self.get_displayed_steps()
        index = members.index(step)
        if index == 0:
            return None
        return members[index - 1]

    def get_wallet_tutorial_index(self) -> int | None:
        """Get wallet tutorial index."""
        return self.qt_wallet.tutorial_index if self.qt_wallet else self.qtwalletbase.tutorial_index

    def set_wallet_tutorial_index(self, value: int | None) -> None:
        """Set wallet tutorial index."""
        if self.qt_wallet:
            self.qt_wallet.tutorial_index = value
        else:
            self.qtwalletbase.tutorial_index = value

    @property
    def should_be_visible(self) -> bool:
        """Should be visible."""
        return self.get_wallet_tutorial_index() is not None

    def set_visibilities(self) -> None:
        """Set visibilities."""
        self.node.setVisible(self.should_be_visible)
        plugins_node = self.qt_wallet.get_plugins_node() if self.qt_wallet else None
        show_plugins_node = bool(
            self.should_be_visible
            and plugins_node
            and self.step_container.current_index() >= self.index_of_step(TutorialStep.plugins)
            and any(not child.isHidden() for child in plugins_node.child_nodes)
        )
        if self.node.parent_node:
            for child in self.node.parent_node.child_nodes:
                if child == self.node:
                    continue
                always_visible = (
                    [self.qt_wallet.hist_node, self.qt_wallet.settings_node] if self.qt_wallet else []
                )
                child.setVisible(
                    True
                    if child in always_visible or (child == plugins_node and show_plugins_node)
                    else not self.should_be_visible
                )

        if self.should_be_visible:
            self._connect_send_test_signals()
            if current_widget := self.widgets.get(self.current_step()):
                self.step_container.signal_widget_focus.emit(current_widget)
        else:
            self._disconnect_send_test_signals()
            self._reset_send_test_runtime_state()
            if self.qt_wallet:
                self._configure_creator_for_embedded_send_test(False)
                self.qt_wallet.uitx_creator.button_box.setVisible(True)

        self._refresh_step_visibilities()

    def _refresh_step_visibilities(self) -> None:
        """Update step-local visibility hooks based on the current active step."""
        active_step = self.current_step() if self.should_be_visible else None
        for step, tab in self.tab_generators.items():
            tab.set_visibilities(step == active_step)

    def num_keystores(self) -> int:
        """Num keystores."""
        return self.qtwalletbase.get_mn_tuple()[1]

    def set_current_index(self, index: int) -> None:
        """Set current index."""
        if self.step_container.current_index() == index:
            if current_widget := self.step_container.stacked_widget.widget(index):
                current_widget.setVisible(True)
                self.step_container.signal_widget_focus.emit(current_widget)
                self.step_container.signal_set_current_widget.emit(current_widget)
            if self.current_step() not in self.get_send_tests_steps():
                self._clear_active_send_test_request()
            self._refresh_step_visibilities()
            self.signal_step_change.emit(index)
            return
        self.step_container.set_current_index(index)
        if self.current_step() not in self.get_send_tests_steps():
            self._clear_active_send_test_request()
        self._refresh_step_visibilities()
        self.signal_step_change.emit(index)

    def go_to_previous_index(self) -> None:
        """Go to previous index."""
        logger.info(
            f"go_to_previous_index: Old index {self.step_container.current_index()} = {self.current_step()}"
        )
        self.set_current_index(max(self.step_container.current_index() - 1, 0))
        logger.info(
            f"go_to_previous_index: Switched index "
            f"{self.step_container.current_index()} = {self.current_step()}"
        )

    def go_to_next_index(self) -> None:
        """Go to next index."""
        if self.step_container.step_bar.current_index + 1 >= self.step_container.step_bar.number_of_steps:
            self.set_wallet_tutorial_index(None)
            self.set_visibilities()
            if self.qt_wallet:
                self.qt_wallet.tabs.select()
            return

        logger.info(
            f"go_to_next_index: Old index {self.step_container.current_index()} = {self.current_step()}"
        )
        self.set_current_index(
            min(
                self.step_container.step_bar.current_index + 1,
                self.step_container.step_bar.number_of_steps - 1,
            )
        )
        logger.info(
            f"go_to_next_index: Switched index {self.step_container.current_index()} = {self.current_step()}"
        )

    def get_send_tests_steps(self, mn_tuple: tuple[int, int] | None = None) -> list[TutorialStep]:
        """Get send tests steps."""
        m, n = mn_tuple if mn_tuple is not None else self.qtwalletbase.get_mn_tuple()
        number = ceil(n / m)
        return list(TutorialStep.send_test_steps()[:number])

    def get_send_test_labels(self, mn_tuple: tuple[int, int] | None = None) -> list[str]:
        """Get send test labels."""
        m, n = mn_tuple if mn_tuple is not None else self.qtwalletbase.get_mn_tuple()
        keystore_labels = self.qtwalletbase.get_keystore_labels()[:n]
        keystore_labels.extend(
            [self.tr("Signer {index}").format(index=i + 1) for i in range(len(keystore_labels), n)]
        )
        groups = build_send_test_signer_groups(keystore_labels, (m, n))

        return [
            Wizard._format_send_test_label(
                self, SendTestStepPlan.from_groups(groups=groups, current_index=test_number)
            )
            for test_number in range(len(groups))
        ]

    def tx_text(self, test_number: int, mn_tuple: tuple[int, int] | None = None) -> str:
        """Tx text."""
        _m, n = mn_tuple if mn_tuple is not None else self.qtwalletbase.get_mn_tuple()
        if n == 1:
            return self.tr("Self-Send Test")
        return self.tr("Sign with {label}").format(
            label=self.get_send_test_labels(mn_tuple=mn_tuple)[test_number]
        )

    def get_displayed_steps(self, mn_tuple: tuple[int, int] | None = None) -> list[TutorialStep]:
        """Return the steps that should be visible in the progress bar."""
        _m, n = mn_tuple if mn_tuple is not None else self.qtwalletbase.get_mn_tuple()
        displayed_steps: list[TutorialStep] = []
        send_test_steps = set(self.get_send_tests_steps(mn_tuple=mn_tuple))
        all_send_test_steps = set(TutorialStep.send_test_steps())
        for step in TutorialStep.ordered_steps():
            if step == TutorialStep.register and n == 1:
                continue
            if step in all_send_test_steps and step not in send_test_steps:
                continue
            displayed_steps.append(step)
        return displayed_steps

    def open_tx(self, test_number: int) -> None:
        """Open tx."""
        if not self.qt_wallet:
            return
        m, n = self.qtwalletbase.get_mn_tuple()

        utxos = [txo for txo in self.qt_wallet.wallet.get_all_utxos()]
        if not utxos:
            Message(self.tr("The wallet is not funded. Please fund the wallet."), parent=self)
            return
        utxos = [utxos[0]]
        funded_category = self.qt_wallet.wallet.labels.get_category(utxos[0].address)

        txinfos = TxUiInfos()
        txinfos.utxo_dict = {utxo.outpoint: utxo for utxo in utxos}
        txinfos.main_wallet_id = self.qt_wallet.wallet.id

        recipient_address = str(
            self.qt_wallet.wallet.get_unused_category_address(category=funded_category).address
        )
        self.qt_wallet.wallet_signals.updated.emit(
            UpdateFilter(
                addresses={recipient_address},
                reason=UpdateFilterReason.GetUnusedCategoryAddress,
            )
        )

        txinfos.recipients.append(
            Recipient(
                recipient_address,
                0,
                checked_max_amount=True,
                label=self.tx_text(test_number),
            )
        )

        txinfos.hide_entire_input_column = True
        txinfos.recipient_read_only = True
        txinfos.hidden.post_create_action = PostCreateEnum.no_action
        txinfos.hidden.wizard_request_id = self.active_request_id
        txinfos.hidden.wizard_send_test_index = test_number
        txinfos.hidden.wizard_send_test_signer_groups = build_send_test_fingerprint_groups(
            fingerprints=[keystore.fingerprint for keystore in self.qt_wallet.wallet.keystores[:n]],
            mn_tuple=(m, n),
        )

        self.qt_wallet.uitx_creator.initial_tx_ui_infos = txinfos
        self.qt_wallet.uitx_creator.set_ui(txinfos)

    def _format_send_test_label(self, plan: SendTestStepPlan) -> str:
        """Format the signer instruction for one send test."""
        return self.tr(" and ").join([f'"{label}"' for label in plan.current_group])

    def fill_tx(self) -> None:
        """Fill tx."""
        if not self.qt_wallet:
            return

        if self.current_step() in self.get_send_tests_steps():
            test_number = self.get_send_tests_steps().index(self.current_step())
        else:
            highlighted_step = self.get_step_of_index(self.step_container.current_highlighted_index())
            if highlighted_step not in self.get_send_tests_steps():
                return
            test_number = self.get_send_tests_steps().index(highlighted_step)

        if test_number in self.pending_txid_by_send_test:
            return
        self.fill_tx_for_test(test_number)

    def updateUi(self, mn_tuple: tuple[int, int] | None = None) -> None:
        """UpdateUi."""
        labels: dict[TutorialStep, str] = {
            TutorialStep.wallet_setup: self.tr("Choose template"),
            TutorialStep.import_xpub: self.tr("Import signer info"),
            TutorialStep.receive: self.tr("Receive Test"),
            TutorialStep.distribute: self.tr("Secure your Keys"),
            TutorialStep.register: self.tr("Register multisig on signers"),
            TutorialStep.plugins: self.tr("Plugins"),
        }
        send_test_steps = self.get_send_tests_steps(mn_tuple=mn_tuple)
        for index, tutorial_step in enumerate(send_test_steps):
            labels[tutorial_step] = (
                self.tr("Self-Send test {j}").format(j=index + 1)
                if len(send_test_steps) > 1
                else self.tr("Self-Send test")
            )

        self.step_container.set_labels(
            [labels[step] for step in self.get_displayed_steps(mn_tuple=mn_tuple) if step in labels]
        )
        self.send_test_previous_button.setText(self.tr("Previous Step"))

    def _clear_widgets_and_tab_generators(self) -> None:
        """Clear widgets and tab generators."""
        while self.tab_generators:
            _step, tab = self.tab_generators.popitem()
            tab.close()

        while self.widgets:
            _step, widget = self.widgets.popitem()
            widget.close()

    def close(self) -> bool:
        """Close."""
        self._is_closing = True
        self._disconnect_send_test_signals()
        self._reset_send_test_runtime_state()
        self._clear_widgets_and_tab_generators()
        self.step_container.close()
        self.step_container.clear_widgets()
        self.qtwalletbase.outer_layout.removeWidget(self)
        self.setParent(None)
        return super().close()
