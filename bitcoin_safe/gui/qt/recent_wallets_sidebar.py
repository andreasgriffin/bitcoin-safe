#
# Bitcoin Safe
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

import logging
from collections.abc import Iterable
from functools import partial
from pathlib import Path
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.util_os import show_file_in_explorer
from PyQt6.QtCore import QPoint, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.sidebar.search_sidebar_tree import SearchSidebarTree
from bitcoin_safe.gui.qt.sidebar.search_tree_view import ResultItem, SearchTreeView
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode, SidebarTree
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu

logger = logging.getLogger(__name__)


class WalletSearchView(SearchTreeView):
    def __init__(self, wallet_picker: RecentlyOpenedWalletsGroup, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        self.wallet_picker = wallet_picker
        super().__init__(self.do_search, parent=parent, on_click=self._on_result_clicked)

    def _on_result_clicked(self, result_item: ResultItem) -> None:
        """Open the wallet associated with the clicked result."""
        if isinstance(result_item.obj, str):
            self.wallet_picker.open_wallet_path(result_item.obj)

    def do_search(self, search_text: str) -> ResultItem:
        """Build a grouped search model for matching wallet names."""
        root = ResultItem("")
        normalized = search_text.strip().lower()
        if not normalized:
            return root

        for section_title, paths in (
            (self.wallet_picker.recent_section_title(), self.wallet_picker.recent_wallet_paths),
            (self.wallet_picker.all_wallets_section_title(), self.wallet_picker.all_wallet_paths),
        ):
            section_item: ResultItem | None = None
            for file_path in paths:
                display_name = self.wallet_picker.display_name(file_path)
                if normalized not in display_name.lower():
                    continue
                if section_item is None:
                    section_item = ResultItem(section_title, parent=root)
                ResultItem(
                    display_name,
                    parent=section_item,
                    icon=self.wallet_picker.wallet_icon,
                    obj=file_path,
                )

        return root


class RecentlyOpenedWalletsGroup(QWidget):
    signal_file_path_clicked = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        signal_open_wallet: SignalProtocol[[str]],
        signal_recently_open_wallet_changed: SignalProtocol[[list[str]]],
        wallet_dir: Path | str,
        hide_extension: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.signal_recently_open_wallet_changed = signal_recently_open_wallet_changed
        self.signal_open_wallet = signal_open_wallet
        self.wallet_dir = Path(wallet_dir)
        self.hide_extension = hide_extension
        self.wallet_icon = svg_tools.get_QIcon("bi--wallet2.svg")
        self.recent_wallet_paths: list[str] = []
        self.all_wallet_paths: list[str] = []
        self._rebuilding = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.sidebar_tree = SidebarTree[str](parent=self, show_stack=False)
        self.search_view = WalletSearchView(wallet_picker=self, parent=self.sidebar_tree)
        self.search_sidebar_tree = SearchSidebarTree(
            sidebar_tree=self.sidebar_tree,
            search_view=self.search_view,
            parent=self,
        )
        self._layout.addWidget(self.search_sidebar_tree)

        self.recent_wallets_node = SidebarNode[str](
            title=self.recent_section_title(),
            data="recent-wallets",
            widget=None,
            icon=None,
            closable=False,
            collapsible=True,
            initially_collapsed=False,
            show_expand_button=True,
            parent=self.sidebar_tree,
        )
        self.all_wallets_node = SidebarNode[str](
            title=self.all_wallets_section_title(),
            data="all-wallets",
            widget=None,
            icon=None,
            closable=False,
            collapsible=True,
            initially_collapsed=False,
            show_expand_button=True,
            parent=self.sidebar_tree,
        )
        self.sidebar_tree.root.addChildNode(self.recent_wallets_node, focus=False)
        self.sidebar_tree.root.addChildNode(self.all_wallets_node, focus=False)

        self.signal_recently_open_wallet_changed.connect(self.refresh_wallets)
        self.signal_file_path_clicked.connect(self.signal_open_wallet)
        self.sidebar_tree.nodeSelected.connect(self._on_sidebar_nodeSelected)
        self.sidebar_tree.nodeContextMenuRequested.connect(self._on_context_menu_requested)

        self.refresh_wallets([])

    def recent_section_title(self) -> str:
        """Return the localized recent section title."""
        return self.tr("RECENT WALLETS")

    def all_wallets_section_title(self) -> str:
        """Return the localized all-wallets section title."""
        return self.tr("ALL WALLETS")

    def display_name(self, file_path: str) -> str:
        """Return the wallet name shown in the list."""
        path = Path(file_path)
        return path.stem if self.hide_extension else path.name

    def open_wallet_path(self, file_path: str) -> None:
        """Emit the selected wallet path."""
        self.signal_file_path_clicked.emit(file_path)

    def refresh_wallets(self, recent_wallet_paths: Iterable[str]) -> None:
        """Refresh both wallet sections from recents and wallet_dir."""
        self._rebuilding = True
        try:
            self.recent_wallet_paths = [
                str(Path(file_path))
                for file_path in reversed(list(recent_wallet_paths))
                if Path(file_path).exists() and Path(file_path).suffix == ".wallet"
            ]
            self.all_wallet_paths = [
                str(path)
                for path in sorted(
                    (path for path in self.wallet_dir.glob("*.wallet") if path.is_file()),
                    key=lambda path: self.display_name(str(path)).lower(),
                )
            ]

            self.recent_wallets_node.setTitle(self.recent_section_title())
            self.all_wallets_node.setTitle(self.all_wallets_section_title())

            self._rebuild_section(self.recent_wallets_node, self.recent_wallet_paths)
            self._rebuild_section(self.all_wallets_node, self.all_wallet_paths)
            self._deselect_all()
        finally:
            self._rebuilding = False

    def _rebuild_section(self, section_node: SidebarNode[str], file_paths: Iterable[str]) -> None:
        """Replace the wallet rows inside a section."""
        section_node.clearChildren()
        for file_path in file_paths:
            child_node = self._make_wallet_node(file_path)
            section_node.addChildNode(child_node, focus=False)
        section_node.setVisible(bool(section_node.child_nodes))

    def _deselect_all(self):
        for section in [self.recent_wallets_node, self.all_wallets_node]:
            for child in section.child_nodes:
                child.header_row.set_selected(False)

    def _make_wallet_node(self, file_path: str) -> SidebarNode[str]:
        """Create a wallet leaf node with a hidden page to keep selection behavior."""
        return SidebarNode[str](
            title=self.display_name(file_path),
            data=file_path,
            widget=QWidget(self.sidebar_tree.stack),
            icon=self.wallet_icon,
            collapsible=False,
            parent=self.sidebar_tree,
        )

    def _on_sidebar_nodeSelected(self, node: object) -> None:
        """Open a wallet when a wallet row becomes current."""
        if not isinstance(node, SidebarNode):
            return
        if self._rebuilding:
            return
        file_path = node.data
        if not isinstance(file_path, str) or file_path in {"recent-wallets", "all-wallets"}:
            return
        self.open_wallet_path(file_path)

    def _on_context_menu_requested(self, node: object, position: QPoint) -> None:
        """Show the wallet reveal action for wallet rows."""
        if not isinstance(node, SidebarNode):
            return
        file_path = node.data
        if not isinstance(file_path, str) or file_path in {"recent-wallets", "all-wallets"}:
            return

        menu = Menu()
        menu.add_action(
            self.tr("Reveal in file explorer"),
            slot=partial(show_file_in_explorer, filename=Path(file_path)),
        )
        menu.exec(position)
