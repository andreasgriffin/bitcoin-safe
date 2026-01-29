#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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

from __future__ import annotations

import asyncio
import base64
import collections
import enum
import hashlib
import ipaddress
import logging
import os
import random
import socket
import struct
import time
from asyncio import StreamReader, StreamWriter
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, cast

import bdkpython as bdk
from aiohttp_socks import open_connection as socks_open_connection
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.network_config import ConnectionInfo, Peer, Peers
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.util import default_timeout

logger = logging.getLogger(__name__)

###############################################################################
# Constants & helpers
###############################################################################

# ────────────────────────────────────────────────────────────────
# DoS-hardening limits – adjust to taste
# ────────────────────────────────────────────────────────────────
MAX_PAYLOAD_LEN = 32 * 1024 * 1024  # 32 MiB – hard upper bound (BIP-339)
MAX_INV_ITEMS = 50_000  # reasonable inv list cap
MAX_MSGS_PER_SEC = 100  # generic message rate
MAX_TXS_PER_SEC = 50  # stricter limit for “tx”
RATE_WINDOW_SEC = 1.0  # sliding-window size
MAX_ADDR_ITEMS = 1000  # Cap addr/v1 and addrv2 list sizes

# Mapping of recognised networks → magic value (big‑endian as on‑the‑wire)
MAGIC_VALUES: dict[Any, int] = {
    bdk.Network.BITCOIN: 0xF9BEB4D9,  # https://github.com/bitcoin/bitcoin/blob/7590e93bc73b3bbac641f05d490fd5c984156b33/src/kernel/chainparams.cpp#L128
    bdk.Network.TESTNET: 0x0B110907,  # https://github.com/bitcoin/bitcoin/blob/7590e93bc73b3bbac641f05d490fd5c984156b33/src/kernel/chainparams.cpp#L247
    bdk.Network.REGTEST: 0xFABFB5DA,  # https://github.com/bitcoin/bitcoin/blob/7590e93bc73b3bbac641f05d490fd5c984156b33/src/kernel/chainparams.cpp#L563
    bdk.Network.SIGNET: 0x0A03CF40,  # https://en.bitcoin.it/wiki/Signet#Differences
    bdk.Network.TESTNET4: 0x1C163F28,  # https://github.com/bitcoin/bitcoin/blob/7590e93bc73b3bbac641f05d490fd5c984156b33/src/kernel/chainparams.cpp#L346
}


# Inventory type constants (superset – see BIP 339 / 152 / 157)
class InventoryType(enum.Enum):
    MSG_TX = 1  # A transaction message (inv points to a transaction)
    MSG_BLOCK = 2  # A full block message (inv points to a serialized block)
    MSG_FILTERED_BLOCK = 3  # A filtered (merkle) block; nodes ask for only relevant transactions
    MSG_CMPCT_BLOCK = 4  # A compact block, containing short IDs for transactions to save bandwidth
    # BIP144: witness types use the high "witness flag" bit (1 << 30)
    MSG_WITNESS_TX = 0x40000001
    MSG_WITNESS_BLOCK = 0x40000002


# Compact‑filter specific (BIP 157/158) – command names
CF_HEADERS_CMD = "cfheaders"
CF_CHECKPT_CMD = "cfcheckpt"
CFILTER_CMD = "cfilter"


@dataclass
class InventoryItem:
    type: InventoryType
    payload: str


class Inventory(list[InventoryItem]):
    pass


def decode_varint(data: bytes) -> tuple[int, int]:
    """Decode varint."""
    if not data:
        raise ValueError("Empty varint")
    size = data[0]
    # 1-byte value
    if size < 0xFD:
        return size, 1

    # 0xFD → next 2 bytes
    if size == 0xFD:
        if len(data) < 3:
            raise ValueError("Truncated varint (need 2 more bytes)")
        return int.from_bytes(data[1:3], "little"), 3

    # 0xFE → next 4 bytes
    if size == 0xFE:
        if len(data) < 5:
            raise ValueError("Truncated varint (need 4 more bytes)")
        return int.from_bytes(data[1:5], "little"), 5

    # 0xFF → next 8 bytes
    if size == 0xFF:
        if len(data) < 9:
            raise ValueError("Truncated varint (need 8 more bytes)")
        return int.from_bytes(data[1:9], "little"), 9

    raise ValueError("Invalid varint size")


def encode_varint(n: int) -> bytes:
    """Encode varint."""
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def double_sha256(b: bytes) -> bytes:
    """Double sha256."""
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


###############################################################################
# P2P client implementation
###############################################################################


