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

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bdkpython as bdk
import pytest

from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.wallet import ProtoWallet


def clone_protowallet(protowallet: ProtoWallet) -> ProtoWallet:
    return ProtoWallet(
        wallet_id=protowallet.id,
        threshold=protowallet.threshold,
        keystores=[keystore.clone() if keystore else None for keystore in protowallet.keystores],
        network=protowallet.network,
        address_type=protowallet.address_type,
        gap=protowallet.gap,
    )


class DummyWallet:
    def __init__(self, protowallet: ProtoWallet) -> None:
        self.id = protowallet.id
        self._protowallet = clone_protowallet(protowallet)
        self.labels = SimpleNamespace(default_category=None)
        self.tips: list[int] = []

    def as_protowallet(self) -> ProtoWallet:
        return clone_protowallet(self._protowallet)


class DummyDescriptorUI:
    def __init__(self, protowallet: ProtoWallet, requested_wallet_id: str) -> None:
        self.protowallet = clone_protowallet(protowallet)
        self._requested_wallet_id = requested_wallet_id

    def get_wallet_id_from_ui(self) -> str:
        return self._requested_wallet_id

    def set_protowallet_from_ui(self) -> None:
        self.protowallet.id = self._requested_wallet_id


@pytest.mark.marker_qt_1
def test_qtwallet_apply_settings_treats_rename_only_as_changes() -> None:
    current_protowallet = ProtoWallet(
        threshold=1,
        keystores=[None],
        network=bdk.Network.REGTEST,
        wallet_id="wallet-old",
    )
    requested_wallet_id = "wallet-renamed"
    dummy_wallet = DummyWallet(current_protowallet)
    descriptor_ui = DummyDescriptorUI(current_protowallet, requested_wallet_id=requested_wallet_id)

    qt_wallet = SimpleNamespace(
        save=Mock(),
        wallet=dummy_wallet,
        wallet_descriptor_ui=descriptor_ui,
        change_wallet_id=Mock(return_value=Path("/tmp/wallet-renamed.wallet")),
        _apply_no_impact_setting_changes=Mock(),
        _recreate_qt_wallet=Mock(),
        tr=lambda text: text,
    )

    with patch("bitcoin_safe.gui.qt.qt_wallet.Message") as message:
        QTWallet.on_qtwallet_apply_setting_changes(qt_wallet)  # type: ignore[arg-type]

    assert qt_wallet.save.call_count == 2
    qt_wallet.change_wallet_id.assert_called_once_with(requested_wallet_id)
    qt_wallet._apply_no_impact_setting_changes.assert_not_called()
    qt_wallet._recreate_qt_wallet.assert_not_called()
    message.assert_called_once_with("Changes applied.", parent=qt_wallet)
