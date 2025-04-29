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


import logging
from typing import Callable, List

import bdkpython as bdk
from PyQt6.QtCore import QObject, pyqtBoundSignal, pyqtSignal

from bitcoin_safe.gui.qt.util import one_time_signal_connection
from bitcoin_safe.signals import TypedPyQtSignalNo

logger = logging.getLogger(__name__)


class MySignalclass(QObject):
    signal: TypedPyQtSignalNo = pyqtSignal()  # type: ignore


def chained_one_time_signal_connections(
    signals: List[pyqtBoundSignal], fs: List[Callable[..., bool]], disconnect_only_if_f_true=True
):
    "If after the i. f is called, it connects the i+1. signal"

    signal, remaining_signals = signals[0], signals[1:]
    f, remaining_fs = fs[0], fs[1:]

    def f_wrapper(*args, **kwargs):
        res = f(*args, **kwargs)
        if disconnect_only_if_f_true and not res:
            # reconnect
            one_time_signal_connection(signal, f_wrapper)
        elif remaining_signals and remaining_fs:
            chained_one_time_signal_connections(remaining_signals, remaining_fs)
        return res

    one_time_signal_connection(signal, f_wrapper)


def make_psbt(
    bdk_wallet: bdk.Wallet, network: bdk.Network, destination_address: str, amount=100_000_000, fee_rate=1
):
    txbuilder = bdk.TxBuilder()

    txbuilder = txbuilder.add_recipient(
        bdk.Address(destination_address, network).script_pubkey(), bdk.Amount.from_sat(amount)
    )

    txbuilder = txbuilder.fee_rate(bdk.FeeRate.from_sat_per_vb(fee_rate))

    psbt = txbuilder.finish(bdk_wallet)

    logger.debug(f"psbt to {destination_address}: {psbt.serialize()}\n")

    psbt_for_signing = bdk.Psbt(psbt.serialize())
    return psbt_for_signing
