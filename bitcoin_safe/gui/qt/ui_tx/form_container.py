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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QWidget

logger = logging.getLogger(__name__)


class GridFormLayout(QGridLayout):
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)

    def _get_max_row(self) -> int:
        # Compute next available row by scanning existing items
        """Get max row."""
        max_row = -1
        for idx in range(self.count()):
            r, _, _, _ = self.getItemPosition(idx)
            if r is not None and r > max_row:
                max_row = r
        return max_row + 1

    def addRow(
        self,
        label: QWidget | None,
        field: QWidget | None,
        label_alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        field_alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
    ) -> None:
        """Adds a label/field pair at the next free row, with optional alignment for
        each cell."""
        row = self._get_max_row()

        # add the label in column 0, with its alignment
        if label is not None:
            self.addWidget(label, row, 0, 1, 1, label_alignment)

        # add the field in column 1, with its alignment
        if field is not None:
            self.addWidget(field, row, 1, 1, 1, field_alignment)

    def set_row_visibility_of_widget(self, widget: QWidget, visible: bool) -> None:
        """Shows or hides all widgets in the row containing `widget`."""
        idx = self.indexOf(widget)
        if idx < 0:
            return  # widget not in layout

        # Fetch the row index of the item
        row, _, _, _ = self.getItemPosition(idx)
        if row is None:
            return

        # Toggle visibility on every column in that row
        for col in range(self.columnCount()):
            item = self.itemAtPosition(row, col)
            if item and (w := item.widget()):
                w.setVisible(visible)

        # Refresh layout on the parent widget
        parent = self.parentWidget()
        if parent is not None:
            if layout := parent.layout():
                layout.invalidate()
            parent.adjustSize()
