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


from typing import Any, Callable, Optional, Union

from PyQt6.QtCore import pyqtBoundSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QMenuBar


class Menu(QMenu):
    def add_action(
        self,
        text="",
        slot: Optional[Union[Callable[[], Any], pyqtBoundSignal]] = None,
        icon: QIcon | None = None,
    ) -> QAction:
        action = QAction(text=text, parent=self)
        if slot:
            if callable(slot):
                action.triggered.connect(lambda: slot())
            else:
                action.triggered.connect(slot)
        self.addAction(action)
        if icon:
            action.setIcon(icon)
        return action

    def add_menu(self, text="") -> "Menu":
        menu = Menu(text, self)
        self.addMenu(menu)
        return menu


class MenuBar(QMenuBar):
    def add_menu(self, text="") -> Menu:
        menu = Menu(text, self)
        self.addMenu(menu)
        return menu