class P2PClient(QObject):
    """Async Bitcoin P2P client – now emits events for *all* standard messages."""

    # ------------------------------------------------------------------
    # Signals – one per message we explicitly parse, plus a generic fallback
    # ------------------------------------------------------------------

    signal_version = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_verack = cast(SignalProtocol[[]], pyqtSignal())
    signal_addr = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_addrv2 = cast(SignalProtocol[[bytes]], pyqtSignal(bytes))
    signal_sendaddrv2 = cast(SignalProtocol[[]], pyqtSignal())
    signal_inv = cast(SignalProtocol[[Inventory]], pyqtSignal(Inventory))
    signal_notfound = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_getdata = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_getblocks = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_getheaders = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_headers = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_block = cast(SignalProtocol[[str]], pyqtSignal(str))  # block hash
    signal_tx = cast(SignalProtocol[[bdk.Transaction]], pyqtSignal(bdk.Transaction))
    signal_getblocktxn = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_blocktxn = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_cmpctblock = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_sendcmpct = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_sendheaders = cast(SignalProtocol[[]], pyqtSignal())
    signal_ping = cast(SignalProtocol[[]], pyqtSignal())
    signal_pong = cast(SignalProtocol[[]], pyqtSignal())
    signal_mempool = cast(SignalProtocol[[]], pyqtSignal())
    signal_reject = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_filterload = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_filteradd = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_filterclear = cast(SignalProtocol[[]], pyqtSignal())
    signal_feefilter = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_wtxidrelay = cast(SignalProtocol[[]], pyqtSignal())
    signal_getcfheaders = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_cfheaders = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_getcfcheckpt = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_cfcheckpt = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_getcfilter = cast(SignalProtocol[[object]], pyqtSignal(object))
    signal_cfilter = cast(SignalProtocol[[object]], pyqtSignal(object))

    signal_unknown = cast(SignalProtocol[[str, bytes]], pyqtSignal(str, bytes))  # (command, raw_payload)

    signal_disconnected_to = cast(SignalProtocol[[Peer]], pyqtSignal(Peer))
    signal_try_connecting_to = cast(SignalProtocol[[ConnectionInfo]], pyqtSignal(ConnectionInfo))
    signal_current_peer_change = cast(SignalProtocol[[ConnectionInfo | None]], pyqtSignal(object))
    signal_received_peers = cast(SignalProtocol[[Peers]], pyqtSignal(Peers))

    # ------------------------------------------------------------------

    def __init__(
        self,
        network: bdk.Network,
        debug=True,
        fetch_txs=True,
        timeout: int = 200,
        parent: QObject | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.network = network
        self.timeout = timeout
        self.reader: StreamReader | None = None
        self.writer: StreamWriter | None = None
        self.fetch_txs = fetch_txs
        # DoS-protection state
        self._msg_times: collections.deque[float] = collections.deque()
        self._tx_times: collections.deque[float] = collections.deque()
        self._current_peer: Peer | None = None

        # call once
        self._DISPATCH_TABLE: dict[str, Callable[[Any], Coroutine[Any, Any, None]]] = {}
        self._init_dispatch()

        if debug:
            for name, sig in self.__class__.__dict__.items():
                if isinstance(sig, pyqtSignal):
                    getattr(self, name).connect(lambda *a, n=name: logger.debug(f"{n} {a}"))

        # signals
        self.signal_addrv2.connect(self._on_addrv2)  # incoming peers

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    async def connect(
        self,
        peer: Peer,
        proxy_info: ProxyInfo | None,
    ) -> None:
        """Establish a connection and send VERSION (+ optionally SENDADDRV2).

        Can raise Expceptions
        """
        logger.debug(f"Connecting to {peer}")
        self.signal_try_connecting_to.emit(ConnectionInfo(peer=peer, proxy_info=proxy_info))

        try:
            self.reader, self.writer = await self._connect(
                peer=peer, proxy_info=proxy_info, timeout=default_timeout(proxy_info)
            )
            self._current_peer = peer
        except asyncio.TimeoutError:
            logger.debug(f"Connection to {peer} timed-out")
            self.signal_disconnected_to.emit(peer)
            return

        logger.debug(f"Connected to {peer} - sending version")
        await self._send_raw("version", self._version_payload(peer))

        # BIP-155: announce ADDRv2 support *before* VERACK, exactly once
        await self._send_raw("sendaddrv2", b"")
        connection_info = ConnectionInfo(peer=peer, proxy_info=proxy_info)
        logger.info(f"Connected to {connection_info}")
        self.signal_current_peer_change.emit(connection_info)

    @classmethod
    async def _connect(
        cls,
        peer: Peer,
        proxy_info: ProxyInfo | None,
        timeout: float = 20,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """If proxy_info is None (or missing host/port), do a plain connection.

        If proxy_info.scheme starts with "socks", use aiohttp_socks.open_connection. Otherwise, fall back to
        direct asyncio.open_connection.
        """
        # 1) No proxy → plain open_connection
        if proxy_info is None:
            return await asyncio.wait_for(asyncio.open_connection(peer.host, peer.port), timeout=timeout)

        scheme = proxy_info.scheme.lower()

        # 2) SOCKS proxy (v4 or v5)
        if scheme.startswith("socks"):
            assert proxy_info.host is not None, "Proxy information incomplete"
            assert proxy_info.port is not None, "Proxy information incomplete"
            # aiohttp_socks will detect "socks4://" vs "socks5://" automatically
            return await asyncio.wait_for(
                socks_open_connection(
                    host=peer.host,
                    port=peer.port,
                    rdns=scheme.endswith("h"),  # remote DNS if "…h"
                    username=None,
                    password=None,
                    proxy_host=proxy_info.host,
                    proxy_port=proxy_info.port,
                ),
                timeout=timeout,
            )

        # 3) HTTP CONNECT proxy
        if scheme.startswith("http"):
            assert proxy_info.host is not None, "Proxy information incomplete"
            assert proxy_info.port is not None, "Proxy information incomplete"
            # Pass an "http://…" URL to open_connection; aiohttp_socks does the CONNECT.
            return await asyncio.wait_for(
                socks_open_connection(
                    proxy_host=proxy_info.host,
                    proxy_port=proxy_info.port,
                    host=peer.host,
                    port=peer.port,
                ),
                timeout=timeout,
            )

        # 4) Anything else is unsupported
        raise ValueError(f"Unsupported proxy scheme: {proxy_info.scheme!r}")

    async def disconnect(self) -> None:  # type: ignore
        """Close the underlying TCP connection *and* clear the reader/writer so that
        ``is_running()`` immediately reflects the new (disconnected) state."""
        if self.writer:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.debug("Timeout while waiting for writer to close")
            except Exception as e:
                logger.debug(f"Error while closing writer: {e}")

        self.reader = None
        self.writer = None
        logger.debug(f"Disconnected from {self._current_peer}")
        self._current_peer = None
        self.signal_current_peer_change.emit(None)

    # ------------------------------------------------------------------
    # Connection-state helper
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        """Return ``True`` while the client has an open TCP connection to its peer."""
        return bool(self.writer and not self.writer.is_closing())

    def current_peer(self) -> Peer | None:
        """Current peer."""
        return self._current_peer

    @staticmethod
    def make_core_user_agent() -> bytes:
        """Make core user agent."""
        versions = [f"{i}.0" for i in range(22, 28)]
        v = random.choice(versions)
        return f"/Satoshi:{v}/".encode()

    def _version_payload(self, peer: Peer) -> bytes:
        """Build the payload for an outgoing `version` message, handling IPv4, IPv6, Tor
        (.onion v2), and I2P (.i2p)."""

        def encode_address(host: str) -> bytes:
            """Convert *host* to the 16-byte 'network address' field used in the VERSION
            message.

            Supported forms
            ---------------
            • IPv4 literal             → ::ffff:IPv4
            • IPv6 literal             → raw 16-byte IPv6
            • Tor v2   <16×Base32>.onion
            • Tor v3   <56×Base32>.onion
            • I2P      <52×Base32>.i2p
            """
            h = host.lower().strip()

            # ── 1. Tor .onion ────────────────────────────────────────────
            if h.endswith(".onion"):
                b32 = h[:-6].upper()

                # v2: 16 Base32 chars → 10 bytes
                if len(b32) == 16:
                    raw = base64.b32decode(b32)
                    if len(raw) != 10:
                        raise ValueError("invalid v2 .onion length after decode")
                    prefix = bytes.fromhex("fd87d87eeb43")
                    return prefix + raw  # 6 + 10 = 16

                # v3: 56 Base32 chars → 35 bytes (32-byte pubkey + …)
                if len(b32) == 56:
                    raw = base64.b32decode(b32)
                    if len(raw) != 35:
                        raise ValueError("invalid v3 .onion length after decode")
                    pubkey = raw[:32]
                    digest = hashlib.sha3_256(pubkey).digest()  # BIP155 §3.1
                    prefix = bytes.fromhex("fd87d87eeb43")
                    return prefix + digest[:10]  # 6 + 10 = 16

                raise ValueError("unsupported .onion size (expect 16 or 56 Base32 chars)")

            # ── 2. I2P .i2p ─────────────────────────────────────────────
            if h.endswith(".i2p"):
                b32 = h[:-4].upper()
                raw = base64.b32decode(b32)
                if len(raw) < 10:
                    raise ValueError("decoded .i2p destination too short")
                prefix = bytes.fromhex("fd60db4dddb5")  # GarliCat /48
                return prefix + raw[:10]  # 6 + 10 = 16

            # ── 3. Plain IP literals ────────────────────────────────────
            try:
                ip = ipaddress.ip_address(host)
            except ValueError as exc:
                raise ValueError(f"unrecognised host format: {host!r}") from exc

            if ip.version == 4:
                return b"\x00" * 10 + b"\xff\xff" + ip.packed  # ::ffff:v4
            if ip.version == 6:
                return ip.packed

            raise ValueError("unknown IP version")

        #
        # — end of encode_address helper —
        #

        my_ip = "127.0.0.1"
        my_port = 8333

        version = 70016  # protocol version
        services = 1  # NODE_NETWORK
        timestamp = int(time.time())
        nonce = int.from_bytes(os.urandom(8), "little")
        user_agent = self.make_core_user_agent()
        start_height = 0
        relay = True

        # 1) Pack the version / services / timestamp (little‐endian)
        payload = struct.pack("<iQQ", version, services, timestamp)

        # 2) “addr_recv” (the remote peer’s address):
        #    • services (8 bytes little‐endian)
        #    • 16 byte “IPv6” field (whatever encode_address returns)
        #    • 2 byte port (big‐endian)
        #
        addr_recv_services = services
        addr_recv_ipbytes = encode_address(peer.host)
        addr_recv_port = peer.port

        payload += struct.pack("<Q", addr_recv_services)
        payload += addr_recv_ipbytes
        payload += struct.pack(">H", addr_recv_port)

        # 3) “addr_from” (our own address):
        payload += struct.pack("<Q", services)
        payload += encode_address(my_ip)  # our loopback address
        payload += struct.pack(">H", my_port)

        # 4) nonce
        payload += struct.pack("<Q", nonce)

        # 5) user_agent (varint length + bytes)
        payload += encode_varint(len(user_agent)) + user_agent

        # 6) start_height + relay flag (little‐endian)
        payload += struct.pack("<i?", start_height, relay)

        return payload

    # ------------------------------------------------------------------
    # Public helpers / high‑level API
    # ------------------------------------------------------------------
    async def request_addresses(self) -> None:
        """Ask the peer for its address table.

        Call this only after VERACK.
        """
        await self._send_raw("getaddr", b"")  # ← nothing else here

    async def broadcast_tx(self, raw_hex: str) -> None:
        """Broadcast tx."""
        try:
            raw = bytes.fromhex(raw_hex)
        except ValueError:
            logger.debug(f"Invalid hex in broadcast_tx: {raw_hex!r}")
            return
        await self._send_raw("tx", raw)

    async def getdata(self, inventory: Inventory) -> None:
        """Request data for the given inventory, *preferring witness* encodings (BIP144)
        when asking for txs/blocks."""
        if not self.writer:
            logger.debug("Writer not initialised – cannot request data")
            return

        # Prefer witness types when requesting tx/block data.
        upgraded = Inventory()
        for item in inventory:
            if item.type == InventoryType.MSG_TX:
                new_type = InventoryType.MSG_WITNESS_TX
            elif item.type == InventoryType.MSG_BLOCK:
                new_type = InventoryType.MSG_WITNESS_BLOCK
            else:
                new_type = item.type
            upgraded.append(InventoryItem(type=new_type, payload=item.payload))

        await self._send_raw("getdata", self._serialize_inv(upgraded))

    async def request_headers(self, *hashes_be: str) -> None:
        """Request headers."""
        if not hashes_be:
            raise ValueError("Need at least one locator hash")
        payload = encode_varint(len(hashes_be))
        payload += b"".join(bytes.fromhex(h)[::-1] for h in hashes_be)
        payload += b"\x00" * 32  # stop hash = null
        await self._send_raw("getheaders", payload)

    async def request_mempool(self) -> None:
        """Request mempool."""
        await self._send_raw("mempool", b"")

    # ------------------------------------------------------------------
    # Main receive loop
    # ------------------------------------------------------------------

    async def listen_forever(self) -> None:
        """Listen forever."""
        while self.is_running():
            await self._read_message()

    # ------------------------------------------------------------------
    # Low‑level framing
    # ------------------------------------------------------------------
    async def _send_raw(self, cmd: str, payload: bytes) -> None:
        """Send a raw Bitcoin P2P message **with a timeout applied to the drain()
        call**."""
        if not self.writer:
            return

        magic = MAGIC_VALUES[self.network]
        header = (
            struct.pack(">L", magic)
            + struct.pack("12s", cmd.encode())
            + struct.pack("<L", len(payload))
            + double_sha256(payload)[:4]
        )

        self.writer.write(header + payload)
        try:
            # ──────────────────────────────────────────────────────────────
            # Enforce I/O-level timeout on the actual socket flush
            # ──────────────────────────────────────────────────────────────
            await asyncio.wait_for(self.writer.drain(), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.debug(f"-> {cmd} timed-out after {self.timeout} s during drain()")
            await self.disconnect()
            return

        logger.debug(f"-> {cmd} ({len(payload)} bytes)")

    async def _read_exact(self, n: int) -> bytes:
        """Read *exactly* ``n`` bytes from the peer, timing-out (and disconnecting) if
        the peer stays silent for longer than ``self.timeout`` seconds."""
        if not self.reader:
            return b""

        data = b""
        while len(data) < n:
            try:
                # ──────────────────────────────────────────────────────────
                # Apply the same per-operation timeout on reads
                # ──────────────────────────────────────────────────────────
                chunk = await asyncio.wait_for(self.reader.readexactly(n - len(data)), timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.debug(f"<- read timed-out after {self.timeout} s")
                await self.disconnect()
                raise
            except asyncio.exceptions.IncompleteReadError as e:
                # e.partial is a bytes object containing however many bytes arrived
                logger.debug(
                    f"Peer closed early — got {len(e.partial)}/{n - len(data)} header bytes: {e.partial!r}",
                )
                raise

            if not chunk:
                raise ConnectionError("Connection closed by peer")
            data += chunk
        return data

    # ────────────────────────────────────────────────────────────────
    # Sliding-window rate-limiter (O(1))
    # ────────────────────────────────────────────────────────────────
    def _enforce_rate_limit(
        self,
        dq: collections.deque[float],
        max_per_sec: int,
        label: str,
    ) -> None:
        """Enforce rate limit."""
        now = time.monotonic()
        dq.append(now)

        # throw away timestamps that fell out of the window
        cutoff = now - RATE_WINDOW_SEC
        while dq and dq[0] < cutoff:
            dq.popleft()

        if len(dq) > max_per_sec:
            logger.debug(
                f"Peer exceeded {label} rate limit ({len(dq)} > {max_per_sec} in {RATE_WINDOW_SEC:.1f}s) – disconnecting"
            )
            # schedule an async disconnect without blocking
            asyncio.create_task(self.disconnect())

    async def _read_message(self) -> None:
        """
        Read one full P2P message: header + payload, with
        magic/checksum verification, size limits, rate-limiting,
        and dispatch to the appropriate handler.


        Can raise Expceptions
        """
        if not self.reader:
            return

        # 1) Read the 24-byte header
        header = await self._read_exact(24)

        # ── HARDENING: verify network magic
        magic_recv = struct.unpack(">L", header[0:4])[0]
        expected_magic = MAGIC_VALUES[self.network]
        if magic_recv != expected_magic:
            logger.debug(f"Wrong magic {magic_recv:08x} ≠ {expected_magic:08x} – disconnecting")
            await self.disconnect()
            return

        # 2) Parse command and payload length
        cmd = header[4:16].rstrip(b"\x00").decode(errors="ignore")
        length = struct.unpack("<L", header[16:20])[0]

        # ── HARDENING: reject over-large payloads
        if length > MAX_PAYLOAD_LEN:
            logger.debug(f"Payload {length} bytes for {cmd} exceeds {MAX_PAYLOAD_LEN} – disconnecting")
            await self.disconnect()
            return

        # 3) Read the payload
        payload = await self._read_exact(length) if length else b""

        # ── HARDENING: checksum verification
        checksum_recv = header[20:24]
        checksum_calc = double_sha256(payload)[:4]
        if checksum_recv != checksum_calc:
            logger.debug(f"Bad checksum for {cmd} – disconnecting")
            await self.disconnect()
            return

        logger.debug(f"<- {cmd} ({length} bytes)")

        # 4) Generic rate limiter
        self._enforce_rate_limit(self._msg_times, MAX_MSGS_PER_SEC, "message")

        # 5) Specific TX spam limiter
        if cmd == "tx":
            self._enforce_rate_limit(self._tx_times, MAX_TXS_PER_SEC, "tx")

        # 6) Dispatch safely
        await self._dispatch(cmd, payload)

    # ------------------------------------------------------------------
    # Dispatcher & handlers
    # ------------------------------------------------------------------

    def _init_dispatch(self) -> None:
        """Init dispatch."""
        mapping = {
            "version": self._handle_version,
            "verack": self._handle_verack,
            "ping": self._handle_ping,
            "pong": self._handle_pong,
            "sendheaders": self._handle_sendheaders,
            "sendcmpct": self._handle_sendcmpct,
            "addr": self._handle_addr,
            "addrv2": self._handle_addrv2,
            "sendaddrv2": self._handle_sendaddrv2,
            "inv": self._handle_inv,
            "notfound": self._handle_notfound,
            "getdata": self._handle_getdata,
            "getblocks": self._handle_getblocks,
            "getheaders": self._handle_getheaders,  # raw
            "headers": self._handle_headers,
            "tx": self._handle_tx,
            "block": self._handle_block,
            "mempool": self._handle_mempool,
            "reject": self._handle_reject,
            "filterload": self._handle_filterload,
            "filteradd": self._handle_filteradd,
            "filterclear": self._handle_filterclear,
            "feefilter": self._handle_feefilter,
            "getcfheaders": self._handle_getcfheaders,
            "cfheaders": self._handle_cfheaders,
            "getcfcheckpt": self._handle_getcfcheckpt,
            "cfcheckpt": self._handle_cfcheckpt,
            "getcfilter": self._handle_getcfilter,
            "cfilter": self._handle_cfilter,
            "wtxidrelay": self._handle_wtxidrelay,
            "cmpctblock": self._handle_cmpctblock,
            "getblocktxn": self._handle_getblocktxn,
            "blocktxn": self._handle_blocktxn,
        }
        self._DISPATCH_TABLE.update(mapping)

    async def _dispatch(self, cmd: str, payload: bytes) -> None:
        # ensure non-empty name
        """Dispatch."""
        safe_cmd = cmd or "<?>"
        handler = self._DISPATCH_TABLE.get(safe_cmd)
        if handler is None:
            # call unknown
            try:
                self.signal_unknown.emit(safe_cmd, payload)
            except Exception as e:
                logger.debug(f"Error emitting unknown for {safe_cmd}: {e}")
                await self.disconnect()
            return

        try:
            await handler(payload)
        except Exception as e:
            logger.debug(f"Error handling {safe_cmd}: {e} – disconnecting")
            await self.disconnect()

    # Individual handlers ------------------------------------------------------------------

    async def _handle_version(self, p: bytes) -> None:
        """Handle version."""
        self.signal_version.emit(self._decode_version(p))
        await self._send_raw("verack", b"")

    async def _handle_verack(self, p: bytes) -> None:
        """Handle verack."""
        self.signal_verack.emit()

        # Immediately (and silently) ask for the address list.
        # We schedule it as a background task so `_handle_verack`
        # returns fast and the receive-loop doesn’t stall.
        asyncio.create_task(self.request_addresses())

    async def _handle_ping(self, p: bytes) -> None:
        """Handle ping."""
        self.signal_ping.emit()
        await self._send_raw("pong", p[:8])

    async def _handle_pong(self, p: bytes) -> None:
        """Handle pong."""
        self.signal_pong.emit()

    async def _handle_sendheaders(self, p: bytes) -> None:
        """Handle sendheaders."""
        self.signal_sendheaders.emit()

    async def _handle_sendcmpct(self, p: bytes) -> None:
        # 1 byte: announce bool, 8 bytes: version
        """Handle sendcmpct."""
        if len(p) >= 9:
            announce, version = struct.unpack("<BQ", p[:9])
            self.signal_sendcmpct.emit({"announce": bool(announce), "version": version})
        else:
            self.signal_sendcmpct.emit({"raw": p})

    async def _handle_addr(self, p: bytes) -> None:
        """Handle addr."""
        self.signal_addr.emit(self._parse_addr_like(p))

    async def _handle_addrv2(self, p: bytes) -> None:
        """Handle addrv2."""
        self.signal_addrv2.emit(p)  # complex; emit raw

    async def _handle_sendaddrv2(self, p: bytes) -> None:
        """Handle sendaddrv2."""
        self.signal_sendaddrv2.emit()

    async def _handle_inv(self, p: bytes) -> None:
        """Handle inv."""
        inventory = self._parse_inv(p)
        self.signal_inv.emit(inventory)

    async def _handle_notfound(self, p: bytes) -> None:
        """Handle notfound."""
        self.signal_notfound.emit(self._parse_inv(p))

    async def _handle_getdata(self, p: bytes) -> None:
        """Handle getdata."""
        self.signal_getdata.emit(self._parse_inv(p))

    async def _handle_getblocks(self, p: bytes) -> None:
        """Handle getblocks."""
        self.signal_getblocks.emit(p)  # rare to receive; raw

    async def _handle_tx(self, p: bytes) -> None:
        """Handle tx."""
        self.signal_tx.emit(bdk.Transaction(p))

    async def _handle_block(self, p: bytes) -> None:
        """Handle block."""
        blk_hash = double_sha256(p[:80])[::-1].hex()
        self.signal_block.emit(blk_hash)

    async def _handle_headers(self, p: bytes) -> None:
        """Handle headers."""
        self.signal_headers.emit(p)

    async def _handle_mempool(self, p: bytes) -> None:
        """Handle mempool."""
        self.signal_mempool.emit()

    async def _handle_reject(self, p: bytes) -> None:
        """Handle reject."""
        self.signal_reject.emit(p)

    async def _handle_filterload(self, p: bytes) -> None:
        """Handle filterload."""
        self.signal_filterload.emit(p)

    async def _handle_filteradd(self, p: bytes) -> None:
        """Handle filteradd."""
        self.signal_filteradd.emit(p)

    async def _handle_filterclear(self, p: bytes) -> None:
        """Handle filterclear."""
        self.signal_filterclear.emit()

    async def _handle_feefilter(self, p: bytes) -> None:
        """Handle feefilter."""
        if len(p) == 8:
            (feerate,) = struct.unpack("<Q", p)
            self.signal_feefilter.emit(feerate)

    async def _handle_getcfheaders(self, p: bytes) -> None:
        """Handle getcfheaders."""
        self.signal_getcfheaders.emit(p)

    async def _handle_cfheaders(self, p: bytes) -> None:
        """Handle cfheaders."""
        self.signal_cfheaders.emit(p)

    async def _handle_getcfcheckpt(self, p: bytes) -> None:
        """Handle getcfcheckpt."""
        self.signal_getcfcheckpt.emit(p)

    async def _handle_cfcheckpt(self, p: bytes) -> None:
        """Handle cfcheckpt."""
        self.signal_cfcheckpt.emit(p)

    async def _handle_getcfilter(self, p: bytes) -> None:
        """Handle getcfilter."""
        self.signal_getcfilter.emit(p)

    async def _handle_cfilter(self, p: bytes) -> None:
        """Handle cfilter."""
        self.signal_cfilter.emit(p)

    async def _handle_wtxidrelay(self, p: bytes) -> None:
        """Handle wtxidrelay."""
        self.signal_wtxidrelay.emit()

    async def _handle_cmpctblock(self, p: bytes) -> None:
        """Handle cmpctblock."""
        self.signal_cmpctblock.emit(p)

    async def _handle_getblocktxn(self, p: bytes) -> None:
        """Handle getblocktxn."""
        self.signal_getblocktxn.emit(p)

    async def _handle_blocktxn(self, p: bytes) -> None:
        """Handle blocktxn."""
        self.signal_blocktxn.emit(p)

    async def _handle_unknown(self, p: bytes, cmd: str | None = None) -> None:  # type: ignore[override]
        """Handle unknown."""
        self.signal_unknown.emit(cmd or "?", p)

    async def _handle_getheaders(self, p: bytes) -> None:
        """Handle an incoming `getheaders` request."""
        # Emit the raw payload so higher-level code can inspect
        # locator hashes and stop-hash if desired.
        self.signal_getheaders.emit(p)

    # ------------------------------------------------------------------
    # Shared parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_inv(p: bytes) -> Inventory:
        """Parse inv."""
        items = Inventory()
        count, consumed = decode_varint(p)

        # Cap insane lists early
        if count > MAX_INV_ITEMS:
            raise ValueError(f"inv list too large ({count} > {MAX_INV_ITEMS})")

        for i in range(count):
            inv_type_int, h = struct.unpack_from("<I32s", p, consumed + i * 36)
            if not isinstance(h, bytes):
                logger.debug(f"expected bytes, but got {h=}")
                continue
            items.append(
                InventoryItem(type=InventoryType(inv_type_int), payload=h[::-1].hex())
            )  # convert to big‑endian for caller
        return items

    @staticmethod
    def _serialize_inv(inventory: Inventory) -> bytes:
        """
        Serialize a list of InventoryItem back into the same format that _parse_inv expects:
        [ varint(count) ][ entries... ]
        where each entry is:
        <I   : 4-byte little-endian unsigned int (InventoryType)
        32s : 32-byte payload >
        The InventoryItem.payload is assumed to be a big-endian hex string of length 64.
        """
        # 1) encode count as varint
        out = bytearray()
        out += encode_varint(len(inventory))

        # 2) for each item, pack type and payload
        for item in inventory:
            # InventoryType → its integer value
            type_int = item.type.value

            # hex → bytes, convert from big-endian to little-endian
            data = bytes.fromhex(item.payload)
            if len(data) != 32:
                raise ValueError(f"expected 32-byte payload, got {len(data)} bytes")
            data_le = data[::-1]

            # pack and append
            out += struct.pack("<I32s", type_int, data_le)

        return bytes(out)

    @staticmethod
    def _parse_addr_like(p: bytes) -> list[tuple[str, int]]:
        """Parse addr like."""
        addrs: list[tuple[str, int]] = []
        count, off = decode_varint(p)

        # ── HARDENING: cap and log
        if count > MAX_ADDR_ITEMS:
            logger.debug(f"addr list claims {count} entries; truncating to {MAX_ADDR_ITEMS}")
        count = min(count, MAX_ADDR_ITEMS)

        # ── HARDENING: ensure we have enough bytes for all entries
        expected_len = off + count * 30
        if len(p) < expected_len:
            logger.debug(
                f"addr payload too short: need {expected_len} bytes, have {len(p)}; parsing what we can"
            )
            # reduce count to whatever fits
            count = max((len(p) - off) // 30, 0)

        for i in range(count):
            base = off + i * 30
            ip = socket.inet_ntop(socket.AF_INET6, p[base + 12 : base + 28])
            port = struct.unpack(">H", p[base + 28 : base + 30])[0]
            addrs.append((ip, port))
        return addrs

    @staticmethod
    def _decode_version(p: bytes) -> dict[str, Any]:
        # https://en.bitcoin.it/wiki/Protocol_documentation#version

        # 1) version, services, timestamp (4 + 8 + 8 = 20 bytes)
        """Decode version."""
        version, services, ts = struct.unpack_from("<iQQ", p, 0)
        off = 20

        # 2) addr_recv (26 bytes)
        #  2a) recv_services (8 bytes)
        (_,) = struct.unpack_from("<Q", p, off)
        off += 8
        #  2b) recv_IP (16 bytes)
        addr_recv = socket.inet_ntop(socket.AF_INET6, p[off : off + 16])
        off += 16
        #  2c) recv_port (2 bytes, big-endian)
        (port_recv,) = struct.unpack_from(">H", p, off)
        off += 2

        # 3) addr_from (26 bytes)
        #  3a) from_services (8 bytes)
        (_,) = struct.unpack_from("<Q", p, off)
        off += 8
        #  3b) from_IP (16 bytes)
        addr_from = socket.inet_ntop(socket.AF_INET6, p[off : off + 16])
        off += 16
        #  3c) from_port (2 bytes)
        (port_from,) = struct.unpack_from(">H", p, off)
        off += 2

        # 4) nonce (8 bytes)
        (nonce,) = struct.unpack_from("<Q", p, off)
        off += 8

        # 5) user_agent (var_str)
        ua_len, varint_len = decode_varint(p[off:])
        MAX_UA_LEN = 256
        if ua_len > MAX_UA_LEN:
            logger.debug(f"User-Agent too long ({ua_len} > {MAX_UA_LEN}), truncating")
            ua_len = MAX_UA_LEN
        off += varint_len
        user_agent = p[off : off + ua_len].decode(errors="replace")
        off += ua_len

        # 6) start_height (4 bytes)
        (start_height,) = struct.unpack_from("<i", p, off)
        off += 4

        # 7) relay flag (optional, 1 byte) – only if version ≥ 70001
        #    you may need to check payload length before reading it.

        return {
            "version": version,
            "services": services,
            "time": ts,
            "addr_recv": addr_recv,
            "port_recv": port_recv,
            "addr_from": addr_from,
            "port_from": port_from,
            "nonce": nonce,
            "user_agent": user_agent,
            "start_height": start_height,
        }

    def _on_addrv2(self, payload: bytes):
        """Decode a BIP-155 ADDRv2 message (payload only) and remember the peers it
        contains.

        We handle the most common network IDs:
        1 = IPv4
        2 = IPv6
        3 = Tor v2
        4 = Tor v3
        5 = I2P
        """
        received_peers = Peers()
        try:
            count, off = decode_varint(payload)
        except Exception as exc:
            logger.debug(f"Malformed addrv2 varint: {exc}")
            return received_peers

        # ── HARDENING: cap reported count
        if count > MAX_ADDR_ITEMS:
            logger.debug(f"addrv2 claims {count} entries; truncating to {MAX_ADDR_ITEMS}")
            count = MAX_ADDR_ITEMS

        for _ in range(count):
            if off + 4 > len(payload):  # timestamp
                break
            off += 4

            # services (varint, ignored here)
            _, consumed = decode_varint(payload[off:])
            off += consumed

            if off >= len(payload):
                break
            network_id = payload[off]
            off += 1

            addr_len, consumed = decode_varint(payload[off:])
            off += consumed

            addr_bytes = payload[off : off + addr_len]
            off += addr_len

            if off + 2 > len(payload):
                break
            port = int.from_bytes(payload[off : off + 2], "big")
            off += 2

            # ─── convert to printable host string ────────────────
            try:
                if network_id == 1 and addr_len == 4:  # IPv4
                    host = socket.inet_ntop(socket.AF_INET, addr_bytes)
                elif network_id == 2 and addr_len == 16:  # IPv6
                    host = socket.inet_ntop(socket.AF_INET6, addr_bytes)
                elif network_id == 3 and addr_len == 10:  # Tor v2
                    host = base64.b32encode(addr_bytes).decode("ascii").lower() + ".onion"
                elif network_id == 4 and addr_len == 32:  # Tor v3
                    host = base64.b32encode(addr_bytes).decode("ascii").lower() + ".onion"
                elif network_id == 5 and addr_len == 32:  # I2P
                    host = base64.b32encode(addr_bytes).decode("ascii").lower() + ".i2p"
                else:
                    # network IDs 6+ are rare – skip unknowns
                    continue
            except Exception:
                continue

            peer = Peer(host=host, port=port)
            if peer not in received_peers:
                received_peers.append(peer)
        logger.debug(f"Received { len(received_peers)=} peers")
        self.signal_received_peers.emit(received_peers)
