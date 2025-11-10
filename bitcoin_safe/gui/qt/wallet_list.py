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
import os
from collections.abc import Iterable
from functools import partial
from pathlib import Path
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.util_os import show_file_in_explorer
from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QMouseEvent, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ButtonStyleDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index):
        """Paint."""
        button_option = QStyleOptionButton()
        button_option.rect = option.rect.adjusted(0, 0, -1, -1)  # Adjust to fit within drawing bounds
        button_option.text = index.data(Qt.ItemDataRole.DisplayRole)
        button_option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Raised

        if option.state & QStyle.StateFlag.State_Selected:
            button_option.state |= QStyle.StateFlag.State_Sunken
        else:
            button_option.state |= QStyle.StateFlag.State_Raised

        QApplication.style().drawControl(QStyle.ControlElement.CE_PushButton, button_option, painter)  # type: ignore

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        """SizeHint."""
        default_height = max(
            25,
            (QApplication.style() or QStyle()).pixelMetric(QStyle.PixelMetric.PM_DialogButtonsButtonHeight),
        )  # type: ignore
        return QSize(option.rect.width(), default_height)


class ButtonList(QListWidget):
    signal_clicked = cast(SignalProtocol[[QListWidgetItem]], pyqtSignal(QListWidgetItem))

    def __init__(self, *args, **kwargs):
        """Initialize instance."""
        super().__init__(*args, **kwargs)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )  # Disable horizontal scrollbar
        self.setItemDelegate(ButtonStyleDelegate())

    def mousePressEvent(self, e: QMouseEvent | None) -> None:
        """MousePressEvent."""
        if not e:
            return
        if e.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)  # Proceed with base class handling
            item = self.itemAt(e.position().toPoint())
            if item:
                item.setSelected(True)  # Manually set the item as selected
                self.signal_clicked.emit(item)  # Emit the custom signal
        elif e.button() == Qt.MouseButton.RightButton:
            self.handleRightClick(e.position().toPoint())

    def mouseReleaseEvent(self, e: QMouseEvent | None) -> None:
        """MouseReleaseEvent."""
        super().mouseReleaseEvent(e)
        if not e:
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.clearSelection()  # Deselect all items on release

    def handleRightClick(self, position: QPoint):
        """HandleRightClick."""
        item = self.itemAt(position)
        if not item:
            return

        menu = QMenu()
        openFolderAction = QAction(self.tr("Open containing folder"), self)
        openFolderAction.triggered.connect(partial(self.openContainingFolder, item.toolTip()))
        menu.addAction(openFolderAction)
        menu.exec(self.mapToGlobal(position))

    def openContainingFolder(self, filePath: str) -> None:
        """OpenContainingFolder."""
        show_file_in_explorer(Path(filePath))


class WalletList(ButtonList):
    signal_file_path_clicked = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(self, hide_extension=True, *args, **kwargs):
        """Initialize instance."""
        super().__init__(*args, **kwargs)
        self.hide_extension = hide_extension
        self.signal_clicked.connect(self.handleItemClick)

    def set_file_paths(self, file_paths: Iterable[str]):
        """Set file paths."""
        self.clear()
        for file_path in reversed(list(file_paths)):
            name = Path(file_path).stem if self.hide_extension else Path(file_path).name
            item = QListWidgetItem(name)
            item.setToolTip(file_path)  # Set tooltip to show full path on hover
            self.addItem(item)

    def handleItemClick(self, item: QListWidgetItem):
        # Get the full path from the tooltip of the item
        """HandleItemClick."""
        full_path = item.toolTip()
        self.signal_file_path_clicked.emit(full_path)  # Emit the signal with the full path


class RecentlyOpenedWalletsGroup(QGroupBox):
    def __init__(
        self,
        signal_open_wallet: SignalProtocol[[str]],
        signal_recently_open_wallet_changed: SignalProtocol[list[str]],
        hide_extension=True,
    ):
        """Initialize instance."""
        super().__init__()
        self.signal_recently_open_wallet_changed = signal_recently_open_wallet_changed
        self.signal_open_wallet = signal_open_wallet

        self.setTitle(self.tr("Recently Opened Wallets"))
        self._layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.wallet_list = WalletList(hide_extension=hide_extension)
        self._layout.addWidget(self.wallet_list)

        self.set_visibility()

        # signals
        self.signal_recently_open_wallet_changed.connect(self.wallet_list.set_file_paths)
        self.signal_recently_open_wallet_changed.connect(
            self.on_signal_recently_open_wallet_changed
        )  # for visibility
        self.wallet_list.signal_file_path_clicked.connect(self.signal_open_wallet)

    def set_visibility(self):
        """Set visibility."""
        self.setHidden(self.wallet_list.count() == 0)

    def on_signal_recently_open_wallet_changed(self, file_paths: Iterable[str]):
        """On signal recently open wallet changed."""
        self.set_visibility()


if __name__ == "__main__":

    class Demo(QWidget):
        def __init__(self) -> None:
            """Initialize instance."""
            super().__init__()
            layout = QVBoxLayout(self)
            self.walletsWidget = WalletList()
            layout.addWidget(self.walletsWidget)

            # If you only want files and not directories, you can filter the list
            files = [f for f in os.listdir(".") if os.path.isfile(f)]

            # Populate list
            self.walletsWidget.set_file_paths(files)

            # External button to update items
            self.updateButton = QPushButton("Update Items")
            layout.addWidget(self.updateButton)
            self.updateButton.clicked.connect(self.updateItems)

        def updateItems(self) -> None:
            # If you only want files and not directories, you can filter the list
            """UpdateItems."""
            files = [f for f in os.listdir("..") if os.path.isfile(f)]

            # Populate list
            self.walletsWidget.set_file_paths(files)

    def main() -> None:
        """Main."""
        app = QApplication([])
        demo = Demo()
        demo.resize(400, 300)
        demo.show()
        app.exec()

    main()
