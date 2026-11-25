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

"""Foreign input data and PSBT metadata.

P2WPKH inputs can be imported without an owning wallet descriptor. P2WSH,
Taproot, legacy and nested inputs require a matching loaded wallet descriptor
so their scripts and maximum satisfaction weight can be determined safely.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import bdkpython as bdk
from bitcoin_safe_lib.storage import BaseSaveableClass
from bitcoin_safe_lib.util import network_kind

from .pythonbdk_types import OutPoint, PythonUtxo, TxOut, robust_address_str_from_txout

P2WPKH_EXAMPLE_DESCRIPTOR = "wpkh(0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798)"


@dataclass
class ForeignUtxo(BaseSaveableClass):
    utxo: PythonUtxo
    psbt_input: bdk.Input
    satisfaction_weight: int
    wallet_id: str | None

    def dump(self) -> dict[str, Any]:
        d = super().dump()
        d.update(
            outpoint=str(self.utxo.outpoint),
            address=self.utxo.address,
            txout=self.utxo.txout.seralized_tuple(),
            psbt=self._serialize_input(),
            satisfaction_weight=self.satisfaction_weight,
            wallet_id=self.wallet_id,
        )
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> ForeignUtxo:
        super()._from_dump(dct, class_kwargs=class_kwargs)
        utxo = PythonUtxo(
            address=dct["address"],
            outpoint=OutPoint.from_str(dct["outpoint"]),
            txout=TxOut.from_seralized_tuple(dct["txout"]),
        )
        psbt_input = bdk.Psbt(dct["psbt"]).input()[0]
        return cls(utxo, psbt_input, dct["satisfaction_weight"], dct["wallet_id"])

    @classmethod
    def from_outpoint(
        cls,
        outpoint: OutPoint,
        txout: bdk.TxOut,
        transaction: bdk.Transaction | None,
        wallets: Sequence[tuple[str, bdk.Wallet]],
        network: bdk.Network,
    ) -> ForeignUtxo:
        script = bytes(txout.script_pubkey.to_bytes())
        psbt_input = cls._empty_input(txout, transaction)
        weight: int | None = None
        wallet_id: str | None = None
        for candidate_wallet_id, bdk_wallet in wallets:
            derivation = bdk_wallet.derivation_of_spk(txout.script_pubkey)
            if derivation is None:
                continue
            descriptor = bdk.Descriptor(
                bdk_wallet.public_descriptor(derivation.keychain), network_kind(network)
            )
            derived = descriptor.derive_address(derivation.index, network).script_pubkey()
            if bytes(derived.to_bytes()) != script:
                raise ValueError("Wallet descriptor does not match the output script")

            weight = descriptor.max_weight_to_satisfy()
            wallet_id = candidate_wallet_id
            # Ask the owning wallet to populate derivation and script metadata where possible.
            try:
                psbt_input = cls._wallet_input_metadata(bdk_wallet, outpoint, txout)
                psbt_input.non_witness_utxo = transaction
                if psbt_input.witness_utxo is not None:
                    psbt_input.witness_utxo = txout
            except Exception as exc:
                raise ValueError(f"Could not obtain the owning wallet's PSBT metadata: {exc}") from exc
            break
        if weight is None:
            if len(script) == 22 and script[:2] == b"\x00\x14":
                # All P2WPKH descriptors have the same satisfaction weight; the key need not match.
                weight = bdk.Descriptor(
                    P2WPKH_EXAMPLE_DESCRIPTOR, network_kind(network)
                ).max_weight_to_satisfy()
            else:
                raise ValueError(
                    "Unsupported or ambiguous output script (including P2WSH and Taproot); "
                    "a matching wallet descriptor is required"
                )
        address = robust_address_str_from_txout(TxOut.from_bdk(txout), network)
        return cls(
            PythonUtxo(address=address, outpoint=outpoint, txout=TxOut.from_bdk(txout)),
            psbt_input,
            weight,
            wallet_id,
        )

    @staticmethod
    def previous_output(outpoint: OutPoint, psbt_input: bdk.Input) -> bdk.TxOut:
        previous = psbt_input.non_witness_utxo
        if previous is None:
            raise ValueError(f"{outpoint}: full previous transaction required")
        if previous.compute_txid() != outpoint.txid or not 0 <= outpoint.vout < len(previous.output()):
            raise ValueError(f"{outpoint}: invalid previous transaction")
        output = previous.output()[outpoint.vout]
        if psbt_input.witness_utxo is not None and TxOut.from_bdk(output) != TxOut.from_bdk(
            psbt_input.witness_utxo
        ):
            raise ValueError(f"{outpoint}: conflicting previous outputs")
        return output

    def _serialize_input(self) -> str:
        """Serialize the complete input map without persisting BDK runtime objects."""
        network = bdk.Network.REGTEST
        receive = bdk.Descriptor(P2WPKH_EXAMPLE_DESCRIPTOR, network_kind(network))
        change = bdk.Descriptor(
            "wpkh(02c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5)",
            network_kind(network),
        )
        bdk_wallet = bdk.Wallet(receive, change, network, bdk.Persister.new_in_memory())
        builder = bdk.TxBuilder().add_foreign_utxo(
            self.utxo.outpoint, self.psbt_input, self.satisfaction_weight
        )
        return (
            builder.manually_selected_only()
            .fee_absolute(bdk.Amount.from_sat(0))
            .allow_dust(True)
            .drain_to(self.utxo.txout.script_pubkey)
            .finish(bdk_wallet)
            .serialize()
        )

    @staticmethod
    def _discard_signatures(psbt_input: bdk.Input) -> None:
        psbt_input.sighash_type = None
        psbt_input.partial_sigs = {}
        psbt_input.final_script_sig = None
        psbt_input.final_script_witness = None
        psbt_input.tap_key_sig = None
        psbt_input.tap_script_sigs = {}

    def use_imported_input(self, imported: bdk.Input) -> None:
        """Keep foreign spend metadata, but discard signatures for the old transaction."""
        imported.non_witness_utxo = imported.non_witness_utxo or self.psbt_input.non_witness_utxo
        imported.witness_utxo = imported.witness_utxo or self.psbt_input.witness_utxo
        self._discard_signatures(imported)
        self.psbt_input = imported

    @staticmethod
    def _empty_input(txout: bdk.TxOut, transaction: bdk.Transaction | None) -> bdk.Input:
        return bdk.Input(
            non_witness_utxo=transaction,
            witness_utxo=txout,
            partial_sigs={},
            sighash_type=None,
            redeem_script=None,
            witness_script=None,
            bip32_derivation={},
            final_script_sig=None,
            final_script_witness=None,
            ripemd160_preimages={},
            sha256_preimages={},
            hash160_preimages={},
            hash256_preimages={},
            tap_key_sig=None,
            tap_script_sigs={},
            tap_scripts={},
            tap_key_origins={},
            tap_internal_key=None,
            tap_merkle_root=None,
            proprietary={},
            unknown={},
        )

    @staticmethod
    def _wallet_input_metadata(bdk_wallet: bdk.Wallet, outpoint: OutPoint, txout: bdk.TxOut) -> bdk.Input:
        """Ask the owning wallet for descriptor metadata for a spendable output."""
        if not bdk_wallet.get_utxo(outpoint):
            raise ValueError("Load and synchronize the originating wallet to obtain input metadata")
        return (
            bdk.TxBuilder()
            .add_utxo(outpoint)
            .manually_selected_only()
            .only_witness_utxo()
            .drain_to(txout.script_pubkey)
            .fee_absolute(bdk.Amount.from_sat(0))
            .allow_dust(True)
            .finish(bdk_wallet)
            .input()[0]
        )
