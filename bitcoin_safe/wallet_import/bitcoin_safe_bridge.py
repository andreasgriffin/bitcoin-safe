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

"""Convert imported public wallet data into Bitcoin Safe models."""

from __future__ import annotations

import json
from collections import Counter

import bdkpython as bdk
from bitcoin_safe_lib.util import network_kind

from bitcoin_safe.hardware_signers import HardwareSigners
from bitcoin_safe.wallet import ProtoWallet, Wallet

from .model import ExchangeError, WalletExchange

NETWORKS = {
    "mainnet": bdk.Network.BITCOIN,
    "testnet": bdk.Network.TESTNET,
    "testnet4": bdk.Network.TESTNET4,
    "regtest": bdk.Network.REGTEST,
    "signet": bdk.Network.SIGNET,
}


def make_protowallet(exchange: WalletExchange, wallet_id: str, network: bdk.Network) -> ProtoWallet:
    """Build a proto wallet only when Bitcoin Safe preserves the source policy."""
    if not exchange.descriptor:
        raise ExchangeError(
            "This account has no complete receive and change descriptor. Export a descriptor from the source wallet."
        )
    if exchange.source_wallet == "electrum":
        from .electrum import missing_cosigner_origins

        missing = missing_cosigner_origins(exchange)
        if missing:
            signers = ", ".join(str(index) for index in missing)
            raise ExchangeError(
                f"Electrum signer(s) {signers} lack a master fingerprint or derivation path. "
                "Obtain these from the original signers; they cannot be derived from an account xpub."
            )
    fingerprints: dict[str, str | None] = {}
    for source_signer in exchange.keystores:
        if not source_signer.fingerprint:
            continue
        fingerprint = source_signer.fingerprint.lower()
        if fingerprint in fingerprints and fingerprints[fingerprint] != source_signer.xpub:
            raise ExchangeError(
                "Distinct signers have the same master fingerprint; check the genuine signer fingerprints."
            )
        fingerprints[fingerprint] = source_signer.xpub
    try:
        original = bdk.Descriptor(exchange.descriptor, network_kind(network))
        proto = ProtoWallet.from_descriptor(wallet_id, exchange.descriptor, network)
        rebuilt = proto.to_multipath_descriptor()
        if rebuilt is None:
            raise ValueError("Incomplete wallet descriptor")
        # Comparing canonical descriptors, rather than a sample of addresses,
        # also catches changed key ordering, derivation paths, and policy.
        original_branches = original.to_single_descriptors()
        rebuilt_branches = rebuilt.to_single_descriptors()
        if len(original_branches) != 2 or [str(d) for d in original_branches] != [
            str(d) for d in rebuilt_branches
        ]:
            raise ValueError("Bitcoin Safe cannot preserve this descriptor policy")
    except Exception as exc:
        raise ExchangeError(f"Unsupported wallet descriptor: {exc}") from exc
    proto.gap = exchange.gap_limit if exchange.gap_limit and exchange.gap_limit > 0 else 20
    for source in exchange.keystores:
        for target in proto.keystores:
            if target is not None and target.xpub == source.xpub:
                if source.non_mainnet_seed:
                    if network == bdk.Network.BITCOIN or exchange.network in ("mainnet", "unknown"):
                        raise ExchangeError("Refusing to import seed on mainnet or unknown network")
                    from .sparrow_seed_public import recover_bip39_public_key

                    if (
                        not source.xpub
                        or not source.key_origin
                        or not recover_bip39_public_key(source, source.non_mainnet_seed, exchange.network)
                    ):
                        raise ExchangeError("Cannot verify imported BIP39 signer")
                    if (
                        not source.fingerprint
                        or target.fingerprint.lower() != source.fingerprint.lower()
                        or target.key_origin != source.key_origin
                    ):
                        raise ExchangeError("BIP39 signer origin does not match the wallet descriptor")
                    target.mnemonic = source.non_mainnet_seed
                if source.label:
                    target.description = source.label
                if source.device_type:
                    signer = HardwareSigners.from_id(source.device_type.lower())
                    if signer:
                        target.hardware_signer_id = signer.id
                break
    return proto


def label_import_data(exchange: WalletExchange) -> tuple[str, list[str]]:
    """Prepare unambiguous BIP-329 labels and describe unsupported metadata."""
    supported = {"tx", "addr", "pubkey", "input", "output", "xpub"}
    warnings = []
    for label_type in sorted({label.type for label in exchange.labels} - supported):
        warnings.append(f"Bitcoin Safe does not currently import {label_type} labels")
    counts = Counter(label.ref for label in exchange.labels if label.type in supported)
    ambiguous = {ref for ref, count in counts.items() if count > 1}
    if ambiguous:
        warnings.append(f"Skipped {len(ambiguous)} ambiguous label references shared across records")
    filtered = [
        label.to_bip329()
        for label in exchange.labels
        if label.type in supported and label.ref not in ambiguous
    ]
    if (
        exchange.next_receive_index is not None
        or exchange.next_change_index is not None
        or exchange.birth_height is not None
    ):
        warnings.append(
            "Saved address indexes and birth height are not imported; check the wallet history after the full scan."
        )
    if exchange.extra.get("unresolved_node_labels") or exchange.extra.get("unclassified_label_refs"):
        warnings.append("Some source labels could not be associated with wallet addresses or transactions.")
    if (
        exchange.frozen_addresses
        or exchange.frozen_outpoints
        or any(label.spendable is False for label in exchange.labels)
    ):
        warnings.append("Frozen addresses and coins are not protected from spending in Bitcoin Safe.")
    return "\n".join(json.dumps(label, ensure_ascii=False) for label in filtered), warnings


def apply_bip329_labels(wallet: Wallet, exchange: WalletExchange) -> list[str]:
    """Apply supported labels before the wallet is first saved and synced."""
    blob, warnings = label_import_data(exchange)
    if blob:
        wallet.labels.import_bip329_jsonlines(blob)
    return warnings
