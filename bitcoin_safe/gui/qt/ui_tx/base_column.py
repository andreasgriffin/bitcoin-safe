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
# SOFTWARE.

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.ui_tx.header_widget import HeaderWidget
from bitcoin_safe.gui.qt.ui_tx.totals_box import TotalsBox
from bitcoin_safe.gui.qt.util import (
    set_margins,
)

logger = logging.getLogger(__name__)


class BaseColumn(QWidget):
    def __init__(
        self,
        fx: FX,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)

        self._layout = QVBoxLayout(self)

        self.header_widget = HeaderWidget(self)
        self._layout.addWidget(self.header_widget)

        # bottom bar
        self.totals = TotalsBox(fx=fx, network=fx.config.network)
        self._layout.addWidget(self.totals)
        set_margins(self.totals._layout, {Qt.Edge.BottomEdge: 0})

    def updateUi(self) -> None:
        """UpdateUi."""
        pass

    def insert_middle_widget(self, widget: QWidget, **kwargs):
        """Insert middle widget."""
        self._layout.insertWidget(1, widget, **kwargs)

    def is_available(self) -> bool:
        """Is available."""
        return True

    def close(self) -> bool:
        self.totals.close()
        return super().close()
