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

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import bitcoin_safe.client as client_module
from bitcoin_safe.client import Client
from bitcoin_safe.client_helpers import UpdateInfo
from bitcoin_safe.psbt_util import FeeRate


def _close_wait_for_coroutine(coroutine) -> None:
    inner = coroutine.cr_frame.f_locals.get("fut") if coroutine.cr_frame else None
    if inner and hasattr(inner, "close"):
        inner.close()
    coroutine.close()


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

    loop_in_thread = MagicMock()
    loop_in_thread.run_foreground.side_effect = lambda coroutine: (
        _close_wait_for_coroutine(coroutine),
        1e-5,
    )[1]
    client = Client(
        client=FakeElectrumClient(),
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=loop_in_thread,
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

    loop_in_thread = MagicMock()
    loop_in_thread.run_foreground.side_effect = lambda coroutine: (
        _close_wait_for_coroutine(coroutine),
        1e-6,
    )[1]
    client = Client(
        client=FakeElectrumClient(),
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=loop_in_thread,
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

    def run_foreground(coroutine):
        coroutine.close()
        return FakeFeeRate()

    loop_in_thread.run_foreground.side_effect = run_foreground
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
    loop_in_thread.run_foreground.assert_called_once()


def test_get_min_broadcast_fee_rate_returns_none_on_error(monkeypatch) -> None:
    """Backend fee lookup failures should be swallowed for the UI."""

    class FakeElectrumClient:
        def relay_fee(self) -> float:
            raise RuntimeError("boom")

    monkeypatch.setattr("bitcoin_safe.client.bdk.ElectrumClient", FakeElectrumClient)

    loop_in_thread = MagicMock()

    def run_foreground(coroutine):
        _close_wait_for_coroutine(coroutine)
        raise RuntimeError("boom")

    loop_in_thread.run_foreground.side_effect = run_foreground
    client = Client(
        client=FakeElectrumClient(),
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=loop_in_thread,
    )

    assert client.get_min_broadcast_fee_rate() is None


def test_get_min_broadcast_fee_rate_returns_none_on_electrum_timeout(monkeypatch) -> None:
    """Electrum timeout should not leak into the UI."""

    class FakeElectrumClient:
        def relay_fee(self) -> float:
            return 1e-5

    monkeypatch.setattr("bitcoin_safe.client.bdk.ElectrumClient", FakeElectrumClient)

    loop_in_thread = MagicMock()

    def run_foreground(coroutine):
        _close_wait_for_coroutine(coroutine)
        raise TimeoutError("timed out")

    client = Client(
        client=FakeElectrumClient(),
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=loop_in_thread,
    )
    loop_in_thread.run_foreground.side_effect = run_foreground

    assert client.get_min_broadcast_fee_rate() is None


def test_get_min_broadcast_fee_rate_returns_none_on_cbf_timeout(monkeypatch) -> None:
    """CBF timeout should not leak into the UI."""

    class FakeCbfSync:
        def __init__(self) -> None:
            self.client = SimpleNamespace(min_broadcast_feerate=lambda: "future")

    monkeypatch.setattr("bitcoin_safe.client.CbfSync", FakeCbfSync)

    loop_in_thread = MagicMock()
    loop_in_thread.run_background.side_effect = lambda coroutine, key=None: coroutine.close()

    def run_foreground(coroutine):
        coroutine.close()
        raise asyncio.TimeoutError()

    loop_in_thread.run_foreground.side_effect = run_foreground
    cbf_sync = FakeCbfSync()

    client = Client(
        client=cbf_sync,
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=loop_in_thread,
    )

    assert client.get_min_broadcast_fee_rate() is None


class FakeElectrumClient:
    def __init__(self) -> None:
        self.sync_calls: list[dict[str, object]] = []

    def sync(self, request, batch_size: int, fetch_prev_txouts: bool):
        self.sync_calls.append(
            {
                "request": request,
                "batch_size": batch_size,
                "fetch_prev_txouts": fetch_prev_txouts,
            }
        )
        return "sync-update"


def test_sync_preserves_custom_update_type(loop_in_thread, monkeypatch) -> None:
    """Client.sync should preserve the caller-provided update type."""
    fake_electrum_client = FakeElectrumClient()
    monkeypatch.setattr(client_module.bdk, "ElectrumClient", FakeElectrumClient)
    client = Client(
        client=fake_electrum_client,
        electrum_config=None,
        proxy_info=None,
        loop_in_thread=loop_in_thread,
    )

    request = object()
    client.sync(request=request, update_type=UpdateInfo.UpdateType.sync_revealed_spks)

    update_info = client._update_queue.get_nowait()
    assert update_info.update == "sync-update"
    assert update_info.update_type == UpdateInfo.UpdateType.sync_revealed_spks
    assert fake_electrum_client.sync_calls == [
        {
            "request": request,
            "batch_size": 100,
            "fetch_prev_txouts": True,
        }
    ]
