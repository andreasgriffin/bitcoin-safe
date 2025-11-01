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

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class HeightSyncedWidget(QWidget):
    def __init__(self, sync_on_resize=False, parent=None) -> None:
        """A QWidget whose minimum height will be kept in sync with any registered peer
        widgets."""
        super().__init__(parent)
        self.sync_on_resize = sync_on_resize
        self._peers: list[HeightSyncedWidget] = []
        # always watch for size-hint changes or resizes on ourselves
        self.installEventFilter(self)

    def syncWith(self, *widgets: HeightSyncedWidget) -> None:
        """Register one or more other HeightSyncedWidget instances to keep height in
        lock-step with."""
        for w in widgets:
            if w is not self and w not in self._peers:
                self._peers.append(w)
                # each peer should also listen to *our* changes
                w._peers.append(self)
                w.installEventFilter(self)
                self.installEventFilter(w)
        # initial sync
        self.syncHeights()

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        """Whenever *we* or *any* peer gets a new size hint or is resized, recalculate
        the max height and apply it."""
        if not a1:
            return super().eventFilter(a0, a1)
        et = a1.type()
        events = [
            QEvent.Type.LayoutRequest,
        ]
        if self.sync_on_resize:
            events.append(QEvent.Type.Resize)
        if et in events:
            self.syncHeights()
        return super().eventFilter(a0, a1)

    def syncHeights(self) -> None:
        # include ourselves + all peers
        """SyncHeights."""
        group = [self] + self._peers
        # compute the max preferred height
        max_h = max(w.sizeHint().height() for w in group)
        if max_h < 0:
            return
        # apply as minimumHeight so they stay at least that tall
        for w in group:
            w.setMinimumHeight(max_h)


if __name__ == "__main__":

    def make_header(text, peers=None, button=False):
        """Make header."""
        hdr = HeightSyncedWidget()
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(5, 2, 5, 2)
        lay.addWidget(QLabel(text))
        lay.addStretch()
        if button:
            lay.addWidget(QPushButton("Action"))
        return hdr

    def main():
        """Main."""
        app = QApplication([])

        # 1) create the two headers, linking them together
        left_hdr = make_header("Left Pane", button=True)
        right_hdr = make_header("Right Pane", peers=[left_hdr])

        # 2) make two pane-widgets, each with header + content stacked
        left_pane = QWidget()
        lv = QVBoxLayout(left_pane)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(left_hdr)
        lv.addWidget(QTextEdit("…left content…"))

        right_pane = QWidget()
        rv = QVBoxLayout(right_pane)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(right_hdr)
        rv.addWidget(QTextEdit("…right content…"))

        # 3) put those two panes into a single horizontal splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_pane)
        splitter.addWidget(right_pane)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([400, 400])  # initial width split

        # 4) show in a window
        win = QWidget()
        ml = QHBoxLayout(win)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(splitter)
        win.resize(800, 600)
        win.show()
        app.exec()

    main()
