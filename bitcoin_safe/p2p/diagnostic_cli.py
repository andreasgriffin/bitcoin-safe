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

import argparse
import logging
import signal
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

import bdkpython as bdk
from PyQt6.QtCore import QCoreApplication, QTimer

from bitcoin_safe.network_config import ConnectionInfo, Peer, Peers
from bitcoin_safe.network_utils import ProxyInfo

from .p2p_client import P2PDiagnosticEvent
from .p2p_listener import P2pListener

logger = logging.getLogger(__name__)


@dataclass
class PeerSession:
    peer: Peer
    started_at: float
    handshake_completed_at: float | None = None
    last_event_at: float = field(default_factory=time.time)
    disconnect_reason: str | None = None
    disconnect_uptime_seconds: float | None = None
    last_command: str | None = None
    message_count: int = 0
    tx_count: int = 0
    version_user_agent: str | None = None
    version_services: str | None = None

    @property
    def lifetime_seconds(self) -> float:
        end_time = (
            self.started_at + self.disconnect_uptime_seconds
            if self.disconnect_uptime_seconds
            else self.last_event_at
        )
        return max(end_time - self.started_at, 0.0)


class DiagnosticCollector:
    def __init__(
        self,
        listener: P2pListener,
        app: QCoreApplication,
        duration_seconds: int,
        print_events: bool,
        show_summary_every: int,
    ) -> None:
        self.listener = listener
        self.app = app
        self.duration_seconds = duration_seconds
        self.print_events = print_events
        self.show_summary_every = show_summary_every
        self.started_at = time.time()
        self.current_connections: list[ConnectionInfo] = []
        self.sessions: dict[Peer, PeerSession] = {}
        self.completed_sessions: list[PeerSession] = []
        self.disconnect_reasons: Counter[str] = Counter()
        self.event_counts: Counter[str] = Counter()
        self.last_tx_rates: dict[Peer, float] = {}
        self.longest_connection_seconds = 0.0
        self.longest_connection_peer: Peer | None = None
        self.max_concurrent_connections = 0
        self.max_discovered_peers = 0
        self.shutdown_active_sessions = 0

        listener.signal_current_peers_change.connect(self.on_current_peers_change)
        listener.signal_peer_tx_rate_change.connect(self.on_tx_diagnostic)
        for client in listener.clients:
            client.signal_diagnostic.connect(self.on_diagnostic_signal)

    def on_current_peers_change(self, connections: list[ConnectionInfo]) -> None:
        self.current_connections = list(connections)
        self.max_concurrent_connections = max(self.max_concurrent_connections, len(connections))
        self.max_discovered_peers = max(self.max_discovered_peers, len(self.listener.discovered_peers))

    def on_tx_diagnostic(self, peer: Peer, rate: float) -> None:
        self.last_tx_rates[peer] = rate

    def on_diagnostic_signal(self, event: object) -> None:
        if isinstance(event, P2PDiagnosticEvent):
            self.on_diagnostic_event(event)

    def on_diagnostic_event(self, event: P2PDiagnosticEvent) -> None:
        self.event_counts[event.event] += 1
        peer = event.peer
        if peer is None:
            if self.print_events:
                print(self._format_event_line(event))
            return

        session = self.sessions.get(peer)
        if event.event == "connect_attempt" or session is None:
            session = PeerSession(peer=peer, started_at=event.timestamp)
            self.sessions[peer] = session

        session.last_event_at = event.timestamp
        session.last_command = event.last_command or event.command or session.last_command
        session.message_count = event.message_count
        session.tx_count = event.tx_count

        if event.event == "version_received" and event.detail:
            for part in event.detail.split():
                if part.startswith("user_agent="):
                    session.version_user_agent = part.removeprefix("user_agent=")
                if part.startswith("services="):
                    session.version_services = part.removeprefix("services=")

        if event.event == "verack_received":
            session.handshake_completed_at = event.timestamp

        if event.event in {"connect_timeout", "connect_error"}:
            session.disconnect_reason = event.detail or event.event
            session.disconnect_uptime_seconds = event.uptime_seconds
            self._finalize_session(session)

        if event.event == "disconnected":
            session.disconnect_reason = event.detail or "unknown"
            session.disconnect_uptime_seconds = event.uptime_seconds
            self._finalize_session(session)

        if self.print_events:
            print(self._format_event_line(event))

    def _finalize_session(self, session: PeerSession) -> None:
        reason_key = self._categorize_reason(session.disconnect_reason or "unknown")
        self.disconnect_reasons[reason_key] += 1
        if session.disconnect_uptime_seconds is not None:
            if session.disconnect_uptime_seconds > self.longest_connection_seconds:
                self.longest_connection_seconds = session.disconnect_uptime_seconds
                self.longest_connection_peer = session.peer
        self.completed_sessions.append(session)
        self.sessions.pop(session.peer, None)

    def _format_event_line(self, event: P2PDiagnosticEvent) -> str:
        timestamp = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
        peer = str(event.peer) if event.peer else "-"
        detail = f" detail={event.detail}" if event.detail else ""
        command = f" cmd={event.command}" if event.command else ""
        last_command = f" last={event.last_command}" if event.last_command else ""
        uptime = f" uptime={event.uptime_seconds:.1f}s" if event.uptime_seconds is not None else ""
        counts = f" msgs={event.message_count} txs={event.tx_count}"
        return f"[{timestamp}] {event.event} peer={peer} stage={event.handshake_stage}{command}{last_command}{uptime}{counts}{detail}"

    def print_periodic_summary(self) -> None:
        elapsed = int(time.time() - self.started_at)
        print(f"\n=== P2P diagnostic summary at {elapsed}s ===")
        print(self.render_summary())

    def close_open_sessions(self) -> None:
        """Mark still-open sessions as intentionally ended by the diagnostic run."""
        self.shutdown_active_sessions = len(self.sessions)
        for session in list(self.sessions.values()):
            session.disconnect_reason = "Diagnostic run ended"
            session.disconnect_uptime_seconds = max(time.time() - session.started_at, 0.0)
            self.completed_sessions.append(session)
            if session.disconnect_uptime_seconds > self.longest_connection_seconds:
                self.longest_connection_seconds = session.disconnect_uptime_seconds
                self.longest_connection_peer = session.peer
        self.sessions.clear()

    def render_summary(self) -> str:
        completed = list(self.completed_sessions)
        active = list(self.sessions.values())
        handshake_failures = sum(1 for session in completed if session.handshake_completed_at is None)
        stable_sessions = [
            session
            for session in completed
            if session.disconnect_uptime_seconds is not None and session.disconnect_uptime_seconds >= 300
        ]
        short_sessions = [
            session
            for session in completed
            if session.disconnect_uptime_seconds is not None and session.disconnect_uptime_seconds < 30
        ]
        uptimes = [
            session.disconnect_uptime_seconds
            for session in completed
            if session.disconnect_uptime_seconds is not None
        ]
        median_uptime = statistics.median(uptimes) if uptimes else 0.0
        average_uptime = statistics.fmean(uptimes) if uptimes else 0.0
        lines = [
            f"runtime_seconds={int(time.time() - self.started_at)}",
            f"current_connections={len(self.current_connections)}",
            f"max_concurrent_connections={self.max_concurrent_connections}",
            f"completed_sessions={len(completed)}",
            f"active_sessions={len(active)}",
            f"handshake_failures={handshake_failures}",
            f"short_sessions_lt_30s={len(short_sessions)}",
            f"stable_sessions_ge_300s={len(stable_sessions)}",
            f"avg_uptime_seconds={average_uptime:.1f}",
            f"median_uptime_seconds={median_uptime:.1f}",
            f"longest_connection_seconds={self.longest_connection_seconds:.1f}",
            f"longest_connection_peer={self.longest_connection_peer or '-'}",
            f"discovered_peer_pool={len(self.listener.discovered_peers)}",
            f"max_discovered_peer_pool={self.max_discovered_peers}",
            f"shutdown_active_sessions={self.shutdown_active_sessions}",
        ]

        if self.disconnect_reasons:
            lines.append("disconnect_reasons:")
            for reason, count in self.disconnect_reasons.most_common():
                lines.append(f"  {reason}: {count}")

        if self.event_counts:
            lines.append("event_counts:")
            for name, count in self.event_counts.most_common():
                lines.append(f"  {name}: {count}")

        active_lines = self._render_active_sessions(active)
        if active_lines:
            lines.append("active_peers:")
            lines.extend(active_lines)

        diagnosis_lines = self._build_diagnosis(completed)
        if diagnosis_lines:
            lines.append("likely_causes:")
            lines.extend(f"  {line}" for line in diagnosis_lines)

        return "\n".join(lines)

    def _render_active_sessions(self, active: list[PeerSession]) -> list[str]:
        lines: list[str] = []
        now = time.time()
        for session in sorted(active, key=lambda item: item.started_at):
            tx_rate = self.last_tx_rates.get(session.peer, 0.0)
            lines.append(
                "  "
                + f"{session.peer} age={max(now - session.started_at, 0.0):.1f}s "
                + f"msgs={session.message_count} txs={session.tx_count} tx_rate={tx_rate:.2f}/s "
                + f"last={session.last_command or '-'}"
            )
        return lines

    def _build_diagnosis(self, completed: list[PeerSession]) -> list[str]:
        diagnosis: list[str] = []
        total_disconnects = sum(self.disconnect_reasons.values())
        if total_disconnects == 0:
            diagnosis.append(
                "No disconnects observed yet; extend the run for a more useful stability sample."
            )
            return diagnosis

        timeout_disconnects = sum(
            count
            for reason, count in self.disconnect_reasons.items()
            if reason in {"read_timeout", "send_timeout"}
        )
        peer_closed_disconnects = self.disconnect_reasons.get("peer_closed", 0)
        handler_errors = self.disconnect_reasons.get("handler_error", 0)
        connect_errors = sum(
            count
            for reason, count in self.disconnect_reasons.items()
            if reason in {"connect_error", "connect_timeout"}
        )

        if timeout_disconnects >= max(2, total_disconnects // 3):
            diagnosis.append(
                "Many sessions end on idle I/O timeout. The current listener treats long silences as failure, "
                "but healthy Bitcoin peers may go quiet for minutes while keeping the TCP session valid. "
                "This is the strongest indicator of self-inflicted churn."
            )
        if peer_closed_disconnects >= max(2, total_disconnects // 3):
            diagnosis.append(
                "A large share of peers close the connection first. This points to peer selection quality, "
                "network middleboxes/proxies, or protocol behavior that remote nodes dislike."
            )
        if handler_errors > 0:
            diagnosis.append(
                "Some disconnects follow message handler failures. Malformed or unhandled payloads are causing the "
                "client to drop otherwise established sessions."
            )
        if connect_errors > 0:
            diagnosis.append(
                "Transport establishment fails for part of the peer set. DNS-seeded peers include many unreachable "
                "or filtered nodes, so connection retries alone do not indicate a protocol bug."
            )

        handshake_failures = sum(1 for session in completed if session.handshake_completed_at is None)
        if handshake_failures:
            diagnosis.append(
                "Some sessions die before `verack`, which narrows the instability to TCP setup, version exchange, "
                "or early read/write timeout behavior."
            )

        if not diagnosis:
            diagnosis.append(
                "Disconnect reasons are mixed. Review the top reason buckets and the per-event stream to decide whether "
                "the next hardening step should target timeout policy, peer scoring, or protocol parsing."
            )
        return diagnosis

    @staticmethod
    def _categorize_reason(reason: str) -> str:
        reason_lower = reason.lower()
        if "timed out while waiting" in reason_lower:
            return "read_timeout"
        if "timed out while sending" in reason_lower:
            return "send_timeout"
        if "peer closed" in reason_lower:
            return "peer_closed"
        if "handler error" in reason_lower:
            return "handler_error"
        if "payload" in reason_lower:
            return "oversized_payload"
        if "checksum" in reason_lower:
            return "bad_checksum"
        if "rate limit" in reason_lower:
            return "rate_limit"
        if "timed out while establishing" in reason_lower:
            return "connect_timeout"
        if (
            "name or service not known" in reason_lower
            or "connect call failed" in reason_lower
            or "network is unreachable" in reason_lower
            or "no route to host" in reason_lower
            or "connection refused" in reason_lower
        ):
            return "connect_error"
        if reason_lower == "connect_error":
            return "connect_error"
        if reason_lower == "diagnostic run ended":
            return "run_stopped"
        return "other"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m bitcoin_safe.p2p.diagnostic_cli",
        description="Run the Bitcoin mainnet P2P listener and diagnose unstable connections.",
    )
    parser.add_argument("--duration", type=int, default=180, help="How long to run diagnostics in seconds.")
    parser.add_argument(
        "--parallel-peers",
        type=int,
        default=2,
        help="Number of listener slots to keep connected in parallel.",
    )
    parser.add_argument(
        "--peer",
        action="append",
        default=[],
        help="Preferred peer in host[:port] form. Can be passed multiple times.",
    )
    parser.add_argument(
        "--proxy",
        help="Optional proxy URL, for example socks5h://127.0.0.1:9050.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=200,
        help="Per-read and per-write timeout used by the current listener implementation.",
    )
    parser.add_argument(
        "--print-events",
        action="store_true",
        help="Print every structured connection event as it happens.",
    )
    parser.add_argument(
        "--summary-every",
        type=int,
        default=60,
        help="Print an interim summary every N seconds. Set 0 to disable.",
    )
    parser.add_argument(
        "--disable-autodiscovery",
        action="store_true",
        help="Only use the explicitly provided peers instead of DNS seed discovery.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level for the diagnostic run.",
    )
    return parser.parse_args(argv)


def install_signal_handlers(app: QCoreApplication, listener: P2pListener) -> None:
    def stop_from_signal(signum: int, _frame: object) -> None:
        logger.info("Received signal %s, stopping P2P diagnostics", signum)
        listener.stop()
        app.quit()

    signal.signal(signal.SIGINT, stop_from_signal)
    signal.signal(signal.SIGTERM, stop_from_signal)


def build_preferred_peers(peer_args: list[str]) -> list[Peer]:
    return [Peer.parse(url=value, network=bdk.Network.BITCOIN) for value in peer_args]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = QCoreApplication([sys.argv[0]])
    proxy_info = ProxyInfo.parse(args.proxy) if args.proxy else None
    preferred_peers = build_preferred_peers(args.peer)
    discovered_peers = Peers(preferred_peers)

    listener = P2pListener(
        network=bdk.Network.BITCOIN,
        loop_in_thread=None,
        debug=False,
        fetch_txs=True,
        timeout=args.timeout,
        discovered_peers=discovered_peers,
        autodiscover_additional_peers=not args.disable_autodiscovery,
        max_parallel_peers=args.parallel_peers,
    )
    collector = DiagnosticCollector(
        listener=listener,
        app=app,
        duration_seconds=args.duration,
        print_events=args.print_events,
        show_summary_every=args.summary_every,
    )
    install_signal_handlers(app=app, listener=listener)

    listener.start(proxy_info=proxy_info, preferred_peers=preferred_peers or None)

    stop_timer = QTimer()
    stop_timer.setSingleShot(True)
    stop_timer.timeout.connect(lambda: (listener.stop(), app.quit()))
    stop_timer.start(max(args.duration, 1) * 1000)

    summary_timer: QTimer | None = None
    if args.summary_every > 0:
        summary_timer = QTimer()
        summary_timer.timeout.connect(collector.print_periodic_summary)
        summary_timer.start(args.summary_every * 1000)

    print("Starting Bitcoin mainnet P2P diagnostic listener")
    print(f"duration_seconds={args.duration}")
    print(f"parallel_peers={args.parallel_peers}")
    print(f"timeout_seconds={args.timeout}")
    print(f"proxy={args.proxy or '-'}")
    print(f"preferred_peers={', '.join(str(peer) for peer in preferred_peers) if preferred_peers else '-'}")
    print(f"autodiscovery={'enabled' if not args.disable_autodiscovery else 'disabled'}")

    exit_code = app.exec()

    if summary_timer is not None:
        summary_timer.stop()
    collector.close_open_sessions()
    listener.stop()

    print("\n=== Final P2P diagnostic summary ===")
    print(collector.render_summary())
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
