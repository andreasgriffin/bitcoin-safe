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

from bitcoin_safe_lib.util_os import webopen
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from bitcoin_safe.gui.qt.analyzer_indicator import ElidedLabel
from bitcoin_safe.gui.qt.buttonedit import SquareButton
from bitcoin_safe.gui.qt.util import block_explorer_URL, do_copy, set_no_margins, svg_tools

from ....config import UserConfig


class TxidLabel(QWidget):
    def __init__(
        self,
        config: UserConfig,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.config = config
        self._txid = ""

        layout = QHBoxLayout(self)
        set_no_margins(layout)
        layout.setSpacing(4)

        self.label_txid_title = QLabel(self)
        self.label_txid = ElidedLabel(elide_mode=Qt.TextElideMode.ElideMiddle)
        self.label_txid.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.label_txid.setMinimumWidth(1)
        self.button_copy_txid = SquareButton(svg_tools.get_QIcon("bi--copy.svg"), self)
        self.button_copy_txid.clicked.connect(self.copy_txid)
        self.button_txid_link = SquareButton(svg_tools.get_QIcon("lucide--external-link.svg"), self)
        self.button_txid_link.clicked.connect(self.open_txid_in_block_explorer)

        layout.addWidget(self.label_txid_title)
        layout.addWidget(self.label_txid)
        layout.addWidget(self.button_copy_txid)
        layout.addWidget(self.button_txid_link)

        self.updateUi()

    def set_txid(self, txid: str) -> None:
        """Set the currently displayed txid."""
        self._txid = txid
        self.updateUi()

    def updateUi(self) -> None:
        """Update the txid controls."""
        tx_url = self._get_tx_url()
        self.label_txid_title.setText(self.tr("Txid: "))
        self.label_txid.setText(self._txid)
        self.label_txid.setToolTip(self._txid)
        self.button_copy_txid.setToolTip(self.tr("Copy transaction ID"))
        self.button_txid_link.setToolTip(self.tr("View on block explorer"))
        self.button_txid_link.setEnabled(bool(tx_url))
        self.button_txid_link.setVisible(bool(tx_url))

    def copy_txid(self) -> None:
        """Copy the current txid."""
        do_copy(self._txid, title=self.tr("Transaction ID"))

    def open_txid_in_block_explorer(self) -> None:
        """Open the current txid in the configured block explorer."""
        if tx_url := self._get_tx_url():
            webopen(tx_url)

    def _get_tx_url(self) -> str | None:
        """Return the block explorer URL for the current txid."""
        if not self.config.network_config.mempool_url:
            return None
        return block_explorer_URL(self.config.network_config.mempool_url, "tx", self._txid)
