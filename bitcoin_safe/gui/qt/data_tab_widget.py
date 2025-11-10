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

import logging
from typing import Generic, TypeVar, cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget

from bitcoin_safe.gui.qt.histtabwidget import HistTabWidget

logger = logging.getLogger(__name__)

T = TypeVar("T")
T2 = TypeVar("T2")


class DataTabWidget(HistTabWidget, Generic[T]):
    signal_on_tab_change = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self._tab_data: dict[QWidget, T] = {}
        self.currentChanged.connect(self.signal_on_tab_change.emit)

    def setTabData(self, widget: QWidget, data: T) -> None:
        """SetTabData."""
        self._tab_data[widget] = data

    def tabData(self, index: int) -> T | None:
        """TabData."""
        tab = self.widget(index)
        if not tab:
            return None
        return self._tab_data.get(tab)

    def get_data_for_tab(self, tab: QWidget) -> T:
        """Get data for tab."""
        return self._tab_data[tab]

    def getCurrentTabData(self) -> T | None:
        """GetCurrentTabData."""
        current_widget = self.currentWidget()
        if not current_widget:
            return None
        return self._tab_data[current_widget]

    def getAllTabData(self) -> dict[QWidget, T]:
        """GetAllTabData."""
        return self._tab_data

    def clearTabData(self) -> None:
        """ClearTabData."""
        self._tab_data.clear()

    def clear(self) -> None:
        """Override the clear method to also clear the tab data."""
        super().clear()
        self._tab_data.clear()

    def addTab(  # type: ignore[override]
        self, widget: QWidget, icon: QIcon | None = None, description: str = "", data: T | None = None
    ) -> int:  # type: ignore[override]
        """AddTab."""
        if icon:
            index = super().addTab(widget, icon, description)
        else:
            index = super().addTab(widget, description)
        if data is not None:
            self.setTabData(widget, data)

        self.signal_on_tab_change.emit()
        return index

    def insertTab(  # type: ignore[override]
        self, index: int, widget: QWidget, data: T, icon: QIcon | None = None, description: str = ""
    ) -> int:  # type: ignore[override]
        """InsertTab."""
        if icon:
            new_index = super().insertTab(index, widget, icon, description)
        else:
            new_index = super().insertTab(index, widget, description)
        if data is not None:
            self.setTabData(widget, data)

        self.signal_on_tab_change.emit()
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
        """Add tab."""
        if position is None:
            self.addTab(tab, icon, description, data=data)
            if focus:
                self.setCurrentIndex(self.count() - 1)
        else:
            self.insertTab(position, tab, data, icon, description)
            if focus:
                self.setCurrentIndex(position)

    def removeTab(self, index: int) -> None:
        """RemoveTab."""
        widget = self.widget(index)
        if widget in self._tab_data:
            del self._tab_data[widget]
        super().removeTab(index)
        if widget:
            widget.setParent(None)  # Detach it from the parent
        self.signal_on_tab_change.emit()


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication, QWidget

    app = QApplication(sys.argv)

    tab_widget = DataTabWidget[str]()
    tab_widget.setMovable(True)
    tab1 = QWidget()
    tab2 = QWidget()

    # Example of adding tabs with and without icons
    tab_widget.addTab(tab1, description="Tab &1", data="Data for Tab 1")
    tab_widget.addTab(tab2, description="Tab &2", data="Data for Tab 2")  # No icon

    # Connect tab change signal to a function to display current tab data
    def show_current_tab_data(index) -> None:
        """Show current tab data."""
        data = tab_widget.getCurrentTabData()
        tab_widget.setToolTip(f"Data for current tab: {data}")

    tab_widget.currentChanged.connect(show_current_tab_data)

    tab_widget.show()
    sys.exit(app.exec())
