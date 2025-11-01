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
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode, SidebarTree
from bitcoin_safe.gui.qt.util import svg_tools

logger = logging.getLogger(__name__)


class LoadingWalletTab(QWidget):
    def __init__(self, tabs: SidebarTree, name: str, focus=True) -> None:
        """Initialize instance."""
        super().__init__(tabs)
        self.tabs = tabs
        self.name = name
        self.focus = focus

        # Create a QWidget to serve as a container for the QLabel
        self._layout = QVBoxLayout(self)  # Setting the layout directly

        # Create and configure QLabel
        self.emptyLabel = QLabel(self.tr("Loading, please wait..."), self)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.emptyLabel.setStyleSheet("font-size: 16pt;")  # Adjust the font size as needed

        # Use spacers to push the QLabel to the center
        spacerTop = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        spacerBottom = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        # Add spacers and label to the layout
        self._layout.addItem(spacerTop)
        self._layout.addWidget(self.emptyLabel)
        self._layout.addItem(spacerBottom)

    def __enter__(self) -> None:
        """Enter context manager."""
        self.tabs.root.addChildNode(
            SidebarNode(
                icon=svg_tools.get_QIcon("status_waiting.svg"),
                title=self.name,
                data=self,
                widget=self,
            ),
            focus=self.focus,
        )
        QApplication.processEvents()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Exit context manager."""
        if node := self.tabs.root.findNodeByWidget(self):
            node.removeNode()
