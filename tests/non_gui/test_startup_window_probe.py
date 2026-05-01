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

from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from bitcoin_safe.gui.qt.startup_window_probe import StartupWindowProbe


class RootWindow(QWidget):
    pass


class DetailsPanel(QWidget):
    pass


def test_format_widget_includes_parent_chain(qapp: QApplication) -> None:
    root = RootWindow()
    root.setWindowTitle("Bitcoin Safe")

    panel = DetailsPanel(root)
    panel.setObjectName("details_panel")

    button = QPushButton("Donate", panel)
    button.setObjectName("donate_button")

    assert StartupWindowProbe._format_widget(button) == (
        "RootWindow['Bitcoin Safe'] > "
        "DetailsPanel['#details_panel'] > "
        "QPushButton['#donate_button' | 'Donate']"
    )
