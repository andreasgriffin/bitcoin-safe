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


from typing import Optional

from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.unique_deque import UniqueDeque


class HistTabWidget(QTabWidget):
    """Stores the closing activation history of the tabs and upon close, activates the last active one.

    Args:
        QTabWidget: Inherits from QTabWidget.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._tab_history: UniqueDeque[int] = UniqueDeque(maxlen=100000)  # History of activated tab indices
        self.currentChanged.connect(self.on_current_changed)

    def on_current_changed(self, index: int) -> None:
        """Updates the tab history when the current tab is changed.

        Args:
            index (int): The index of the newly activated tab.
        """
        if index >= 0:
            self._tab_history.append(index)

    def remove_tab_from_history(self, index: int) -> None:
        """Handles the tab close request, updating history and setting the last active tab.

        Args:
            index (int): The index of the tab that is being closed.
        """
        # Remove the closed tab from history and adjust the indices
        if index in self._tab_history:
            self._tab_history = UniqueDeque([i for i in self._tab_history if i != index])
        self._tab_history = UniqueDeque([i - 1 if i > index else i for i in self._tab_history])

    def get_last_active_tab(self) -> int:
        if len(self._tab_history) >= 2:
            return self._tab_history[-2]
        elif len(self._tab_history) >= 1:
            return self._tab_history[-1]
        return self.currentIndex()

    def jump_to_last_active_tab(self) -> None:
        """Sets the current tab to the last active one from history or to the first tab if history is empty."""
        index = self.get_last_active_tab()
        if index >= 0:
            self.setCurrentIndex(index)

    def removeTab(self, index: int) -> None:
        self.remove_tab_from_history(index)
        return super().removeTab(index)


if __name__ == "__main__":

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.tab_widget = HistTabWidget()
            self.tab_widget.setTabsClosable(True)

            def remove(index):
                self.tab_widget.jump_to_last_active_tab()
                self.tab_widget.removeTab(index)

            self.tab_widget.tabCloseRequested.connect(remove)
            self.tab_widget.currentChanged.connect(
                lambda: print(f"on_currentChanged = {self.tab_widget._tab_history}")
            )
            self.setCentralWidget(self.tab_widget)
            # Adding example tabs
            for i in range(5):
                tab = QWidget()
                layout = QVBoxLayout()
                label = QLabel(f"Content of tab {i + 1}")
                layout.addWidget(label)
                tab.setLayout(layout)
                self.tab_widget.addTab(tab, f"Tab {i + 1}")

            self.setGeometry(300, 300, 400, 300)

    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
