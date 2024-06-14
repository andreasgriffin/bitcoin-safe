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
from typing import Any, Dict

logger = logging.getLogger(__name__)

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget


class DataTabWidget(QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tab_data: Dict[int, Any] = {}

    def setTabData(self, index, data) -> None:
        self.tab_data[index] = data

    def tabData(self, index) -> Any:
        return self.tab_data.get(index)

    def getCurrentTabData(self) -> Any:
        current_index = self.currentIndex()
        return self.tabData(current_index)

    def getAllTabData(self) -> Dict[int, Any]:
        return self.tab_data

    def clearTabData(self) -> None:
        self.tab_data = {}

    def addTab(self, widget, icon=None, description="", data=None) -> int:
        if icon:
            index = super().addTab(widget, QIcon(icon), description.replace("&", "").capitalize())
        else:
            index = super().addTab(widget, description.replace("&", "").capitalize())
        self.setTabData(index, data)
        return index

    def insertTab(self, index, widget, icon=None, description="", data=None) -> int:
        if icon:
            new_index = super().insertTab(
                index, widget, QIcon(icon), description.replace("&", "").capitalize()
            )
        else:
            new_index = super().insertTab(index, widget, description.replace("&", "").capitalize())
        self._updateDataAfterInsert(new_index, data)
        return new_index

    def removeTab(self, index) -> None:
        super().removeTab(index)
        self._updateDataAfterRemove(index)

    def _updateDataAfterInsert(self, new_index, data) -> None:
        new_data = {}
        for i, d in sorted(self.tab_data.items()):
            if i >= new_index:
                new_data[i + 1] = d
            else:
                new_data[i] = d
        new_data[new_index] = data
        self.tab_data = new_data

    def _updateDataAfterRemove(self, removed_index) -> None:
        new_data = {}
        for i, d in self.tab_data.items():
            if i < removed_index:
                new_data[i] = d
            elif i > removed_index:
                new_data[i - 1] = d
        self.tab_data = new_data

    def get_data_for_tab(self, tab: QWidget) -> Any:
        index = self.indexOf(tab)
        return self.tabData(index)


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

    app = QApplication(sys.argv)

    tab_widget = DataTabWidget()
    tab1 = QWidget()
    tab2 = QWidget()

    # Example of adding tabs with and without icons
    tab_widget.addTab(tab1, description="Tab &1", data="Data for Tab 1")
    tab_widget.addTab(tab2, description="Tab &2", data="Data for Tab 2")  # No icon

    # Connect tab change signal to a function to display current tab data
    def show_current_tab_data(index) -> None:
        data = tab_widget.getCurrentTabData()
        QMessageBox.information(tab_widget, "Current Tab Data", f"Data for current tab: {data}")

    tab_widget.currentChanged.connect(show_current_tab_data)

    tab_widget.show()
    sys.exit(app.exec())
