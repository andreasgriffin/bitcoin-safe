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

import inspect
from datetime import datetime

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.constants import MIN_RELAY_FEE
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.psbt_util import FeeRate
from bitcoin_safe.tx import TxUiInfos

from ...helpers import TestConfig
from ...non_gui.test_signers import test_seeds
from .helpers import Shutter, main_window_context, setup_single_sig_wallet


def _prepare_creator_for_fee_warning_test(
    qt_wallet: QTWallet, monkeypatch: pytest.MonkeyPatch, fee_rate: float
) -> None:
    creator = qt_wallet.uitx_creator
    monkeypatch.setattr(creator.category_list, "get_selected_keys", lambda *args, **kwargs: ["selected"])
    monkeypatch.setattr(creator, "get_tx_ui_infos", lambda use_categories=None: TxUiInfos(fee_rate=fee_rate))


@pytest.mark.marker_qt_2
def test_creator_fee_warning_uses_backend_minimum(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warning should show the backend-derived minimum when available."""
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
            wallet_name="test_creator_fee_warning_uses_backend_minimum",
            seed=test_seeds[0],
        )

        _prepare_creator_for_fee_warning_test(qt_wallet, monkeypatch, fee_rate=1.5)
        monkeypatch.setattr(
            qt_wallet.wallet, "get_min_broadcast_fee_rate", lambda: FeeRate.from_float_sats_vB(2.0)
        )

        captured: list[str] = []

        def fake_question_dialog(message: str, **kwargs) -> bool:
            captured.append(message)
            return True

        monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.question_dialog", fake_question_dialog)
        qt_wallet.uitx_creator.create_tx()

        assert captured
        assert "2.0" in captured[0]


@pytest.mark.marker_qt_2
def test_creator_fee_warning_falls_back_to_min_relay_fee(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warning should fall back to the global minimum when backend data is unavailable."""
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
            wallet_name="test_creator_fee_warning_falls_back_to_min_relay_fee",
            seed=test_seeds[1],
        )

        _prepare_creator_for_fee_warning_test(qt_wallet, monkeypatch, fee_rate=0.5)
        monkeypatch.setattr(qt_wallet.wallet, "get_min_broadcast_fee_rate", lambda: None)

        captured: list[str] = []

        def fake_question_dialog(message: str, **kwargs) -> bool:
            captured.append(message)
            return True

        monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.question_dialog", fake_question_dialog)
        qt_wallet.uitx_creator.create_tx()

        assert captured
        assert str(MIN_RELAY_FEE) in captured[0]


@pytest.mark.marker_qt_2
def test_creator_fee_warning_skips_equal_minimum(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No warning should be shown when the fee rate matches the minimum."""
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
            wallet_name="test_creator_fee_warning_skips_equal_minimum",
            seed=test_seeds[2],
        )

        _prepare_creator_for_fee_warning_test(qt_wallet, monkeypatch, fee_rate=2.0)
        monkeypatch.setattr(
            qt_wallet.wallet, "get_min_broadcast_fee_rate", lambda: FeeRate.from_float_sats_vB(2.0)
        )
        qt_wallet.uitx_creator.signal_create_tx.disconnect(qt_wallet.create_psbt)

        called = False
        emitted: list[TxUiInfos] = []

        def fake_question_dialog(message: str, **kwargs) -> bool:
            nonlocal called
            called = True
            return True

        def fake_emit(tx_ui_infos: TxUiInfos) -> None:
            emitted.append(tx_ui_infos)

        qt_wallet.uitx_creator.signal_create_tx.connect(fake_emit)
        monkeypatch.setattr("bitcoin_safe.gui.qt.ui_tx.ui_tx_creator.question_dialog", fake_question_dialog)
        qt_wallet.uitx_creator.create_tx()

        assert not called
        assert len(emitted) == 1
