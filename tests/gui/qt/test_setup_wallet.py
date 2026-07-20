#
# Bitcoin-Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import inspect
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from bitcoin_safe.descriptors import get_default_address_type
from bitcoin_safe.gui.qt.bitcoin_quick_receive import BitcoinQuickReceive
from bitcoin_safe.gui.qt.card_base import CardExpansionMode
from bitcoin_safe.gui.qt.dialogs import PasswordCreation
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.step_progress_bar import StepProgressContainer
from bitcoin_safe.gui.qt.wizard.wizard import (
    DistributeSeeds,
    PluginListStep,
    ReceiveTest,
    SendTest,
    TutorialStep,
    Wizard,
)
from bitcoin_safe.gui.qt.wizard.wizard_support import WizardTabInfo
from bitcoin_safe.signals import SignalsMin
from tests.faucet import Faucet

from ...helpers import TestConfig
from ...non_gui.utils import create_multisig_protowallet
from ...util import wait_for_sync
from .helpers import Shutter, main_window_context, sign_tx

logger = logging.getLogger(__name__)


def _create_wallet_with_wizard(
    main_window,
    wallet_name: str,
    threshold: int,
    signers: int,
    tutorial_index: int,
) -> QTWallet:
    """Create a real wallet with its tutorial opened at the requested step."""
    key_origin = get_default_address_type(is_multisig=signers > 1).key_origin(main_window.config.network)
    protowallet = create_multisig_protowallet(
        threshold=threshold,
        signers=signers,
        key_origins=[key_origin] * signers,
        wallet_id=wallet_name,
        network=main_window.config.network,
    )
    wallet_file = Path(main_window.config.wallet_dir) / f"{wallet_name}.wallet"
    with patch.object(QFileDialog, "getSaveFileName", return_value=(str(wallet_file), "All Files (*)")):
        with patch.object(PasswordCreation, "get_password", return_value=""):
            qt_wallet = main_window.create_qtwallet_from_protowallet(
                protowallet=protowallet,
                tutorial_index=tutorial_index,
                known_new_wallet=True,
            )
    assert isinstance(qt_wallet, QTWallet)
    assert isinstance(qt_wallet.wizard, Wizard)
    qt_wallet.wizard.node.select()
    qt_wallet.wizard.set_visibilities()
    return qt_wallet


def _complete_receive_step(
    wizard: Wizard,
    qt_wallet: QTWallet,
    faucet: Faucet,
    qtbot: QtBot,
    amount: int,
):
    """Fund the wallet, show the receive tx card, and advance manually."""
    step = wizard.tab_generators[TutorialStep.receive]
    assert isinstance(step, ReceiveTest)
    assert isinstance(step.quick_receive, BitcoinQuickReceive)
    assert not step.button_previous.isVisible()
    qtbot.waitUntil(lambda: bool(step.quick_receive and step.quick_receive.group_boxes), timeout=5_000)
    address = step.quick_receive.group_boxes[0].address
    faucet.send(destination_address=address, amount=amount, qtbot=qtbot)
    wait_for_sync(wallet=qt_wallet.wallet, qtbot=qtbot, minimum_funds=amount, timeout=30_000)

    if not step.check_button.isHidden():
        step.check_button.click()
    qtbot.waitUntil(lambda: not step.next_button.isHidden(), timeout=5_000)
    qtbot.waitUntil(lambda: step.get_received_txid() is not None, timeout=5_000)
    step.next_button.click()


def _complete_send_step(
    wizard: Wizard,
    qt_wallet: QTWallet,
    main_window,
    qtbot: QtBot,
    send_step: TutorialStep,
    shutter: Shutter,
):
    """Create, sign, broadcast, then collapse back to the recognized tx card."""
    wizard.set_current_index(wizard.index_of_step(send_step))
    wizard.set_visibilities()

    step = wizard.tab_generators[send_step]
    assert isinstance(step, SendTest)
    creator = qt_wallet.uitx_creator
    qtbot.waitUntil(lambda: creator.button_ok.isVisible(), timeout=10_000)
    assert creator.button_box.isVisible()
    assert not creator.button_back.isVisible()
    assert creator.button_clear is not None and not creator.button_clear.isVisible()
    assert not creator.rbf_bar.isVisible()
    assert not creator.cpfp_bar.isVisible()
    assert wizard.send_test_previous_button.isVisible()
    assert main_window.tab_wallets.currentNode() != qt_wallet.hist_node

    creator.button_ok.click()
    qtbot.waitUntil(
        lambda: bool(step.embedded_viewer and step.embedded_viewer.isVisible()),
        timeout=10_000,
    )
    assert step.test_number in wizard.pending_txid_by_send_test

    viewer = step.embedded_viewer
    assert viewer is not None
    assert not viewer.rbf_bar.isVisible()
    assert not viewer.cpfp_bar.isVisible()
    txid = str(viewer.extract_tx().compute_txid())
    assert main_window.get_tx_viewer(txid) is None

    sign_tx(qt_wallet=qt_wallet, qtbot=qtbot, shutter=shutter, viewer=viewer)
    viewer.button_send.click()
    assert main_window.tab_wallets.currentNode() != qt_wallet.hist_node

    wait_for_sync(qtbot=qtbot, wallet=qt_wallet.wallet, txid=txid, timeout=40_000)
    qtbot.waitUntil(lambda: txid in wizard.recognized_txids, timeout=40_000)
    qtbot.waitUntil(lambda: wizard.current_step() == send_step, timeout=5_000)
    qtbot.waitUntil(lambda: step.buttonbox.isVisible(), timeout=5_000)
    qtbot.waitUntil(lambda: step.embedded_viewer is None, timeout=5_000)
    assert txid in wizard.recognized_txids
    assert step.active_card.expansion_mode() == CardExpansionMode.FIXED_COLLAPSED
    assert txid[:4] in step.active_card.header_subtitle.text()
    assert main_window.tab_wallets.currentNode() != qt_wallet.hist_node
    step.button_next.click()


