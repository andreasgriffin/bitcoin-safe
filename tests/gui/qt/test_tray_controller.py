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

from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QMainWindow
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.tray_controller import TrayController
from bitcoin_safe.gui.qt.util import Message


class _UnlockingMainWindow(QMainWindow):
    def __init__(self, unlock_result: bool) -> None:
        super().__init__()
        self._unlock_result = unlock_result
        self.unlock_calls = 0

    def try_unlock_application(self) -> bool:
        self.unlock_calls += 1
        return self._unlock_result


@pytest.mark.marker_qt_3
def test_tray_notifications_are_suppressed_while_locked(qtbot: QtBot) -> None:
    parent = _UnlockingMainWindow(unlock_result=True)
    qtbot.addWidget(parent)
    tray = TrayController(parent=parent)

    with patch.object(tray, "showMessage") as mock_show_message:
        tray.show_message(Message("first", no_show=True))
        assert mock_show_message.call_count == 1
        assert len(tray._tray_notifications) == 1

        tray.set_locked(True)
        tray.show_message(Message("second", no_show=True))
        assert mock_show_message.call_count == 1
        assert len(tray._tray_notifications) == 1

    actions = tray._tray_menu_past_notifications.actions()
    assert len(actions) == 1
    assert "hidden" in actions[0].text().lower()

    tray.hide()


@pytest.mark.marker_qt_3
def test_tray_restore_requires_unlock_when_locked(qtbot: QtBot) -> None:
    parent = _UnlockingMainWindow(unlock_result=False)
    qtbot.addWidget(parent)
    tray = TrayController(parent=parent)
    tray.set_locked(True)

    with patch.object(parent, "show") as mock_parent_show:
        tray.restore_from_tray()
        mock_parent_show.assert_not_called()

    assert parent.unlock_calls == 1
    tray.hide()
