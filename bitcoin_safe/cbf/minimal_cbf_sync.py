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
"""Minimal script to sync a descriptor using BDK compact block filters."""

import argparse
import asyncio
import tempfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import cast

import bdkpython as bdk


def parse_args() -> argparse.Namespace:
    """Parse args."""
    parser = argparse.ArgumentParser(
        description="Sync a descriptor using BDK compact block filters.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("descriptor", help="External descriptor string (usually ending with /0/*)")
    parser.add_argument(
        "change_descriptor",
        help="Internal/change descriptor string (usually ending with /1/*)",
    )
    parser.add_argument(
        "--network",
        default="signet",
        choices=[network.name.lower() for network in bdk.Network],
        help="Bitcoin network to use",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory where headers/peer data should be stored",
    )
    parser.add_argument(
        "--wallet-persistence",
        default=None,
        help="Path to the sqlite file storing wallet state (defaults to <data-dir>/wallet.sqlite)",
    )
    parser.add_argument(
        "--connections",
        type=int,
        default=2,
        help="Number of peer connections the light client should maintain",
    )
    parser.add_argument(
        "--peer",
        action="append",
        dest="peers",
        default=[],
        help="Optional peer in the form IPv4:port. Repeat for multiple peers.",
    )
    parser.add_argument(
        "--new-wallet",
        action="store_true",
        help="Force using the NEW scan type even if the wallet has state",
    )
    parser.add_argument(
        "--recovery-height",
        type=int,
        default=None,
        help="Block height to start recovering from. Sets the RECOVERY scan type.",
    )
    parser.add_argument(
        "--reveal",
        type=int,
        default=1,
        help="Number of external addresses to reveal before syncing",
    )
    return parser.parse_args()


def parse_peer(peer: str) -> bdk.Peer:
    """Parse peer."""
    host, _, port_str = peer.partition(":")
    if not port_str:
        raise ValueError(f"Peer '{peer}' must be in the form host:port")
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError(f"Invalid port in peer '{peer}'") from exc

    octets = host.split(".")
    if len(octets) != 4:
        raise ValueError(f"Only IPv4 peers are supported in this demo script. Got '{host}'.")
    try:
        ipv4 = bdk.IpAddress.from_ipv4(*(int(o) for o in octets))
    except ValueError as exc:
        raise ValueError(f"Invalid IPv4 peer '{peer}'") from exc

    return bdk.Peer(address=ipv4, port=port, v2_transport=False)


def build_peers(peer_strings: Iterable[str]) -> list[bdk.Peer]:
    """Build peers."""
    peers: list[bdk.Peer] = []
    for peer_str in peer_strings:
        try:
            peers.append(parse_peer(peer_str))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    return peers


async def stream_client_messages(client: bdk.CbfClient) -> None:
    """Stream client messages."""

    async def log_stream(prefix: str, getter):
        """Log stream."""
        while True:
            try:
                item = await getter()
            except asyncio.CancelledError:
                break
            if item is None:
                continue
            print(f"[{prefix}] {item}")

    tasks = [
        asyncio.create_task(log_stream("INFO", client.next_info)),
        asyncio.create_task(log_stream("WARNING", client.next_warning)),
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def run_sync(args: argparse.Namespace) -> None:
    """Run sync."""
    network = bdk.Network[args.network.upper()]

    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp())
    data_dir.mkdir(parents=True, exist_ok=True)

    persister = bdk.Persister.new_in_memory()

    descriptor = bdk.Descriptor(args.descriptor, network=network)
    change_descriptor = bdk.Descriptor(args.change_descriptor, network=network)

    wallet = bdk.Wallet(
        descriptor=descriptor,
        change_descriptor=change_descriptor,
        network=network,
        persister=persister,
    )

    reveal_count = max(0, args.reveal)
    if reveal_count:
        last_index = reveal_count - 1
        wallet.reveal_addresses_to(bdk.KeychainKind.EXTERNAL, last_index)
        wallet.persist(persister)

    if args.recovery_height is not None:
        scan_type = bdk.ScanType.RECOVERY(
            used_script_index=100, checkpoint=bdk.RecoveryPoint.SEGWIT_ACTIVATION
        )
    elif args.new_wallet or wallet.latest_checkpoint().height == 0:
        scan_type = bdk.ScanType.RECOVERY(
            used_script_index=100, checkpoint=bdk.RecoveryPoint.TAPROOT_ACTIVATION
        )
    else:
        scan_type = bdk.ScanType.SYNC()

    scan_type = cast(bdk.ScanType, scan_type)
    builder = bdk.CbfBuilder().scan_type(scan_type).data_dir(str(data_dir)).connections(args.connections)

    peers = build_peers(args.peers)
    if peers:
        builder = builder.peers(peers)

    components = builder.build(wallet)
    client = components.client
    node = components.node

    node.run()

    message_task = asyncio.create_task(stream_client_messages(client))

    start_time = datetime.now()
    print(f"Sync started at {start_time.isoformat()}")

    try:
        update = await client.update()
        wallet.apply_update(update)
        wallet.persist(persister)
    finally:
        client.shutdown()
        message_task.cancel()
        await asyncio.gather(message_task, return_exceptions=True)

    finish_time = datetime.now()
    duration = finish_time - start_time

    balance = wallet.balance().total.to_sat()
    print(f"Sync finished at {finish_time.isoformat()} (duration {duration})")
    print(f"Wallet balance: {balance} sat")
    for tx in wallet.transactions():
        print(f"Tx: {tx.transaction.compute_txid()}  Fee: {wallet.calculate_fee(tx.transaction).to_sat()}")


def main() -> None:
    """Main."""
    args = parse_args()
    try:
        asyncio.run(run_sync(args))
    except KeyboardInterrupt:
        print("Interrupted by user")


if __name__ == "__main__":
    main()
