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
import logging
import random
import threading
from collections.abc import Iterable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.broadcast_types import (
    BroadcastAttempt,
    BroadcastCompletion,
    BroadcastOutcome,
    BroadcastRequest,
    WalletBroadcastRoute,
)
from bitcoin_safe.tx import short_tx_id

if TYPE_CHECKING:
    from bitcoin_safe.client import Client
    from bitcoin_safe.p2p.p2p_listener import P2pListener

logger = logging.getLogger(__name__)


def unique_wallet_routes(
    wallet_clients: Iterable[tuple[str, Client | None]],
) -> tuple[WalletBroadcastRoute, ...]:
    """Group wallet IDs by shared client identity while preserving wallet order."""
    clients: dict[int, tuple[Client, list[str]]] = {}
    for wallet_id, client in wallet_clients:
        if client is None:
            continue
        entry = clients.setdefault(id(client), (client, []))
        entry[1].append(wallet_id)
    return tuple(
        WalletBroadcastRoute(client=client, wallet_ids=tuple(wallet_ids))
        for client, wallet_ids in clients.values()
    )


@dataclass
class _BroadcastFlight:
    request: BroadcastRequest
    request_ids: list[str] = field(default_factory=list)
    task: Future[None] | None = None


class BroadcastCoordinator(QObject):
    """Retry broadcast routes away from the GUI thread and coalesce identical txids."""

    signal_complete = pyqtSignal(object)

    def __init__(self, loop_in_thread: LoopInThread, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.loop_in_thread = loop_in_thread
        self._lock = threading.Lock()
        self._in_flight: dict[str, _BroadcastFlight] = {}

    def close(self) -> None:
        """Cancel every pending broadcast so no send runs after shutdown begins."""
        with self._lock:
            flights = list(self._in_flight.values())
            self._in_flight.clear()
        for flight in flights:
            if flight.task is not None:
                flight.task.cancel()

    def submit(
        self,
        request: BroadcastRequest,
        wallet_routes: tuple[WalletBroadcastRoute, ...],
        listener: P2pListener | None,
    ) -> None:
        """Schedule one broadcast sequence, joining an existing sequence for the txid."""
        txid = request.txid
        with self._lock:
            flight = self._in_flight.get(txid)
            if flight is not None:
                flight.request_ids.append(request.request_id)
                return
            flight = _BroadcastFlight(request=request, request_ids=[request.request_id])
            self._in_flight[txid] = flight
            flight.task = self.loop_in_thread.run_background(self._run(flight, wallet_routes, listener))

    async def _run(
        self,
        flight: _BroadcastFlight,
        wallet_routes: tuple[WalletBroadcastRoute, ...],
        listener: P2pListener | None,
    ) -> None:
        attempts: list[BroadcastAttempt] = []
        successful_route: BroadcastAttempt | None = None
        wallet_timeout = False
        txid = flight.request.txid
        try:
            routes = list(wallet_routes)
            random.shuffle(routes)
            logger.info(f"Broadcasting {short_tx_id(txid)}: {len(routes)} wallet route(s) to try")
            for route in routes:
                backend = type(route.client.client).__name__
                try:
                    await route.client.broadcast_async(flight.request.tx)
                except Exception as exc:
                    wallet_timeout |= isinstance(exc, (asyncio.TimeoutError, TimeoutError))
                    error = str(exc) or type(exc).__name__
                    wallets = ", ".join(route.wallet_ids)
                    logger.info(
                        f"Broadcast {short_tx_id(txid)} via {backend} wallets {wallets} failed: {error}"
                    )
                    attempts.append(
                        BroadcastAttempt(
                            route_type="wallet",
                            backend=backend,
                            wallet_ids=route.wallet_ids,
                            success=False,
                            error=error,
                        )
                    )
                    continue
                wallets = ", ".join(route.wallet_ids)
                logger.info(f"Broadcast {short_tx_id(txid)} succeeded via {backend} wallets {wallets}")
                successful_route = BroadcastAttempt(
                    route_type="wallet", backend=backend, wallet_ids=route.wallet_ids, success=True
                )
                attempts.append(successful_route)
                break

            if successful_route is None and listener is not None:
                logger.info(f"Broadcast {short_tx_id(txid)}: no wallet route succeeded, trying P2P peers")
                for p2p_attempt in await listener.broadcast_tx(flight.request.tx.serialize().hex()):
                    attempt = BroadcastAttempt(
                        route_type="p2p",
                        peer=p2p_attempt.peer,
                        success=p2p_attempt.success,
                        error=p2p_attempt.error,
                    )
                    attempts.append(attempt)
                    if attempt.success:
                        logger.info(f"Broadcast {short_tx_id(txid)} written to P2P peer {attempt.peer}")
                        successful_route = attempt
                        break
                    logger.info(
                        f"Broadcast {short_tx_id(txid)} to P2P peer {attempt.peer} failed: {attempt.error}"
                    )

            outcome = (
                BroadcastOutcome.success
                if successful_route
                else BroadcastOutcome.failure
                if attempts
                else BroadcastOutcome.no_routes
            )
            logger.info(
                f"Broadcast {short_tx_id(txid)} finished: {outcome.value} after {len(attempts)} attempt(s)"
            )
        except asyncio.CancelledError:
            self._complete(flight, BroadcastOutcome.failure, None, attempts, wallet_timeout)
            raise
        except Exception as exc:
            logger.exception("Unexpected transaction broadcast coordinator failure")
            attempts.append(BroadcastAttempt(route_type="coordinator", success=False, error=str(exc)))
            outcome = BroadcastOutcome.failure

        self._complete(flight, outcome, successful_route, attempts, wallet_timeout)

    def _complete(
        self,
        flight: _BroadcastFlight,
        outcome: BroadcastOutcome,
        successful_route: BroadcastAttempt | None,
        attempts: list[BroadcastAttempt],
        wallet_timeout: bool,
    ) -> None:
        """Remove the in-flight entry and emit one completion with all requesters."""
        with self._lock:
            if self._in_flight.pop(flight.request.txid, None) is None:
                return  # already cancelled by close()
            request_ids = tuple(flight.request_ids)
        self.signal_complete.emit(
            BroadcastCompletion(
                txid=flight.request.txid,
                request_ids=request_ids,
                outcome=outcome,
                successful_route=successful_route,
                attempts=tuple(attempts),
                wallet_timeout=wallet_timeout,
            )
        )
