#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
#

from __future__ import annotations

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QTreeView, QWidget

from .util import is_theme_change_event


class ColorCorrectedTreeView(QTreeView):
    """QTreeView variant that fixes selected item text colors for Windows styles."""

    _SELECTION_STYLE_MARKER_START = "/* colorcorrectedtreeview-selection-override:start */"
    _SELECTION_STYLE_MARKER_END = "/* colorcorrectedtreeview-selection-override:end */"
    _WINDOWS_STYLE_NAMES = frozenset({"windows", "windowsvista", "windows11", "qwindows11style"})

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setObjectName(f"{self.__class__.__name__}.{id(self)}")
        self._refresh_selection_style_sheet()

    def changeEvent(self, event: QEvent | None) -> None:
        """React to palette and style changes that affect selection colors."""
        super().changeEvent(event)
        if is_theme_change_event(event, include_style_change=True):
            self._refresh_selection_style_sheet()

    def setStyleSheet(self, styleSheet: str | None) -> None:
        """Keep the managed selection override when other code updates the stylesheet."""
        base_style_sheet = self._strip_selection_style_override(styleSheet or "")
        super().setStyleSheet(self._compose_selection_style_sheet(base_style_sheet))

    def _needs_selection_text_override(self) -> bool:
        """Return whether the current Qt style needs an explicit selection text override."""
        style_names: set[str] = set()
        instance_style = None
        try:
            # this is needed, in case self.style().objectName().lower()  == ""
            instance_style = QApplication.instance().style()  # type: ignore
        except Exception:
            pass
        for style in [self.style(), instance_style]:
            if not style:
                continue
            style_names.add(style.objectName().lower())
            if meta_object := style.metaObject():
                style_names.add(meta_object.className().lower())

        result = any(
            windows_style_name in style_name
            for style_name in style_names
            for windows_style_name in self._WINDOWS_STYLE_NAMES
        )
        return result

    def _selection_style_override(self) -> str:
        """Return the guarded selection-color override stylesheet."""
        palette = self.palette()
        selection_color = palette.color(palette.ColorRole.HighlightedText).name()
        tree_view_selector = f'QTreeView[objectName="{self.objectName()}"]'
        return f"""
{self._SELECTION_STYLE_MARKER_START}
{tree_view_selector}::item:hover {{
    color: {selection_color};
}}
{tree_view_selector}::item:selected {{
    color: {selection_color};
}}
{tree_view_selector}::item:selected:hover {{
    color: {selection_color};
}}
{tree_view_selector}::item:selected:active {{
    color: {selection_color};
}}
{tree_view_selector}::item:selected:!active {{
    color: {selection_color};
}}
{self._SELECTION_STYLE_MARKER_END}
""".strip()

    def _strip_selection_style_override(self, style_sheet: str) -> str:
        """Remove the managed selection override block from a stylesheet."""
        if self._SELECTION_STYLE_MARKER_START not in style_sheet:
            return style_sheet

        prefix, _, rest = style_sheet.partition(self._SELECTION_STYLE_MARKER_START)
        _, _, suffix = rest.partition(self._SELECTION_STYLE_MARKER_END)
        return f"{prefix.rstrip()}\n{suffix.lstrip()}".strip()

    def _compose_selection_style_sheet(self, base_style_sheet: str) -> str:
        """Append the managed selection override when the current style needs it."""
        if not self._needs_selection_text_override():
            return base_style_sheet.strip()

        return "\n\n".join(
            style for style in [base_style_sheet.strip(), self._selection_style_override()] if style
        )

    def _refresh_selection_style_sheet(self) -> None:
        """Rebuild the managed selection override using the current palette and style."""
        current_style_sheet = super().styleSheet()
        base_style_sheet = self._strip_selection_style_override(current_style_sheet)
        new_style_sheet = self._compose_selection_style_sheet(base_style_sheet)
        if new_style_sheet != current_style_sheet:
            super().setStyleSheet(new_style_sheet)
