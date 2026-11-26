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

from unittest.mock import MagicMock

import bdkpython as bdk
import pytest

from bitcoin_safe.gui.qt.analyzers import AddressAnalyzer
from bitcoin_safe.gui.qt.custom_edits import AnalyzerState
from bitcoin_safe.output_validation import validate_raw_output_script
from bitcoin_safe.pythonbdk_types import Recipient
from bitcoin_safe.tx import TxUiInfos
from bitcoin_safe.wallet import Wallet


@pytest.mark.parametrize("allow_all", [False, True])
@pytest.mark.parametrize("allow_return", [False, True])
def test_raw_script_policy(monkeypatch: pytest.MonkeyPatch, allow_all: bool, allow_return: bool) -> None:
    monkeypatch.setattr("bitcoin_safe.execute_config.ALLOW_ALL_SCRIPTS", allow_all)
    monkeypatch.setattr("bitcoin_safe.execute_config.ALLOW_OP_RETURN", allow_return)
    analyzer = AddressAnalyzer(bdk.Network.REGTEST, None, allow_scripts=True)
    for text, allowed in [
        ("script:", False),
        ("script:51", allow_all),
        ("script:6a", allow_return),
        ("script:xx", False),
    ]:
        assert (analyzer.analyze(text).state == AnalyzerState.Valid) == allowed
        recipient = Recipient(text, 0)
        if allowed:
            validate_raw_output_script(bytes.fromhex(text[7:]))
        else:
            with pytest.raises(ValueError):
                Wallet.create_psbt(MagicMock(), TxUiInfos(recipients=[recipient]))
        assert recipient.address == text
    with pytest.raises(ValueError, match="amount of zero"):
        validate_raw_output_script(bytes.fromhex("6a"), 1)
    # A known-valid regular address remains accepted independently of script policy.
    descriptor = bdk.Descriptor(
        "wpkh(0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798)", bdk.NetworkKind.TEST
    )
    address = str(descriptor.derive_address(0, bdk.Network.REGTEST))
    assert analyzer.analyze(address).state == AnalyzerState.Valid
