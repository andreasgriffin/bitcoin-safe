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

from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode, SidebarTree


def test_closing_wallet_selects_page_from_collapsed_wallet(qapp: QApplication) -> None:
    del qapp
    host = QWidget()
    layout = QVBoxLayout(host)
    tree = SidebarTree[str]()
    layout.addWidget(tree)
    host.show()

    first_wallet = SidebarNode(data="first-wallet", title="First wallet")
    first_page = SidebarNode(data="first-page", title="First page", widget=QWidget())
    first_wallet.addChildNode(first_page, focus=False)

    second_wallet = SidebarNode(data="second-wallet", title="Second wallet")
    second_page = SidebarNode(data="second-page", title="Second page", widget=QWidget())
    second_wallet.addChildNode(second_page, focus=False)

    tree.root.addChildNode(first_wallet, focus=False)
    tree.root.addChildNode(second_wallet, focus=False)

    first_page.select()
    first_wallet.set_collapsed(True)
    second_page.select()
    QApplication.processEvents()

    second_wallet.removeNode()
    QApplication.processEvents()

    assert first_wallet.expanded
    assert tree.currentNode() is first_page
    assert tree.currentWidget() is first_page.widget


def test_removed_subtree_is_purged_from_selection_history(qapp: QApplication) -> None:
    del qapp
    host = QWidget()
    layout = QVBoxLayout(host)
    tree = SidebarTree[str]()
    layout.addWidget(tree)
    host.show()

    kept_wallet = SidebarNode(data="kept-wallet", title="Kept wallet")
    kept_page = SidebarNode(data="kept-page", title="Kept page", widget=QWidget())
    kept_wallet.addChildNode(kept_page, focus=False)

    removed_wallet = SidebarNode(data="removed-wallet", title="Removed wallet")
    removed_page = SidebarNode(data="removed-page", title="Removed page", widget=QWidget())
    removed_wallet.addChildNode(removed_page, focus=False)

    tree.root.addChildNode(kept_wallet, focus=False)
    tree.root.addChildNode(removed_wallet, focus=False)

    kept_page.select()
    removed_page.select()
    assert tree._selection_history[-1] is removed_page

    removed_wallet.removeNode()
    QApplication.processEvents()

    assert all(not n._is_within(removed_wallet) for n in tree._selection_history)
    assert tree._selection_history == [kept_page]
    assert tree._navigation_index == 0
    assert tree._navigate_history(step=-1) is False


def _make_tree() -> SidebarTree[str]:
    # Build the tree unshown: nodes added to an already-visible tree get hidden by Qt's setParent().
    return SidebarTree[str]()


def _page(title: str) -> SidebarNode[str]:
    return SidebarNode(data=title, title=title, widget=QWidget())


