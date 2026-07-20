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
