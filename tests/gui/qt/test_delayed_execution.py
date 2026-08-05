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

from PyQt6 import sip
from PyQt6.QtCore import QObject
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.util import delayed_execution


def test_delayed_execution_runs_while_parent_is_alive(qtbot: QtBot) -> None:
    parent = QObject()
    calls: list[bool] = []

    delayed_execution(lambda: calls.append(True), parent, delay=0)

    qtbot.waitUntil(lambda: bool(calls))
    qtbot.waitUntil(lambda: not parent.children())
    assert calls == [True]
    sip.delete(parent)


def test_delayed_execution_is_cancelled_when_parent_is_deleted(qtbot: QtBot) -> None:
    parent = QObject()
    calls: list[bool] = []
    delayed_execution(lambda: calls.append(True), parent, delay=10)

    sip.delete(parent)
    qtbot.wait(20)

    assert calls == []


def test_delayed_execution_callback_can_delete_its_parent(qtbot: QtBot) -> None:
    parent = QObject()
    delayed_execution(lambda: sip.delete(parent), parent, delay=0)

    qtbot.waitUntil(lambda: sip.isdeleted(parent))
