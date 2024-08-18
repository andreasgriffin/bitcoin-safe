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


from typing import Dict

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget


class SignalEmitter(QObject):
    change_tab = pyqtSignal(int)


class GroupSignalManager:
    signals: Dict[str, SignalEmitter] = {}

    @classmethod
    def get_emitter(cls, group: str) -> SignalEmitter:
        if group not in cls.signals:
            cls.signals[group] = SignalEmitter()
        return cls.signals[group]


class SyncedTabWidget(QTabWidget):
    def __init__(
        self,
        group: str,
        parent: QWidget | None = None,
        tab_position: QTabWidget.TabPosition = QTabWidget.TabPosition.North,
    ) -> None:
        super().__init__(parent)
        self.group = group
        self.emitter: SignalEmitter = GroupSignalManager.get_emitter(self.group)
        # Connect to a custom method instead of directly to setCurrentIndex
        self.emitter.change_tab.connect(self.safeSetCurrentIndex)
        self.currentChanged.connect(self.onTabChange)

        # Set the tab position
        self.setTabPosition(tab_position)

    def onTabChange(self, index: int) -> None:
        self.emitter.change_tab.emit(index)

    def safeSetCurrentIndex(self, index: int) -> None:
        # Check if the index is within the valid range before setting it
        if 0 <= index < self.count():
            self.setCurrentIndex(index)


if __name__ == "__main__":

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Grouped Synced Tab Widgets")

            centralWidget = QWidget()
            self.setCentralWidget(centralWidget)
            layout = QVBoxLayout(centralWidget)

            # Create SyncedTabWidgets in different groups
            for group_name in ["g1", "g2"]:
                for _ in range(3):
                    tabWidget = SyncedTabWidget(group_name)
                    tabWidget.addTab(QWidget(), group_name + ".d1")
                    tabWidget.addTab(QWidget(), group_name + ".d2")
                    layout.addWidget(tabWidget)

    app = QApplication([])
    mainWindow = MainWindow()
    mainWindow.show()
    app.exec()
