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

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bitcoin_safe.client import Client
from bitcoin_safe.psbt_util import FeeRate


def test_relay_fee_btc_per_kb_to_fee_rate() -> None:
    """Electrum relay fee conversion should preserve sub-sat precision."""
    assert FeeRate.from_btc_per_kb(1e-5).to_sat_per_kwu() == 250
    assert FeeRate.from_btc_per_kb(1e-6).to_sat_per_kwu() == 25


def test_get_min_broadcast_fee_rate_electrum(monkeypatch) -> None:
    """Electrum should expose the backend relay fee as a FeeRate."""

    class FakeElectrumClient:
        def relay_fee(self) -> float:
            return 1e-5

    monkeypatch.setattr("bitcoin_safe.client.bdk.ElectrumClient", FakeElectrumClient)

    client = Client(
        client=FakeElectrumClient(),
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=MagicMock(),
    )

    fee_rate = client.get_min_broadcast_fee_rate()
    assert fee_rate is not None
    assert FeeRate.to_sats_per_vb(fee_rate) == pytest.approx(1.0)


def test_get_min_broadcast_fee_rate_electrum_subsat(monkeypatch) -> None:
    """Electrum relay fee conversion should support 0.1 sat/vB."""

    class FakeElectrumClient:
        def relay_fee(self) -> float:
            return 1e-6

    monkeypatch.setattr("bitcoin_safe.client.bdk.ElectrumClient", FakeElectrumClient)

    client = Client(
        client=FakeElectrumClient(),
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=MagicMock(),
    )

    fee_rate = client.get_min_broadcast_fee_rate()
    assert fee_rate is not None
    assert FeeRate.to_sats_per_vb(fee_rate) == pytest.approx(0.1)


def test_get_min_broadcast_fee_rate_esplora(monkeypatch) -> None:
    """Esplora should not claim a backend minimum broadcast fee."""

    class FakeEsploraClient:
        pass

    monkeypatch.setattr("bitcoin_safe.client.bdk.EsploraClient", FakeEsploraClient)

    client = Client(
        client=FakeEsploraClient(),
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=MagicMock(),
    )

    assert client.get_min_broadcast_fee_rate() is None


def test_get_min_broadcast_fee_rate_cbf(monkeypatch) -> None:
    """CBF should expose the backend minimum fee rate as a FeeRate."""

    class FakeFeeRate:
        def to_sat_per_kwu(self) -> int:
            return 250

    class FakeCbfSync:
        def __init__(self) -> None:
            self.client = SimpleNamespace(min_broadcast_feerate=lambda: "future")

    monkeypatch.setattr("bitcoin_safe.client.CbfSync", FakeCbfSync)

    loop_in_thread = MagicMock()
    loop_in_thread.run_background.side_effect = lambda coroutine, key=None: coroutine.close()
    loop_in_thread.run_foreground.return_value = FakeFeeRate()
    cbf_sync = FakeCbfSync()

    client = Client(
        client=cbf_sync,
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=loop_in_thread,
    )

    fee_rate = client.get_min_broadcast_fee_rate()
    assert fee_rate is not None
    assert FeeRate.to_sats_per_vb(fee_rate) == pytest.approx(1.0)
    loop_in_thread.run_foreground.assert_called_once_with("future")


def test_get_min_broadcast_fee_rate_returns_none_on_error(monkeypatch) -> None:
    """Backend fee lookup failures should be swallowed for the UI."""

    class FakeElectrumClient:
        def relay_fee(self) -> float:
            raise RuntimeError("boom")

    monkeypatch.setattr("bitcoin_safe.client.bdk.ElectrumClient", FakeElectrumClient)

    client = Client(
        client=FakeElectrumClient(),
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=MagicMock(),
    )

    assert client.get_min_broadcast_fee_rate() is None
