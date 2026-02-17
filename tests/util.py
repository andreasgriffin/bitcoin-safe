#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QCoreApplication, QObject, pyqtBoundSignal, pyqtSignal
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.util import one_time_signal_connection
from bitcoin_safe.pythonbdk_types import BlockchainType
from bitcoin_safe.util import SATOSHIS_PER_BTC
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


def get_timeout_scale() -> float:
    value = os.getenv("CI_TIMEOUT_SCALE", "1")
    try:
        scale = float(value)
    except ValueError:
        return 1.0
    return scale if scale >= 1.0 else 1.0


def scale_timeout(timeout: float) -> float:
    return timeout * get_timeout_scale()


class MySignalclass(QObject):
    signal = cast(SignalProtocol[[]], pyqtSignal())


def chained_one_time_signal_connections(
    signals: list[pyqtBoundSignal], fs: list[Callable[..., bool]], disconnect_only_if_f_true=True
):
    "If after the i. f is called, it connects the i+1. signal"

    signal, remaining_signals = signals[0], signals[1:]
    f, remaining_fs = fs[0], fs[1:]

    def f_wrapper(*args, **kwargs):
        """F wrapper."""
        res = f(*args, **kwargs)
        if disconnect_only_if_f_true and not res:
            # reconnect
            one_time_signal_connection(signal, f_wrapper)
        elif remaining_signals and remaining_fs:
            chained_one_time_signal_connections(remaining_signals, remaining_fs)
        return res

    one_time_signal_connection(signal, f_wrapper)


def make_psbt(
    wallet: Wallet,
    destination_address: str,
    amount=SATOSHIS_PER_BTC,
    fee_rate=1,
):
    """Make psbt."""
    txbuilder = bdk.TxBuilder()

    txbuilder = txbuilder.add_recipient(
        bdk.Address(destination_address, wallet.network).script_pubkey(), bdk.Amount.from_sat(amount)
    )

    txbuilder = txbuilder.fee_rate(bdk.FeeRate.from_sat_per_vb(fee_rate))

    psbt = txbuilder.finish(wallet.bdkwallet)
    wallet.persist()

    logger.debug(f"psbt to {destination_address}: {psbt.serialize()}\n")

    return psbt


def wait_for_sync(
    qtbot: QtBot,
    wallet: Wallet,
    minimum_funds=0,
    txid: str | None = None,
    tx_count: int = 0,
    timeout: float = 10_000,
):
    effective_timeout = scale_timeout(timeout)

    def info_message():
        logger.info(
            f"{wallet.id=}\n"
            f"{wallet.get_balance().total=} and {minimum_funds=}\n"
            f"{(not txid or wallet.get_tx(txid))=} and {txid=}"
            f"{len(wallet.bdkwallet.transactions())=} and {tx_count=}"
        )

    def condition() -> bool:
        res = bool(
            wallet.get_balance().total >= minimum_funds
            and (not txid or wallet.get_tx(txid))
            and len(wallet.bdkwallet.transactions()) >= tx_count
        )
        if not res:
            info_message()
            QCoreApplication.processEvents()
            qtbot.wait(200)
        return res

    if condition():
        logger.info("No need to wait. Condition already satisfied")
        return

    if wallet.config.network_config.server_type == BlockchainType.CompactBlockFilter:
        # since p2p listenting and
        # cbf node syncronization happens without any triggering in the background
        # we just have to wait
        try:
            qtbot.waitUntil(condition, timeout=int(effective_timeout))
        except Exception:
            raise
        finally:
            info_message()

    else:
        # electrum servers need active sync triggering
        async def wait_for_funds():
            """Wait for funds."""
            deadline = asyncio.get_event_loop().time() + effective_timeout
            original_funds = wallet.get_balance().total
            while not condition():
                await asyncio.sleep(0.5)
                # first try to wait for incoming p2p transactions

                # try the sync
                QApplication.processEvents()
                wallet.trigger_sync()
                await wallet.update()  # this is blocking

                if asyncio.get_event_loop().time() > deadline:
                    raise TimeoutError("Conditions not met")

            logger.info(f"{wallet.id=} received {wallet.get_balance().total - original_funds} new Sats")

        wallet.loop_in_thread.run_foreground(wait_for_funds())
        info_message()
