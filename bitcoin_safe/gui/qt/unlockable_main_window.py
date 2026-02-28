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

from abc import abstractmethod

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget

from bitcoin_safe.gui.qt.dialogs import PasswordQuestion
from bitcoin_safe.gui.qt.util import Message, MessageType


class UnlockableMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._app_is_locked = False
        self._unlock_prompt_open = False

    @property
    def app_is_locked(self) -> bool:
        return self._app_is_locked

    def _set_app_locked(self, locked: bool) -> None:
        self._app_is_locked = locked
        self.on_app_lock_state_changed(locked)

    def _ask_for_unlock(self) -> bool:
        if not self._app_is_locked:
            return True
        if self._unlock_prompt_open:
            return False

        self._unlock_prompt_open = True
        app_instance = QApplication.instance()
        app = app_instance if isinstance(app_instance, QApplication) else None
        restore_quit_on_last_window_closed = False
        if app and self.isHidden() and app.quitOnLastWindowClosed():
            app.setQuitOnLastWindowClosed(False)
            restore_quit_on_last_window_closed = True
        try:
            while True:
                dialog_parent: QWidget | None = None if self.isHidden() else self
                ui_password_question = PasswordQuestion(
                    parent=dialog_parent,
                    label_text=self.tr("Enter the app lock password:"),
                )
                password = ui_password_question.ask_for_password()
                if password is None:
                    return False
                if self.verify_app_lock_password(password):
                    self._set_app_locked(False)
                    return True
                Message(self.tr("Wrong app lock password."), type=MessageType.Warning, parent=self)
        finally:
            if app and restore_quit_on_last_window_closed:
                app.setQuitOnLastWindowClosed(True)
            self._unlock_prompt_open = False

    def try_unlock_application(self) -> bool:
        return self._ask_for_unlock()

    def on_app_lock_state_changed(self, locked: bool) -> None:
        pass

    @abstractmethod
    def verify_app_lock_password(self, password: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def lock_application(self) -> None:
        raise NotImplementedError
