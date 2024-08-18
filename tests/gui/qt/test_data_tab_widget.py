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

from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget

logger = logging.getLogger(__name__)


import pytest
from PyQt6.QtWidgets import QApplication, QWidget


@pytest.fixture
def data_tab_widget(qapp: QApplication) -> DataTabWidget:
    """Fixture to create a DataTabWidget instance with string data."""
    widget = DataTabWidget(str)
    return widget


def test_add_tab(data_tab_widget: DataTabWidget):
    """Test adding tabs and verifying data storage."""
    widget = data_tab_widget
    tab1 = QWidget()
    data1 = "Data for tab 1"
    index1 = widget.addTab(tab1, description="Tab 1", data=data1)
    assert index1 == 0
    assert len(widget._tab_data) == 1
    assert widget.tabData(index1) == data1

    tab2 = QWidget()
    data2 = "Data for tab 2"
    index2 = widget.addTab(tab2, description="Tab 2", data=data2)
    assert index2 == 1
    assert len(widget._tab_data) == 2
    assert widget.tabData(index2) == data2


def test_insert_tab(data_tab_widget: DataTabWidget):
    """Test inserting a tab and verifying data consistency."""
    widget = data_tab_widget
    tab1 = QWidget()
    data1 = "Data for tab 1"
    widget.addTab(tab1, description="Tab 1", data=data1)
    tab2 = QWidget()
    data2 = "Data for tab 2"
    widget.addTab(tab2, description="Tab 2", data=data2)

    tab_inserted = QWidget()
    data_inserted = "Data for inserted tab"
    index_inserted = widget.insertTab(1, tab_inserted, data_inserted, description="Inserted Tab")
    assert index_inserted == 1
    assert len(widget._tab_data) == 3
    assert widget.tabData(index_inserted) == data_inserted
    assert widget.tabData(0) == data1
    assert widget.tabData(2) == data2


def test_remove_tab(data_tab_widget: DataTabWidget):
    """Test removing a tab and verifying data consistency."""
    widget = data_tab_widget
    tabs = []
    for i in range(3):
        tab = QWidget()
        data = f"Data for tab {i}"
        widget.addTab(tab, description=f"Tab {i}", data=data)
        tabs.append((tab, data))

    widget.removeTab(1)
    assert len(widget._tab_data) == 2
    assert widget.tabData(0) == "Data for tab 0"
    assert widget.tabData(1) == "Data for tab 2"
    assert widget.tabData(2) is None


def test_clear_tab_data(data_tab_widget: DataTabWidget):
    """Test clearing tab data."""
    widget = data_tab_widget
    widget.addTab(QWidget(), description="Tab 1", data="Data 1")
    widget.addTab(QWidget(), description="Tab 2", data="Data 2")
    assert len(widget._tab_data) == 2
    widget.clearTabData()
    assert len(widget._tab_data) == 0
    assert widget.count() == 2
    with pytest.raises(KeyError):
        widget.tabData(0)


def test_get_current_tab_data(data_tab_widget: DataTabWidget):
    """Test retrieving data of the current tab."""
    widget = data_tab_widget
    widget.addTab(QWidget(), description="Tab 1", data="Data 1")
    widget.addTab(QWidget(), description="Tab 2", data="Data 2")
    widget.setCurrentIndex(1)
    assert widget.getCurrentTabData() == "Data 2"


def test_get_all_tab_data(data_tab_widget: DataTabWidget):
    """Test retrieving all tab data."""
    widget = data_tab_widget
    widget.addTab(QWidget(), description="Tab 1", data="Data 1")
    widget.addTab(QWidget(), description="Tab 2", data="Data 2")
    all_data = widget.getAllTabData()
    assert len(all_data) == 2
    assert all_data[widget.widget(0)] == "Data 1"
    assert all_data[widget.widget(1)] == "Data 2"


