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
from typing import List, Optional, Set

from PyQt6.QtWidgets import QTabWidget, QWidget

logger = logging.getLogger(__name__)


class BlockChangesSignals:
    """
    Blocks signals from all recursive widgets that are in the layout

    This takes a long time, so do not use it on widgets with many subwidgets
    """

    def __init__(self, widgets: List[QWidget]) -> None:
        self.widgets: List[QWidget] = widgets
        self.all_widgets: Optional[Set[QWidget]] = None

    def fill_widget_list(self) -> Set[QWidget]:
        res = self.collect_all_widgets()
        self.all_widgets = res
        return res

    def _collect_sub_widget(self, widget: QWidget) -> List[QWidget]:
        """Recursively collect all widgets in a given layout."""
        widgets = []
        if isinstance(widget, QTabWidget):
            widgets += self._collect_widgets_in_tab(widget)
        else:
            for child in widget.findChildren(QWidget):
                widgets.append(child)
                widgets += self._collect_sub_widget(child)
        return widgets

    def _collect_widgets_in_tab(self, tab_widget: QTabWidget) -> List[QWidget]:
        """Recursively collect all widgets in a QTabWidget."""
        widgets = []
        for index in range(tab_widget.count()):
            tab_page = tab_widget.widget(index)
            if tab_page and tab_page.layout():
                widgets += self._collect_sub_widget(tab_page)
        return widgets

    def collect_all_widgets(self) -> Set[QWidget]:
        l = []
        for widget in self.widgets:
            l += self._collect_sub_widget(widget)
            if isinstance(widget, QTabWidget):
                l += self._collect_widgets_in_tab(widget)
        return set(l)

    def __enter__(self) -> None:
        if self.all_widgets is None:
            self.all_widgets = self.fill_widget_list()

        # remove the already blocked ones
        self.all_widgets = set([w for w in self.all_widgets if not w.signalsBlocked()])

        for widget in self.all_widgets:
            widget.blockSignals(True)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.all_widgets is None:
            self.all_widgets = self.fill_widget_list()

        for widget in self.all_widgets:
            widget.blockSignals(False)