def test_removing_selected_node_restores_previous_selection_not_stack_neighbor(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()
    page_a, page_b, page_c = _page("A"), _page("B"), _page("C")
    for page in (page_a, page_b, page_c):
        tree.root.addChildNode(page, focus=False)

    page_a.select()
    page_c.select()
    selected_pages: list[SidebarNode[str]] = []
    tree.currentChanged.connect(selected_pages.append)

    tree.show()

    page_c.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is page_a
    assert tree.currentWidget() is page_a.widget
    assert selected_pages == [page_a]


def test_removing_subtree_with_selected_page_restores_page_outside_subtree(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()

    wallet_a = SidebarNode(data="wallet-a", title="Wallet A")
    wallet_a_pages = [_page("A1"), _page("A2")]
    for page in wallet_a_pages:
        wallet_a.addChildNode(page, focus=False)

    wallet_b = SidebarNode(data="wallet-b", title="Wallet B")
    wallet_b_pages = [_page("B1"), _page("B2")]
    for page in wallet_b_pages:
        wallet_b.addChildNode(page, focus=False)

    tree.root.addChildNode(wallet_a, focus=False)
    tree.root.addChildNode(wallet_b, focus=False)

    wallet_a_pages[0].select()
    wallet_b_pages[0].select()
    wallet_b_pages[1].select()

    tree.show()

    wallet_b.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is wallet_a_pages[0]
    assert tree.currentWidget() is wallet_a_pages[0].widget
    assert all(not n._is_within(wallet_b) for n in tree._selection_history)
    assert tree._selection_history == [wallet_a_pages[0]]


def test_removing_unselected_node_keeps_selection(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()
    page_a, page_b = _page("A"), _page("B")
    tree.root.addChildNode(page_a, focus=False)
    tree.root.addChildNode(page_b, focus=False)

    page_a.select()
    tree.show()
    page_b.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is page_a
    assert tree.currentWidget() is page_a.widget


def test_removing_selected_node_without_history_selects_surviving_page(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()
    page_a, page_b = _page("A"), _page("B")
    tree.root.addChildNode(page_a, focus=False)
    tree.root.addChildNode(page_b, focus=False)

    page_b.select()
    tree._selection_history.clear()
    tree._navigation_index = -1
    tree._current_node = None

    tree.show()

    page_b.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is page_a
    assert tree.currentWidget() is page_a.widget


def test_removing_last_selected_page_leaves_selection_empty(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()
    page = _page("only")
    tree.root.addChildNode(page, focus=False)

    page.select()
    tree.show()
    page.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is None
    assert tree._selection_history == []
    assert tree._navigation_index == -1


def test_navigation_history_skips_removed_node_after_selected_removal(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()
    page_a, page_b, page_c = _page("A"), _page("B"), _page("C")
    for page in (page_a, page_b, page_c):
        tree.root.addChildNode(page, focus=False)

    page_a.select()
    page_b.select()
    page_c.select()

    tree.show()

    page_c.removeNode()
    QApplication.processEvents()

    assert tree._selection_history == [page_a, page_b]
    assert tree.currentNode() is page_b

    assert tree.navigate_history_backward() is True
    assert tree.currentNode() is page_a
    assert tree.navigate_history_forward() is True
    assert tree.currentNode() is page_b
    assert tree.navigate_history_forward() is False
    assert all(n is not page_c for n in tree._selection_history)


def test_reinserting_explicitly_hidden_node_keeps_it_hidden(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()
    tree.show()
    node = _page("hidden")
    node.hide()
    tree.root.addChildNode(node, focus=False)
    assert node.isHidden()

    tree.root.removeChildNode(node)
    tree.root.addChildNode(node, focus=False)
    assert node.isHidden()


def test_removing_selected_node_restores_last_used_page_from_collapsed_groups(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()

    wallet_b = SidebarNode(data="wallet-b", title="Wallet B")
    page_b = _page("B")
    wallet_b.addChildNode(page_b, focus=False)

    wallet_a = SidebarNode(data="wallet-a", title="Wallet A")
    page_a = _page("A")
    wallet_a.addChildNode(page_a, focus=False)

    wallet_c = SidebarNode(data="wallet-c", title="Wallet C")
    page_c = _page("C")
    wallet_c.addChildNode(page_c, focus=False)

    tree.root.addChildNode(wallet_b, focus=False)
    tree.root.addChildNode(wallet_a, focus=False)
    tree.root.addChildNode(wallet_c, focus=False)

    page_a.select()
    page_b.select()
    page_c.select()

    tree.show()

    wallet_a.set_collapsed(True)
    wallet_b.set_collapsed(True)
    assert not wallet_a.expanded
    assert not wallet_b.expanded

    wallet_c.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is page_b
    assert tree.currentWidget() is page_b.widget
    assert wallet_b.expanded is True
    assert wallet_a.expanded is False
    assert all(not n._is_within(wallet_c) for n in tree._selection_history)
    assert page_b in tree._selection_history
    assert page_a in tree._selection_history


def test_explicitly_hidden_page_is_not_restored_from_history(qapp: QApplication) -> None:
    del qapp
    tree = _make_tree()
    page_a, page_b, page_c = _page("A"), _page("B"), _page("C")
    for page in (page_a, page_b, page_c):
        tree.root.addChildNode(page, focus=False)

    page_a.select()
    page_b.select()
    page_c.select()
    tree.show()

    page_b.hide()
    page_c.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is page_a
    assert all(n is not page_b for n in tree._selection_history)
