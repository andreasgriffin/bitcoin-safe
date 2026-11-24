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

from __future__ import annotations

import bdkpython as bdk
import pytest

from bitcoin_safe.psbt_util import FeeInfo, compact_size_length, estimate_tx_weight, weight_to_vsize
from tests.non_gui.test_psbt_util import p2wsh_psbt_0_2of3


@pytest.mark.parametrize(
    ("value", "size"),
    [(0, 1), (252, 1), (253, 3), (65535, 3), (65536, 5), (2**32 - 1, 5), (2**32, 9)],
)
def test_compact_size_length(value: int, size: int) -> None:
    assert compact_size_length(value) == size


def test_estimate_accounts_for_script_and_output_count_lengths() -> None:
    base = estimate_tx_weight([(1, 1)], [bdk.Script(bytes(22))])
    assert estimate_tx_weight([(1, 1)], [bdk.Script(bytes(200))]) - base == 178 * 4
    assert estimate_tx_weight([(1, 1)], [bdk.Script(bytes(252))]) - base == 230 * 4
    assert estimate_tx_weight([(1, 1)], [bdk.Script(bytes(253))]) - base == 233 * 4
    empty_script = bdk.Script(b"")
    assert (
        estimate_tx_weight([(1, 1)], [empty_script] * 253)
        - estimate_tx_weight([(1, 1)], [empty_script] * 252)
        == 11 * 4
    )
    assert estimate_tx_weight([(1, 1)], [None]) == base
    assert FeeInfo.estimate_from_num_inputs(2, [(1, 1)], [bdk.Script(bytes(200))]).vsize == weight_to_vsize(
        estimate_tx_weight([(1, 1)], [bdk.Script(bytes(200))])
    )


def test_psbt_fee_estimate_uses_output_scripts() -> None:
    psbt = p2wsh_psbt_0_2of3
    assert [len(output.script_pubkey.to_bytes()) for output in psbt.extract_tx().output()] == [34, 34]
    estimate = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
    assert estimate.vsize == weight_to_vsize(
        estimate_tx_weight([(2, 3)], [output.script_pubkey for output in psbt.extract_tx().output()])
    )
    assert estimate.fee_amount == psbt.fee()
