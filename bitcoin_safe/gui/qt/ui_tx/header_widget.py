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
import platform

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.ui_tx.height_synced_widget import HeightSyncedWidget
from bitcoin_safe.gui.qt.util import HLine, set_no_margins, svg_tools

logger = logging.getLogger(__name__)


class HeaderWidget(HeightSyncedWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)

        self._layout = QVBoxLayout(self)
        if platform.system().lower() == "darwin":
            self._layout.setSpacing(0)
        set_no_margins(self._layout)

        self.h_laylout = QHBoxLayout()
        if platform.system().lower() == "darwin":
            self.h_laylout.setSpacing(max(self.h_laylout.spacing(), 7))
        self.label_title = QLabel()
        self.icon = QLabel()
        self.icon_name = ""
        self.h_laylout.addWidget(self.icon)
        self.h_laylout.addWidget(self.label_title)
        self.h_laylout.addStretch()
        self._layout.addLayout(self.h_laylout)
        self._layout.addWidget(HLine())

    def set_icon(self, icon_name: str):
        """Set icon."""
        self.icon_name = icon_name
        self.icon.setPixmap(svg_tools.get_pixmap(icon_name, size=(16, 16)))
