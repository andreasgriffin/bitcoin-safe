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

from unittest.mock import Mock

from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason
from bitcoin_safe.wallet import TxConfirmationStatus, TxStatus


def test_psbt_viewer_ignores_chain_height_only_update() -> None:
    psbt_status = TxStatus(
        tx=None,
        chain_position=None,
        get_height=lambda: 0,
        fallback_confirmation_status=TxConfirmationStatus.PSBT,
    )
    viewer = Mock()
    viewer.chain_position = None
    viewer.get_tx_status.return_value = psbt_status

    UITx_Viewer.reload(
        viewer,
        UpdateFilter(reason=UpdateFilterReason.ChainHeightAdvanced),
    )

    viewer.set_tab_properties.assert_not_called()
    viewer.maybe_defer_update.assert_not_called()
    viewer.set_psbt.assert_not_called()
