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

from bitcoin_qr_tools.unified_encoder import QrExportTypes

from bitcoin_safe.gui.qt.tx_signing_steps import allows_psbt_qr_type_choice, preferred_psbt_qr_type
from bitcoin_safe.hardware_signers import HardwareSigners


def test_krux_psbt_qr_prefers_bbqr() -> None:
    assert preferred_psbt_qr_type(HardwareSigners.krux) == QrExportTypes.bbqr


def test_generic_signer_allows_psbt_qr_type_choice() -> None:
    assert allows_psbt_qr_type_choice(HardwareSigners.generic)
    assert not allows_psbt_qr_type_choice(HardwareSigners.krux)