def _finish_tutorial(wizard: Wizard, qtbot: QtBot) -> None:
    """Advance through the remaining non-send wizard steps."""
    distribute = wizard.tab_generators[TutorialStep.distribute]
    assert isinstance(distribute, DistributeSeeds)
    distribute.backup_sheets_printed = True
    distribute.seed_words_attached_confirmed = True
    distribute._refresh_action_buttons()
    qtbot.waitUntil(lambda: distribute.button_next.isEnabled(), timeout=5_000)
    distribute.button_next.click()
    if wizard.should_be_visible:
        qtbot.waitUntil(lambda: wizard.current_step() == TutorialStep.plugins, timeout=5_000)

        plugins = wizard.tab_generators[TutorialStep.plugins]
        assert isinstance(plugins, PluginListStep)
        qtbot.waitUntil(lambda: plugins.button_next.isVisible(), timeout=5_000)
        qtbot.waitUntil(lambda: plugins.button_next.isEnabled(), timeout=5_000)
        plugins.button_next.click()
    qtbot.waitUntil(lambda: not wizard.should_be_visible, timeout=5_000)


@pytest.mark.marker_qt_1
def test_distribute_step_update_ui_after_close_does_not_raise(
    qtbot: QtBot,
    test_config: TestConfig,
    backend: str,
) -> None:
    """Closing the distribute step must not break late UI refreshes during teardown."""
    del test_config
    del backend
    container = StepProgressContainer(
        step_labels=["Distribute"],
        signals_min=SignalsMin(),
        loop_in_thread=MagicMock(),
    )
    qtbot.addWidget(container)

    fake_qtwalletbase = MagicMock()
    fake_qtwalletbase.tabs = MagicMock()
    fake_qtwalletbase.signals = SignalsMin()
    fake_qtwalletbase.get_mn_tuple.return_value = (1, 1)

    refs = WizardTabInfo(
        container=container,
        qtwalletbase=fake_qtwalletbase,
        go_to_next_index=lambda: None,
        go_to_previous_index=lambda: None,
        signal_create_wallet=MagicMock(),
        max_test_fund=0,
    )
    distribute = DistributeSeeds(
        refs=refs,
        loop_in_thread=MagicMock(),
        show_previous_step_button=True,
    )

    tutorial_widget = distribute.create()
    qtbot.addWidget(tutorial_widget)

    distribute.close()
    distribute.updateUi()


@pytest.mark.marker_qt_1
def test_wizard(
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
    backend: str,
    wallet_name: str = "test_wizard",
    amount: int = int(1e6),
) -> None:
    """Single-sig wizard stays inside the wizard during the send test."""
    del backend
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        qt_wallet = _create_wallet_with_wizard(
            main_window=main_window,
            wallet_name=wallet_name,
            threshold=1,
            signers=1,
            tutorial_index=0,
        )
        wizard = qt_wallet.wizard
        assert isinstance(wizard, Wizard)

        _complete_receive_step(wizard=wizard, qt_wallet=qt_wallet, faucet=faucet, qtbot=qtbot, amount=amount)
        _complete_send_step(
            wizard=wizard,
            qt_wallet=qt_wallet,
            main_window=main_window,
            qtbot=qtbot,
            send_step=TutorialStep.send,
            shutter=shutter,
        )
        assert wizard.current_step() == TutorialStep.distribute

        distribute = wizard.tab_generators[TutorialStep.distribute]
        assert isinstance(distribute, DistributeSeeds)
        distribute.button_previous.click()
        assert wizard.current_step() == TutorialStep.send

        send_step = wizard.tab_generators[TutorialStep.send]
        assert isinstance(send_step, SendTest)
        qtbot.waitUntil(lambda: send_step.buttonbox.isVisible(), timeout=5_000)
        assert send_step.embedded_viewer is None
        assert send_step.active_card.expansion_mode() == CardExpansionMode.FIXED_COLLAPSED
        send_step.button_next.click()
        assert wizard.current_step() == TutorialStep.distribute

        _finish_tutorial(wizard, qtbot=qtbot)
        assert not wizard.should_be_visible


