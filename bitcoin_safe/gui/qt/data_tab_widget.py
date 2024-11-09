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
from typing import Dict, Generic, Type, TypeVar

from bitcoin_safe.gui.qt.histtabwidget import HistTabWidget

logger = logging.getLogger(__name__)

from typing import Dict, Generic, Type, TypeVar

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget

T = TypeVar("T")
T2 = TypeVar("T2")


class DataTabWidget(Generic[T], HistTabWidget):
    def __init__(self, data_class: Type[T], parent=None) -> None:
        super().__init__(parent)
        self._data_class = data_class
        self._tab_data: Dict[QWidget, T] = {}

    def setTabData(self, widget: QWidget, data: T) -> None:
        self._tab_data[widget] = data

    def tabData(self, index: int) -> T | None:
        tab = self.widget(index)
        if not tab:
            return None
        return self._tab_data[tab]

    def get_data_for_tab(self, tab: QWidget) -> T:
        return self._tab_data[tab]

    def getCurrentTabData(self) -> T | None:
        current_widget = self.currentWidget()
        if not current_widget:
            return None
        return self._tab_data[current_widget]

    def getAllTabData(self) -> Dict[QWidget, T]:
        widgets_raw = [self.widget(i) for i in range(self.count())]
        widgets = [w for w in widgets_raw if w]
        return {widget: self.get_data_for_tab(widget) for widget in widgets}

    def clearTabData(self) -> None:
        self._tab_data.clear()

    def clear(self) -> None:
        """Override the clear method to also clear the tab data."""
        super().clear()
        self._tab_data.clear()

    def addTab(  # type: ignore[override]
        self, widget: QWidget, icon: QIcon | None = None, description: str = "", data: T | None = None
    ) -> int:  # type: ignore[override]
        if icon:
            index = super().addTab(widget, icon, description)
        else:
            index = super().addTab(widget, description)
        if data is not None:
            self.setTabData(widget, data)
        return index

    def insertTab(  # type: ignore[override]
        self, index: int, widget: QWidget, data: T, icon: QIcon | None = None, description: str = ""
    ) -> int:  # type: ignore[override]
        if icon:
            new_index = super().insertTab(index, widget, icon, description)
        else:
            new_index = super().insertTab(index, widget, description)
        if data is not None:
            self.setTabData(widget, data)
        return new_index

    def add_tab(
        self,
        tab: QWidget,
        icon: QIcon | None,
        description: str,
        data: T,
        position: int | None = None,
        focus: bool = False,
    ):
        if position is None:
            index = self.addTab(tab, icon, description, data=data)
            if focus:
                self.setCurrentIndex(self.count() - 1)
        else:
            self.insertTab(position, tab, data, icon, description)
            if focus:
                self.setCurrentIndex(position)

    def removeTab(self, index: int) -> None:
        widget = self.widget(index)
        super().removeTab(index)
        if widget in self._tab_data:
            del self._tab_data[widget]


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication, QWidget

    app = QApplication(sys.argv)

    tab_widget = DataTabWidget(str)
    tab_widget.setMovable(True)
    tab1 = QWidget()
    tab2 = QWidget()

    # Example of adding tabs with and without icons
    tab_widget.addTab(tab1, description="Tab &1", data="Data for Tab 1")
    tab_widget.addTab(tab2, description="Tab &2", data="Data for Tab 2")  # No icon

    # Connect tab change signal to a function to display current tab data
    def show_current_tab_data(index) -> None:
        data = tab_widget.getCurrentTabData()
        tab_widget.setToolTip(f"Data for current tab: {data}")

    tab_widget.currentChanged.connect(show_current_tab_data)

    tab_widget.show()
    sys.exit(app.exec())