def test_get_data_for_tab(data_tab_widget: DataTabWidget):
    """Test retrieving data for a specific tab widget."""
    widget = data_tab_widget
    tab1 = QWidget()
    tab2 = QWidget()
    widget.addTab(tab1, description="Tab 1", data="Data 1")
    widget.addTab(tab2, description="Tab 2", data="Data 2")
    assert widget.get_data_for_tab(tab1) == "Data 1"
    assert widget.get_data_for_tab(tab2) == "Data 2"


def test_add_tab_with_position_and_focus(data_tab_widget: DataTabWidget):
    """Test adding a tab at a specific position with focus."""
    widget = data_tab_widget
    widget.addTab(QWidget(), description="Tab 1", data="Data 1")
    widget.addTab(QWidget(), description="Tab 2", data="Data 2")
    new_tab = QWidget()
    widget.add_tab(new_tab, icon=None, description="New Tab", data="New Data", position=1, focus=True)
    assert len(widget._tab_data) == 3
    assert widget.currentIndex() == 1
    assert widget.tabData(1) == "New Data"


def test_remove_all_tabs(data_tab_widget: DataTabWidget):
    """Test removing all tabs and data."""
    widget = data_tab_widget
    widget.addTab(QWidget(), description="Tab 1", data="Data 1")
    widget.addTab(QWidget(), description="Tab 2", data="Data 2")
    widget.clear()
    assert widget.count() == 0
    assert len(widget._tab_data) == 0


def test_add_tab_without_data(data_tab_widget: DataTabWidget):
    """Test adding a tab without associated data."""
    widget = data_tab_widget
    tab = QWidget()
    index = widget.addTab(tab, description="No Data Tab")
    assert len(widget._tab_data) == 0
    with pytest.raises(KeyError):
        widget.tabData(index)


def test_insert_tab_without_data(data_tab_widget: DataTabWidget):
    """Test inserting a tab without associated data."""
    widget = data_tab_widget
    tab = QWidget()
    index = widget.insertTab(0, tab, data=None, description="Inserted No Data Tab")
    assert len(widget._tab_data) == 0
    with pytest.raises(KeyError):
        widget.tabData(index)


def test_remove_tab_updates_indices(data_tab_widget: DataTabWidget):
    """Test that removing a tab updates the indices correctly."""
    widget = data_tab_widget
    for i in range(5):
        widget.addTab(QWidget(), description=f"Tab {i}", data=f"Data {i}")
    widget.removeTab(2)
    assert len(widget._tab_data) == 4
    assert widget.tabData(2) == "Data 3"
    assert widget.tabData(3) == "Data 4"


def test_insert_tab_updates_indices(data_tab_widget: DataTabWidget):
    """Test that inserting a tab updates the indices correctly."""
    widget = data_tab_widget
    for i in range(3):
        widget.addTab(QWidget(), description=f"Tab {i}", data=f"Data {i}")
    widget.insertTab(1, QWidget(), data="Inserted Data", description="Inserted Tab")
    assert len(widget._tab_data) == 4
    assert widget.tabData(1) == "Inserted Data"
    assert widget.tabData(2) == "Data 1"


def test_set_tab_data(data_tab_widget: DataTabWidget):
    """Test setting tab data after creation."""
    widget = data_tab_widget
    tab = QWidget()
    index = widget.addTab(tab, description="Tab", data="Initial Data")
    widget.setTabData(tab, "Updated Data")
    assert widget.tabData(index) == "Updated Data"


def test_invalid_index_access(data_tab_widget: DataTabWidget):
    """Test accessing data with an invalid index."""
    widget = data_tab_widget
    widget.addTab(QWidget(), description="Tab", data="Data")
    with pytest.raises(KeyError):
        widget.get_data_for_tab(QWidget())


def test_clear_tabs_and_data(data_tab_widget: DataTabWidget):
    """Test clearing all tabs and data."""
    widget = data_tab_widget
    for i in range(3):
        widget.addTab(QWidget(), description=f"Tab {i}", data=f"Data {i}")
    widget.clear()
    widget.clearTabData()
    assert widget.count() == 0
    assert len(widget._tab_data) == 0
