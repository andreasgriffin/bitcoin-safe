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

import random

import bdkpython as bdk
import pytest
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_qr_tools.unified_encoder import QrExportTypes, UnifiedEncoder

from bitcoin_safe.gui.qt.export_data import generate_fragments_for_qr


def test_large_bbqr_uses_a_larger_qr_version() -> None:
    payload = random.Random(0).randbytes(300_000).hex()
    data = Data(payload, DataType.LabelsBip329, bdk.Network.REGTEST)

    with pytest.raises(ValueError, match="Cannot make it fit"):
        UnifiedEncoder.generate_fragments_for_qr(
            data=data,
            qr_export_type=QrExportTypes.bbqr,
            max_qr_size=50,
        )

    fragments = generate_fragments_for_qr(data=data, qr_export_type=QrExportTypes.bbqr)

    assert 1 < len(fragments) <= 1295
