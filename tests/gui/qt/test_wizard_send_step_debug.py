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

import inspect
from datetime import datetime

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.wizard.wizard import SendTest, TutorialStep, Wizard

from ...faucet import Faucet
from ...helpers import TestConfig
from ...non_gui.test_signers import test_seeds
from ...util import wait_for_sync
from .helpers import Shutter, main_window_context, setup_single_sig_wallet


@pytest.mark.marker_qt_2
def test_debug_single_sig_send_step_layout(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    faucet: Faucet,
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")
    shutter.create_symlink(test_config=test_config)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)
        qt_wallet = setup_single_sig_wallet(
            main_window=main_window,
            qtbot=qtbot,
            shutter=shutter,
            test_config=test_config,
            wallet_name="debug_send_step",
            seed=test_seeds[0],
        )
        assert isinstance(qt_wallet, QTWallet)

        faucet.send(
            destination_address=str(qt_wallet.wallet.get_address().address), amount=1_000_000, qtbot=qtbot
        )
        wait_for_sync(wallet=qt_wallet, qtbot=qtbot, minimum_funds=1_000_000, timeout=30_000)

        wizard = qt_wallet.wizard
        assert isinstance(wizard, Wizard)
        main_window.resize(1280, 900)
        wizard.toggle_tutorial()
        wizard.set_current_index(wizard.index_of_step(TutorialStep.send))
        wizard.on_send_test_step_activated(0)
        qtbot.waitUntil(lambda: qt_wallet.uitx_creator.isVisible(), timeout=10_000)
        qtbot.wait(500)

        step = wizard.tab_generators[TutorialStep.send]
        assert isinstance(step, SendTest)

        print("MAIN", main_window.geometry())
        print("ACTIVE_CARD", step.active_card.geometry())
        print("CARD_CONTENT", step.active_card.content_widget.geometry())
        print("UITX", qt_wallet.uitx_creator.geometry())
        print("UITX_LAYOUT", qt_wallet.uitx_creator.layout().contentsRect())
        print(
            "WARNINGS",
            [
                (
                    widget.__class__.__name__,
                    widget.isVisible(),
                    widget.isHidden(),
                    widget.geometry(),
                )
                for widget in [
                    qt_wallet.uitx_creator.high_fee_rate_warning_label,
                    qt_wallet.uitx_creator.high_fee_warning_label,
                    qt_wallet.uitx_creator.nlocktime_warning_label,
                    qt_wallet.uitx_creator.category_linking_warning_bar,
                    qt_wallet.uitx_creator.rbf_bar,
                    qt_wallet.uitx_creator.cpfp_bar,
                ]
            ],
        )
        print("SPLITTER", qt_wallet.uitx_creator.splitter.geometry())
        print("RECIP_HEADER", qt_wallet.uitx_creator.column_recipients.header_widget.geometry())
        print("RECIPIENTS", qt_wallet.uitx_creator.column_recipients.recipients.geometry())
        print("BUTTON_BOX", qt_wallet.uitx_creator.button_box.geometry())

        shutter.save(main_window, delay=0.5)
