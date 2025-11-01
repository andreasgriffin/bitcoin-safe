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
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.sidebar.search_tree_view import (
    SearchTreeView,
    demo_do_search,
    demo_on_click,
)
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode, SidebarTree

logger = logging.getLogger(__name__)


class SearchSidebarTree(QWidget):
    """Layout inside the SidebarTree's left column: [ SearchTreeView (search field +
    results) ] [ Sidebar scroll area (hidden when searching) ]

    The right content stack of SidebarTree remains untouched.
    """

    def __init__(self, sidebar_tree: SidebarTree, search_view: SearchTreeView, parent: QWidget | None = None):
        """Initialize instance."""
        super().__init__(parent)
        self.sidebar_tree = sidebar_tree
        self.search_view = search_view

        # Host the existing SidebarTree in this wrapper
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar_tree)

        # Insert the search view above the sidebar list inside the left column
        self.sidebar_tree.left_vbox.insertWidget(1, self.search_view)

        # Toggle only the left list visibility (the search field stays)
        def _toggle_left_list(active: bool) -> None:
            """Toggle left list."""
            self.sidebar_tree.scroll_area.setVisible(not active)

        self.search_view.searchActiveChanged.connect(_toggle_left_list)
        self.sidebar_tree.scroll_area.setVisible(not self.search_view.isSearchActive())


# --------------------------------------------------------------------
# DEMO (assumes SidebarTree / SidebarNode are available in scope)
# --------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    main = QMainWindow()
    main.setWindowTitle("SearchSidebarTree Demo")

    central = QWidget()
    main.setCentralWidget(central)
    root_layout = QHBoxLayout(central)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    # Build a sample SidebarTree with wallets and tabs
    sidebar = SidebarTree[str]()
    root = SidebarNode[str](title="All Wallets", data="root")
    sidebar.root.addChildNode(root)

    def mk_page(title: str) -> QWidget:
        """Mk page."""
        w = QWidget()
        vl = QVBoxLayout(w)
        lbl = QLabel(f"<h1>{title}</h1>")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.addWidget(lbl)
        return w

    def add_wallet(name: str):
        """Add wallet."""
        wallet = SidebarNode[str](title=name, data=name, icon=QIcon.fromTheme("wallet"))
        for cat in ["History", "Send", "Receive", "Descriptor", "Tools & Services"]:
            page_title = f"{name} - {cat}"
            leaf = SidebarNode[str](title=cat, data=page_title, widget=mk_page(page_title))
            wallet.addChildNode(leaf)
        root.addChildNode(wallet)

    add_wallet("Wallet A")
    add_wallet("Wallet B")

    # Create SearchTreeView (search + results panel)
    search_view = SearchTreeView(
        do_search=demo_do_search,
        on_click=demo_on_click,
    )

    # Stack: SearchTreeView on top, SidebarTree underneath (shown only when not searching)
    wrapper = SearchSidebarTree(sidebar_tree=sidebar, search_view=search_view)

    # Put the wrapper into the window
    root_layout.addWidget(wrapper)

    main.resize(1000, 600)
    main.show()
    sys.exit(app.exec())
