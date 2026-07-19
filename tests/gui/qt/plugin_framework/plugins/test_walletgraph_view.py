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

import bdkpython as bdk
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QInputDevice, QPointingDevice, QWheelEvent
from pytestqt.qtbot import QtBot

from bitcoin_safe.plugin_framework.plugins.walletgraph.wallet_graph_view import WalletGraphView


def _touchpad_wheel_event(delta_y: int) -> tuple[QPointingDevice, QWheelEvent]:
    device = QPointingDevice(
        "test-touchpad",
        1,
        QInputDevice.DeviceType.TouchPad,
        QPointingDevice.PointerType.Finger,
        QInputDevice.Capability.Position,
        2,
        0,
    )
    event = QWheelEvent(
        QPointF(10.0, 10.0),
        QPointF(10.0, 10.0),
        QPoint(),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
        device=device,
    )
    return device, event


def test_walletgraph_touchpad_wheel_still_zooms(qtbot: QtBot) -> None:
    view = WalletGraphView(network=bdk.Network.REGTEST)
    qtbot.addWidget(view)

    initial_scale = view.transform().m11()
    touchpad, event = _touchpad_wheel_event(120)
    assert touchpad.type() == QInputDevice.DeviceType.TouchPad

    view.wheelEvent(event)

    assert event.isAccepted()
    assert view.transform().m11() == pytest.approx(initial_scale * view.DEFAULT_WHEEL_ZOOM_FACTOR)
