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

import enum

from PyQt6.QtCore import QModelIndex
from PyQt6.QtGui import QStandardItem
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.color_corrected_treeview import ColorCorrectedTreeView
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole, MyTreeView
from bitcoin_safe.signals import Signals


class DummyTreeView(MyTreeView[str]):
    class Columns(MyTreeView.Columns):
        LABEL = enum.auto()

    filter_columns = [Columns.LABEL]
    key_column = Columns.LABEL

    def __init__(self, config: UserConfig) -> None:
        super().__init__(config=config, signals=Signals())
        self.setModel(self.proxy)

    def append_row(self, text: str, key: str, clipboard_data: object | None = None) -> None:
        item = QStandardItem(text)
        item.setData(key, MyItemDataRole.ROLE_KEY)
        if clipboard_data is not None:
            item.setData(clipboard_data, MyItemDataRole.ROLE_CLIPBOARD_DATA)
        self._source_model.appendRow([item])


def _is_hidden(tree_view: DummyTreeView, row: int) -> bool:
    source_index = tree_view._source_model.index(row, tree_view.Columns.LABEL)
    proxy_index = tree_view.proxy.mapFromSource(source_index)
    assert proxy_index.isValid()
    return tree_view.isRowHidden(proxy_index.row(), QModelIndex())


def test_mytreeview_filter_matches_clipboard_content(qtbot: QtBot, test_config: UserConfig) -> None:
    tree_view = DummyTreeView(config=test_config)
    qtbot.addWidget(tree_view)

    tree_view.append_row(text="visible label", key="text")
    tree_view.append_row(text="shown value", key="clipboard", clipboard_data="secret xpub")
    tree_view.append_row(text="amount display", key="numeric", clipboard_data=12345)
    tree_view.append_row(text="plain row", key="plain")

    assert tree_view.filter("visible") == [False, True, True, True]
    assert not _is_hidden(tree_view, 0)

    assert tree_view.filter("secret") == [True, False, True, True]
    assert not _is_hidden(tree_view, 1)

    assert tree_view.filter("12345") == [True, True, False, True]
    assert not _is_hidden(tree_view, 2)

    assert tree_view.filter("plain") == [True, True, True, False]
    assert not _is_hidden(tree_view, 3)


def test_mytreeview_selection_override_not_applied_for_non_windows_style(
    monkeypatch, qtbot: QtBot, test_config: UserConfig
) -> None:
    tree_view = DummyTreeView(config=test_config)
    qtbot.addWidget(tree_view)
    tree_view.setStyleSheet("QTreeView { border: none; }")

    monkeypatch.setattr(tree_view, "_needs_selection_text_override", lambda: False)

    tree_view._refresh_selection_style_sheet()

    assert tree_view.styleSheet() == "QTreeView { border: none; }"


def test_mytreeview_selection_override_applied_for_windows_style(
    monkeypatch, qtbot: QtBot, test_config: UserConfig
) -> None:
    tree_view = DummyTreeView(config=test_config)
    qtbot.addWidget(tree_view)

    monkeypatch.setattr(tree_view, "_needs_selection_text_override", lambda: True)

    tree_view._refresh_selection_style_sheet()

    palette = tree_view.palette()
    selection_color = palette.color(palette.ColorRole.HighlightedText).name()
    selector = f'QTreeView[objectName="{tree_view.objectName()}"]::item:selected'

    assert f"color: {selection_color};" in tree_view.styleSheet()
    assert "background-color:" not in tree_view.styleSheet()
    assert selector in tree_view.styleSheet()
    assert tree_view.objectName().startswith("DummyTreeView.")


def test_colorcorrectedtreeview_keeps_managed_override_when_stylesheet_changes(
    monkeypatch, qtbot: QtBot
) -> None:
    tree_view = ColorCorrectedTreeView()
    qtbot.addWidget(tree_view)

    monkeypatch.setattr(tree_view, "_needs_selection_text_override", lambda: True)

    tree_view.setStyleSheet("QTreeView { border: none; }")

    assert "QTreeView { border: none; }" in tree_view.styleSheet()
    assert f'QTreeView[objectName="{tree_view.objectName()}"]::item:selected' in tree_view.styleSheet()
    assert tree_view.objectName().startswith("ColorCorrectedTreeView.")
