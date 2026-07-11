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

import bdkpython as bdk
from bitcoin_usb.address_types import AddressTypes
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.analyzers import KeyOriginAnalyzer
from bitcoin_safe.gui.qt.custom_edits import AnalyzerState


def _make_key_origin_analyzer(expected_key_origin: str, network: bdk.Network) -> KeyOriginAnalyzer:
    return KeyOriginAnalyzer(
        get_expected_key_origin=lambda: expected_key_origin,
        network=network,
        parent=None,
    )


def test_key_origin_analyzer_detects_network_mismatch(qtbot: QtBot) -> None:
    del qtbot
    analyzer = _make_key_origin_analyzer(
        AddressTypes.p2wpkh.key_origin(bdk.Network.BITCOIN),
        network=bdk.Network.BITCOIN,
    )

    analysis = analyzer.analyze(AddressTypes.p2wpkh.key_origin(bdk.Network.REGTEST))

    assert analysis.state == AnalyzerState.Invalid
    assert "Please provide xPub for network" in analysis.msg


def test_key_origin_analyzer_warns_for_singlesig_multisig_mixup(qtbot: QtBot) -> None:
    del qtbot
    analyzer = _make_key_origin_analyzer(
        AddressTypes.p2wsh.key_origin(bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )

    analysis = analyzer.analyze(AddressTypes.p2wpkh.key_origin(bdk.Network.REGTEST))

    assert analysis.state == AnalyzerState.Warning
    assert analysis.msg == "This looks like a single-sig. Expected: multi-sig."


def test_key_origin_analyzer_warns_for_wrong_singlesig_address_type(qtbot: QtBot) -> None:
    del qtbot
    analyzer = _make_key_origin_analyzer(
        AddressTypes.p2tr.key_origin(bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )

    analysis = analyzer.analyze(AddressTypes.p2wpkh.key_origin(bdk.Network.REGTEST))

    assert analysis.state == AnalyzerState.Warning
    assert AddressTypes.p2wpkh.name in analysis.msg
    assert AddressTypes.p2tr.name in analysis.msg
