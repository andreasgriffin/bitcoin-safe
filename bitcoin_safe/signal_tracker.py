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
from typing import Callable, List, Tuple, TypeVar

from PyQt6.QtCore import QObject, pyqtBoundSignal

from bitcoin_safe.signals import SignalFunction, SingularSignalFunction

from .typestubs import TypedPyQtSignal, TypedPyQtSignalNo

logger = logging.getLogger(__name__)


T0 = TypeVar("T0", bound=SingularSignalFunction)
T1 = TypeVar("T1", bound=SignalFunction)
T2 = TypeVar("T2", bound=pyqtBoundSignal)
T3 = TypeVar("T3", bound=TypedPyQtSignalNo)
T4 = TypeVar("T4", bound=TypedPyQtSignal)


class SignalTools:
    @classmethod
    def disconnect_all_signals_from(cls, object_with_bound_signals: QObject) -> None:
        """Finds any qtBoundSignal attached to object_with_bound_signals
        and removes all connections of them

        Args:
            object_with_bound_signals (Any): _description_
        """

        def discon_sig(signal: pyqtBoundSignal | TypedPyQtSignalNo | TypedPyQtSignal):
            """
            Disconnect only breaks one connection at a time,
            so loop to be safe.
            """
            while True:
                try:
                    signal.disconnect()
                except TypeError:
                    break
            return

        for signal_name in dir(object_with_bound_signals):
            if signal_name in ["destroyed"]:
                continue
            signal = getattr(object_with_bound_signals, signal_name)
            if isinstance(signal, pyqtBoundSignal):
                discon_sig(signal)

    @classmethod
    def connect_signal(
        cls, signal: T0 | T1 | T2 | T3 | T4, f: Callable, **kwargs
    ) -> Tuple[T0 | T1 | T2 | T3 | T4, Callable]:
        signal.connect(f, **kwargs)
        return (signal, f)

    @classmethod
    def connect_signal_and_append(
        cls,
        connected_signals: List[
            Tuple[
                pyqtBoundSignal
                | SingularSignalFunction
                | SignalFunction
                | TypedPyQtSignalNo
                | TypedPyQtSignal,
                Callable,
            ]
        ],
        signal: (
            pyqtBoundSignal | SingularSignalFunction | SignalFunction | TypedPyQtSignalNo | TypedPyQtSignal
        ),
        f: Callable,
        **kwargs,
    ) -> None:
        signal.connect(f, **kwargs)
        connected_signals.append((signal, f))

    @classmethod
    def disconnect_signal(
        cls,
        signal: (
            pyqtBoundSignal | SingularSignalFunction | SignalFunction | TypedPyQtSignalNo | TypedPyQtSignal
        ),
        f: Callable,
    ) -> None:
        try:
            signal.disconnect(f)
        except:
            logger.debug(f"Could not disconnect {signal=} from {f=}")

    @classmethod
    def disconnect_signals(
        cls,
        connected_signals: List[
            Tuple[
                pyqtBoundSignal
                | SingularSignalFunction
                | SignalFunction
                | TypedPyQtSignalNo
                | TypedPyQtSignal,
                Callable,
            ]
        ],
    ) -> None:
        while connected_signals:
            signal, f = connected_signals.pop()
            cls.disconnect_signal(signal=signal, f=f)


class SignalTracker:
    def __init__(self) -> None:
        self._connected_signals: List[
            Tuple[
                SignalFunction
                | SingularSignalFunction
                | pyqtBoundSignal
                | TypedPyQtSignalNo
                | TypedPyQtSignal,
                Callable,
            ]
        ] = []

    def connect(
        self,
        signal: (
            SignalFunction | SingularSignalFunction | pyqtBoundSignal | TypedPyQtSignalNo | TypedPyQtSignal
        ),
        f: Callable,
        **kwargs,
    ) -> None:
        signal.connect(f, **kwargs)
        self._connected_signals.append((signal, f))

    def disconnect_all(self):
        SignalTools.disconnect_signals(self._connected_signals)
