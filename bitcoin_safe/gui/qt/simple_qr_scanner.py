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

import bdkpython as bdk
from bitcoin_qr_tools.gui.bitcoin_video_widget import BitcoinVideoWidget
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol

from bitcoin_safe.gui.qt.dialogs import show_textedit_message
from bitcoin_safe.gui.qt.util import center_on_screen

from .util import do_copy

logger = logging.getLogger(__name__)


class SimpleQrScanner(BitcoinVideoWidget):
    def __init__(
        self,
        network: bdk.Network,
        close_all_video_widgets: SignalProtocol[[]],
        title: str,
        label_description: str = "",
        display_result=True,
    ) -> None:
        """Initialize instance."""
        super().__init__(network=network, close_on_result=True)

        self.close_all_video_widgets = close_all_video_widgets
        self.title = title
        self.display_result = display_result
        self.label_description = label_description

        self.close_all_video_widgets.emit()
        self.signal_raw_content.connect(self.on_raw_decoded)
        self.setWindowTitle(self.title)
        self.show()
        center_on_screen(self, min_height=400, min_width=300)

    def _show_result(self, o: object) -> None:
        """Show result."""
        do_copy(str(o), title=self.title)
        show_textedit_message(text=str(o), label_description=self.label_description, title=self.title)

    def on_raw_decoded(self, o: object) -> None:
        """On raw decoded."""
        if not self.display_result:
            return
        try:
            data = self.meta_data_handler.get_complete_data()
            self._show_result(data)
        except Exception:
            self._show_result(o)