@pytest.mark.marker_qt_1
def test_plugins_step_reparents_plugin_manager_widget(
    qtbot: QtBot,
    test_config: TestConfig,
    backend: str,
    wallet_name: str = "test_plugins_step_reparents_widget",
) -> None:
    """The final tutorial step temporarily hosts the existing plugin manager widget."""
    del backend
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        qt_wallet = _create_wallet_with_wizard(
            main_window=main_window,
            wallet_name=wallet_name,
            threshold=1,
            signers=1,
            tutorial_index=0,
        )
        wizard = qt_wallet.wizard
        assert isinstance(wizard, Wizard)

        plugins_step = wizard.tab_generators[TutorialStep.plugins]
        assert isinstance(plugins_step, PluginListStep)
        plugin_widget = qt_wallet.plugin_manager_widget
        plugins_node = qt_wallet.get_plugins_node()
        assert plugin_widget is not None
        assert plugins_node is not None
        assert qt_wallet.tabs.findNodeByWidget(plugin_widget) == plugins_node

        wizard.set_current_index(wizard.index_of_step(TutorialStep.plugins))
        qtbot.waitUntil(lambda: plugins_step.plugins_host_layout.indexOf(plugin_widget) != -1, timeout=5_000)
        assert plugin_widget.parentWidget() == plugins_step.plugins_host

        wizard.set_current_index(wizard.index_of_step(TutorialStep.distribute))
        qtbot.waitUntil(lambda: qt_wallet.tabs.findNodeByWidget(plugin_widget) == plugins_node, timeout=5_000)
        assert plugins_step.plugins_host_layout.indexOf(plugin_widget) == -1

        wizard.set_current_index(wizard.index_of_step(TutorialStep.plugins))
        qtbot.waitUntil(lambda: plugins_step.plugins_host_layout.indexOf(plugin_widget) != -1, timeout=5_000)
        plugins_step.button_next.click()
        qtbot.waitUntil(lambda: wizard.current_step() == TutorialStep.receive, timeout=5_000)
        assert wizard.should_be_visible
        qtbot.waitUntil(lambda: qt_wallet.tabs.findNodeByWidget(plugin_widget) == plugins_node, timeout=5_000)
        qt_wallet.tabs.setCurrentWidget(plugin_widget)
        assert qt_wallet.tabs.currentWidget() == plugin_widget


@pytest.mark.marker_qt_1
def test_plugins_step_shows_enabled_plugin_in_sidebar(
    qtbot: QtBot,
    test_config: TestConfig,
    backend: str,
    wallet_name: str = "test_plugins_step_shows_enabled_plugin_in_sidebar",
) -> None:
    """Enabling a plugin during the plugins step restores the sidebar root and child node."""
    del backend
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore
        qt_wallet = _create_wallet_with_wizard(
            main_window=main_window,
            wallet_name=wallet_name,
            threshold=1,
            signers=1,
            tutorial_index=0,
        )
        wizard = qt_wallet.wizard
        assert isinstance(wizard, Wizard)

        plugins_step = wizard.tab_generators[TutorialStep.plugins]
        assert isinstance(plugins_step, PluginListStep)
        plugin_manager_widget = qt_wallet.plugin_manager_widget
        plugins_node = qt_wallet.get_plugins_node()
        assert plugin_manager_widget is not None
        assert plugins_node is not None

        wizard.set_current_index(wizard.index_of_step(TutorialStep.plugins))
        qtbot.waitUntil(
            lambda: plugins_step.plugins_host_layout.indexOf(plugin_manager_widget) != -1, timeout=5_000
        )
        assert plugins_node.isHidden()

        plugin_list_widget = next(
            (
                plugin_widget
                for plugin_widget in plugin_manager_widget.plugins_widgets
                if plugin_widget.plugin.supports_enable_toggle()
            ),
            None,
        )
        assert plugin_list_widget is not None
        plugin_node = plugin_list_widget.plugin.node
        assert plugin_node.parent_node == plugins_node
        assert plugin_node.isHidden()

        plugin_list_widget.enable_checkbox.click()
        qtbot.waitUntil(lambda: plugin_list_widget.plugin.enabled, timeout=5_000)
        qtbot.waitUntil(lambda: not plugins_node.isHidden(), timeout=5_000)
        qtbot.waitUntil(lambda: not plugin_node.isHidden(), timeout=5_000)

        plugins_step.button_next.click()
        qtbot.waitUntil(lambda: wizard.current_step() == TutorialStep.receive, timeout=5_000)
        assert not plugins_node.isHidden()
        assert not plugin_node.isHidden()

        wizard.set_current_index(wizard.index_of_step(TutorialStep.distribute))
        qtbot.waitUntil(lambda: wizard.current_step() == TutorialStep.distribute, timeout=5_000)
        assert not plugins_node.isHidden()
        assert not plugin_node.isHidden()
