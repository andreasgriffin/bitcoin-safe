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

import asyncio
from types import SimpleNamespace

from bitcoin_safe.broadcast_types import BroadcastOutcome, BroadcastRequest, WalletBroadcastRoute
from bitcoin_safe.gui.qt.broadcast import BroadcastCoordinator, unique_wallet_routes
from bitcoin_safe.p2p.p2p_listener import P2PBroadcastAttempt


class FakeLoop:
    def run_background(self, coroutine):
        self.coroutine = coroutine


class FakeTransaction:
    def compute_txid(self) -> str:
        return "txid"

    def serialize(self) -> bytes:
        return b"tx"


class FakeClient:
    def __init__(self, response: Exception | None = None) -> None:
        self.client = SimpleNamespace()
        self.response = response
        self.calls = 0

    async def broadcast(self, _tx: FakeTransaction) -> None:
        self.calls += 1
        if self.response:
            raise self.response


class FakeListener:
    def __init__(self, attempts: tuple[P2PBroadcastAttempt, ...]) -> None:
        self.attempts = attempts
        self.calls = 0

    async def broadcast_tx(self, _raw_hex: str) -> tuple[P2PBroadcastAttempt, ...]:
        self.calls += 1
        return self.attempts


def test_unique_wallet_routes_group_shared_client_identity() -> None:
    shared = FakeClient()
    distinct = FakeClient()

    routes = unique_wallet_routes(
        (("wallet-a", shared), ("wallet-b", shared), ("wallet-c", distinct), ("wallet-d", None))
    )

    assert len(routes) == 2
    assert routes[0].client is shared
    assert routes[0].wallet_ids == ("wallet-a", "wallet-b")
    assert routes[1].wallet_ids == ("wallet-c",)


def test_wallet_attempts_stop_on_first_success(monkeypatch) -> None:
    monkeypatch.setattr("bitcoin_safe.gui.qt.broadcast.random.shuffle", lambda routes: None)
    loop = FakeLoop()
    coordinator = BroadcastCoordinator(loop)
    completions = []
    coordinator.signal_complete.connect(completions.append)
    failed = FakeClient(RuntimeError("offline"))
    succeeded = FakeClient()
    request = BroadcastRequest.create(FakeTransaction())

    coordinator.submit(
        request,
        (
            WalletBroadcastRoute(failed, ("wallet-a",)),
            WalletBroadcastRoute(succeeded, ("wallet-b",)),
        ),
        None,
    )
    asyncio.run(loop.coroutine)

    assert failed.calls == succeeded.calls == 1
    assert completions[0].outcome is BroadcastOutcome.success
    assert [attempt.success for attempt in completions[0].attempts] == [False, True]
    assert completions[0].attempts[0].wallet_ids == ("wallet-a",)


def test_same_txid_requests_coalesce_and_fallback_to_p2p() -> None:
    loop = FakeLoop()
    coordinator = BroadcastCoordinator(loop)
    completions = []
    coordinator.signal_complete.connect(completions.append)
    failed = FakeClient(RuntimeError("backend rejected transaction"))
    listener = FakeListener((P2PBroadcastAttempt(peer="node:8333", success=True),))
    first = BroadcastRequest.create(FakeTransaction())
    second = BroadcastRequest.create(FakeTransaction())

    routes = (WalletBroadcastRoute(failed, ("wallet",)),)
    coordinator.submit(first, routes, listener)
    coordinator.submit(second, routes, listener)
    asyncio.run(loop.coroutine)

    assert failed.calls == 1
    assert listener.calls == 1
    assert len(completions) == 1
    assert completions[0].request_ids == (first.request_id, second.request_id)
    assert completions[0].successful_route.peer == "node:8333"


def test_failed_wallet_and_empty_p2p_routes_report_failure() -> None:
    loop = FakeLoop()
    coordinator = BroadcastCoordinator(loop)
    completions = []
    coordinator.signal_complete.connect(completions.append)
    failed = FakeClient(RuntimeError("backend rejected transaction"))
    listener = FakeListener(())
    request = BroadcastRequest.create(FakeTransaction())

    coordinator.submit(request, (WalletBroadcastRoute(failed, ("wallet",)),), listener)
    asyncio.run(loop.coroutine)

    assert completions[0].outcome is BroadcastOutcome.failure
    assert completions[0].attempts[0].error == "backend rejected transaction"


def test_no_available_routes_report_no_routes() -> None:
    loop = FakeLoop()
    coordinator = BroadcastCoordinator(loop)
    completions = []
    coordinator.signal_complete.connect(completions.append)
    request = BroadcastRequest.create(FakeTransaction())

    coordinator.submit(request, (), None)
    asyncio.run(loop.coroutine)

    assert completions[0].outcome is BroadcastOutcome.no_routes
    assert completions[0].attempts == ()


def test_close_cancels_pending_broadcast_without_completion(monkeypatch) -> None:
    """Closing the coordinator cancels in-flight work and emits no completion."""

    class PendingFuture:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> bool:
            self.cancelled = True
            return True

    class FakeLoopCapturingTask:
        def run_background(self, coroutine):
            self.coroutine = coroutine
            self.future = PendingFuture()
            return self.future

    loop = FakeLoopCapturingTask()
    coordinator = BroadcastCoordinator(loop)
    completions = []
    coordinator.signal_complete.connect(completions.append)
    request = BroadcastRequest.create(FakeTransaction())

    coordinator.submit(request, (WalletBroadcastRoute(FakeClient(), ("wallet",)),), None)
    coordinator.close()
    loop.coroutine.close()

    assert loop.future.cancelled
    assert completions == []
    assert coordinator._in_flight == {}
