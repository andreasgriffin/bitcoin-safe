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

from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.gui.qt.util import svg_tools


def test_icon_label_defaults_to_icon_left(qtbot: QtBot) -> None:
    label = IconLabel("Default")
    label.set_icon(svg_tools.get_QIcon("checkmark.svg"))
    qtbot.addWidget(label)

    layout = label.layout()

    assert layout is not None
    assert layout.itemAt(0).widget() == label.icon_label
    assert layout.itemAt(1).widget() == label.textLabel


def test_icon_label_can_place_icon_on_right(qtbot: QtBot) -> None:
    label = IconLabel("Status", icon_on_right=True)
    label.set_icon(svg_tools.get_QIcon("checkmark.svg"))
    qtbot.addWidget(label)

    layout = label.layout()

    assert layout is not None
    assert layout.itemAt(0).widget() == label.textLabel
    assert layout.itemAt(1).widget() == label.icon_label
