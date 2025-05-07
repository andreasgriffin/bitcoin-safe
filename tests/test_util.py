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
from pathlib import Path
from typing import Callable, List
from unittest.mock import patch

import bdkpython as bdk
from _pytest.logging import LogCaptureFixture
from bitcoin_tools.util import path_to_rel_home_path, rel_home_path_to_abs_path
from PyQt6.QtCore import QObject, pyqtBoundSignal, pyqtSignal

from bitcoin_safe.gui.qt.util import one_time_signal_connection
from bitcoin_safe.signals import TypedPyQtSignalNo

# from bitcoin_safe.logging_setup import setup_logging


# import the __main__ because it setsup the logging


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


@patch("pathlib.Path.home")
def test_path_to_rel_home_path(mock_home):
    # Mock the home directory to a fixed path
    mock_home.return_value = Path("/home/user")

    # Define a test case
    test_abs_path = Path("/home/user/documents/test.txt")
    expected_rel_path = Path("documents/test.txt")

    # Test the path_to_rel_home_path function
    assert (
        Path(path_to_rel_home_path(test_abs_path)) == expected_rel_path
    ), "Failed to convert absolute path to relative path correctly"


@patch("pathlib.Path.home")
def test_rel_path_to_abs_path(mock_home):
    # Mock the home directory to a fixed path
    mock_home.return_value = Path("/home/user")

    # Define a test case
    test_rel_path = Path("documents/test.txt")
    expected_abs_path = Path("/home/user/documents/test.txt")

    # Test the rel_path_to_abs_path function
    assert (
        Path(rel_home_path_to_abs_path(test_rel_path)) == expected_abs_path
    ), "Failed to convert relative path to absolute path correctly"


@patch("pathlib.Path.home")
def test_rel_path_to_abs_path_with_given_absolute(mock_home):
    # Mock the home directory to a fixed path
    mock_home.return_value = Path("/home/user")

    # Define a test case
    test_rel_path = Path("/home/user/documents/test.txt")
    expected_abs_path = Path("/home/user/documents/test.txt")

    # Test the rel_path_to_abs_path function
    assert (
        Path(rel_home_path_to_abs_path(test_rel_path)) == expected_abs_path
    ), "Failed to convert relative path to absolute path correctly"


@patch("pathlib.Path.home")
def test_conversion_round_trip(mock_home):
    # Mock the home directory to a fixed path
    mock_home.return_value = Path("/home/user")

    # A path for round-trip conversion
    original_path = Path("/home/user/documents/round_trip_test.txt")

    # Convert to relative and back to absolute
    rel_path = Path(path_to_rel_home_path(original_path))
    round_trip_path = Path(rel_home_path_to_abs_path(rel_path))

    assert round_trip_path == original_path, "Round-trip conversion did not return the original path"


def test_chained_one_time_signal_connections(caplog: LogCaptureFixture):
    with caplog.at_level(logging.INFO):

        n = 4
        instances = [MySignalclass() for _ in range(n)]

        def factory(i, instance):
            def f(i=i, instance=instance):
                logger.info(str(i))
                return True

            return f

        fs = [factory(i, instance) for i, instance in enumerate(instances)]

        chained_one_time_signal_connections([instance.signal for instance in instances], fs)

        for instance in instances:
            instance.signal.emit()
            instance.signal.emit()

        for instance in instances:
            instance.signal.emit()
            instance.signal.emit()

        assert [record.msg for record in caplog.records] == [str(i) for i in range(n)]


def test_chained_one_time_signal_connections_prevent_disconnect(caplog: LogCaptureFixture):
    # repeat, but now do not return True
    with caplog.at_level(logging.INFO):

        n = 4
        instances = [MySignalclass() for _ in range(n)]

        def factory(i, instance):
            def f(i=i, instance=instance):
                logger.info(str(i))
                return None

            return f

        fs = [factory(i, instance) for i, instance in enumerate(instances)]

        chained_one_time_signal_connections([instance.signal for instance in instances], fs)

        for instance in instances:
            instance.signal.emit()

        for instance in instances:
            instance.signal.emit()

        # since f(0) == None, the 1. signal simply reconnects
        assert [record.msg for record in caplog.records] == ["0", "0"]


def make_psbt(
    bdk_wallet: bdk.Wallet, network: bdk.Network, destination_address: str, amount=100_000_000, fee_rate=1
):
    txbuilder = bdk.TxBuilder()

    txbuilder = txbuilder.add_recipient(
        bdk.Address(destination_address, network).script_pubkey(), int(amount)
    )

    txbuilder = txbuilder.fee_rate(fee_rate)

    psbt = txbuilder.finish(bdk_wallet)

    logger.debug(f"psbt to {destination_address}: {psbt.serialize()}\n")

    psbt_for_signing = bdk.Psbt(psbt.serialize())
    return psbt_for_signing
