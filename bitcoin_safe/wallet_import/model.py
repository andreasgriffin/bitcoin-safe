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

"""Wallet migration data; BIP39 seeds are retained only on test networks."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

OUTPOINT = re.compile(r"^[0-9a-fA-F]{64}:[0-9]+$")
TXID = re.compile(r"^[0-9a-fA-F]{64}$")
BIP329_TYPES = {"tx", "addr", "pubkey", "input", "output", "xpub", "spscan", "wallet"}
NETWORKS = {"mainnet", "testnet", "testnet4", "signet", "regtest", "unknown"}


class ExchangeError(ValueError):
    """Invalid or unsupported wallet migration input."""


class PasswordRequired(ExchangeError):
    """A source wallet requires its application password."""


@dataclass(slots=True)
class Keystore:
    xpub: str | None = None  # public ONLY, normalized to xpub/tpub
    fingerprint: str | None = None
    key_origin: str | None = None  # m/84h/0h/0h, account level
    derivation_suffix: str = "/<0;1>/*"
    device_type: str | None = None  # bitcoin-safe HardwareSigners id when known
    label: str | None = None
    source: str | None = None  # hardware / software / watch-only / unknown
    raw_xpub_prefix: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # Excluded from repr; serialized only for explicit test networks.
    non_mainnet_seed: str | None = field(default=None, repr=False, compare=False)
    # Indicates whether recovery material was redacted or retained on test networks.
    recovery_material: str | None = None  # SEED_REDACTED or PRIVATE_KEY_REDACTED

    def public_dict(self) -> dict[str, Any]:
        if self.recovery_material not in (
            None,
            "SEED_REDACTED",
            "PRIVATE_KEY_REDACTED",
            "BIP39_RETAINED_TESTNET",
        ):
            raise ExchangeError("Invalid recovery material marker")
        return {
            "xpub": self.xpub,
            "fingerprint": self.fingerprint,
            "key_origin": self.key_origin,
            "derivation_suffix": self.derivation_suffix,
            "device_type": self.device_type,
            "label": self.label,
            "source": self.source,
            "raw_xpub_prefix": self.raw_xpub_prefix,
            "recovery_material": self.recovery_material,
            "extra": self.extra,
        }


@dataclass(slots=True)
class Label:
    type: str
    ref: str
    label: str | None = None
    origin: str | None = None
    spendable: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.type not in BIP329_TYPES:
            raise ExchangeError(f"Unsupported BIP329 label type: {self.type}")
        if not isinstance(self.ref, str) or not self.ref:
            raise ExchangeError("BIP329 label ref is missing")
        if self.spendable is not None and (self.type != "output" or not isinstance(self.spendable, bool)):
            raise ExchangeError("'spendable' must be a boolean on an output label")
        if self.label is not None and not isinstance(self.label, str):
            raise ExchangeError("Label text must be a string")
        if self.origin is not None and not isinstance(self.origin, str):
            raise ExchangeError("Label origin must be a string")

    def to_bip329(self) -> dict[str, Any]:
        rec: dict[str, Any] = {"type": self.type, "ref": self.ref}
        if self.label is not None:
            rec["label"] = self.label
        if self.origin is not None:
            rec["origin"] = self.origin
        if self.spendable is not None:
            rec["spendable"] = self.spendable
        # BIP329 optional extra metadata: keep only well-defined non-secret fields.
        for k in ("height", "time", "fee", "value", "rate", "keypath", "fmv", "heights"):
            if k in self.extra:
                rec[k] = self.extra[k]
        return rec


@dataclass(slots=True)
class UTXO:
    outpoint: str
    address: str | None = None
    value_sats: int | None = None
    frozen: bool = False
    label: str | None = None
    spent: bool | None = None

    def __post_init__(self):
        if not OUTPOINT.fullmatch(self.outpoint):
            raise ExchangeError("Invalid outpoint")


@dataclass(slots=True)
class WalletExchange:
    source_wallet: str
    name: str
    network: str = "unknown"
    descriptor: str | None = None  # combined /<0;1>/*, when provable
    receive_descriptor: str | None = None
    change_descriptor: str | None = None
    keystores: list[Keystore] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    frozen_addresses: list[str] = field(default_factory=list)
    frozen_outpoints: list[str] = field(default_factory=list)
    utxos: list[UTXO] = field(default_factory=list)
    gap_limit: int | None = None
    next_receive_index: int | None = None
    next_change_index: int | None = None
    birth_height: int | None = None
    threshold: int | None = None
    address_type: str | None = None
    warnings: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    # Held ONLY in memory, explicitly testnet-like, never serialized or repr'd.
    non_mainnet_seed: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self.network not in NETWORKS:
            raise ExchangeError(f"Unsupported network: {self.network}")
        if self.non_mainnet_seed is not None and self.network in ("mainnet", "unknown"):
            raise ExchangeError("Seed material may only be attached on explicit non-mainnet networks")

    def attach_non_mainnet_seed(self, seed: str) -> None:
        if self.network in ("mainnet", "unknown"):
            raise ExchangeError("Refusing to retain mainnet/unknown-network seed")
        self.non_mainnet_seed = seed

    def attach_keystore_seed(self, index: int, seed: str) -> None:
        """Attach a valid BIP39 seed only for test networks."""
        if self.network in ("mainnet", "unknown"):
            raise ExchangeError("Refusing to attach mainnet/unknown-network keystore seed")
        if not isinstance(seed, str) or not seed.strip():
            raise ExchangeError("Empty non-mainnet seed")
        from bdkpython import Mnemonic

        try:
            Mnemonic.from_string(seed)
        except Exception as exc:
            raise ExchangeError("Invalid BIP39 mnemonic") from exc
        self.keystores[index].non_mainnet_seed = " ".join(seed.split())

    def add_label(self, label: Label) -> None:
        # Distinct (type, ref, origin) labels can be legitimate; conflicting ones
        # are never silently overwritten, because origin disambiguates accounts.
        for existing in self.labels:
            if (existing.type, existing.ref, existing.origin) == (label.type, label.ref, label.origin):
                if existing.label not in (None, label.label) and label.label is not None:
                    self.warnings.append(f"Conflicting labels for {label.type}:{label.ref}; kept first")
                if existing.label is None:
                    existing.label = label.label
                if label.spendable is not None:
                    if existing.spendable is not None and existing.spendable != label.spendable:
                        self.warnings.append(f"Conflicting spendable state for {label.ref}; kept first")
                    elif existing.spendable is None:
                        existing.spendable = label.spendable
                return
        self.labels.append(label)

    def add_frozen_outpoint(self, outpoint: str) -> None:
        if not OUTPOINT.fullmatch(outpoint):
            self.warnings.append("Skipped malformed frozen outpoint")
            return
        outpoint = outpoint.lower()
        if outpoint not in self.frozen_outpoints:
            self.frozen_outpoints.append(outpoint)
        self.add_label(Label(type="output", ref=outpoint, spendable=False))

    def to_dict(self) -> dict[str, Any]:
        # Explicit allowlist; NEVER use asdict(self) because that includes seeds.
        result: dict[str, Any] = {
            "format_version": 1,
            "source_wallet": self.source_wallet,
            "name": self.name,
            "network": self.network,
            "descriptor": self.descriptor,
            "receive_descriptor": self.receive_descriptor,
            "change_descriptor": self.change_descriptor,
            "keystores": [k.public_dict() for k in self.keystores],
            "labels": [label.to_bip329() for label in self.labels],
            "frozen_addresses": sorted(set(self.frozen_addresses)),
            "frozen_outpoints": sorted(set(self.frozen_outpoints)),
            "utxos": [asdict(u) for u in self.utxos],
            "gap_limit": self.gap_limit,
            "next_receive_index": self.next_receive_index,
            "next_change_index": self.next_change_index,
            "birth_height": self.birth_height,
            "threshold": self.threshold,
            "address_type": self.address_type,
            "warnings": self.warnings,
            "extra": self.extra,
        }
        # Defense in depth: refuse *any* accidental secret leak through extra.
        _assert_no_secrets(result)
        if self.network in ("mainnet", "unknown") and any(k.non_mainnet_seed for k in self.keystores):
            raise ExchangeError("Refusing to export BIP39 secret on mainnet or unknown network")
        for i, key in enumerate(self.keystores):
            if key.non_mainnet_seed:
                result["keystores"][i]["bip39_mnemonic"] = key.non_mainnet_seed
                result["keystores"][i]["recovery_material"] = "BIP39_RETAINED_TESTNET"
        return result

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> WalletExchange:
        """Rehydrate an exchange document, allowing BIP39 seeds only on test networks."""
        if not isinstance(obj, dict) or obj.get("format_version") != 1:
            raise ExchangeError("Unsupported wallet exchange format version")
        public_obj = dict(obj)
        raw_keys = obj.get("keystores")
        if not isinstance(raw_keys, list):
            raise ExchangeError("Invalid keystore list")
        public_keys = []
        for raw in raw_keys:
            if not isinstance(raw, dict):
                raise ExchangeError("Invalid keystore entry")
            clean = dict(raw)
            secret = clean.pop("bip39_mnemonic", None)
            if secret is not None and obj.get("network") not in NETWORKS - {"mainnet", "unknown"}:
                raise ExchangeError("BIP39 seed in mainnet or unknown-network keystore")
            public_keys.append(clean)
        public_obj["keystores"] = public_keys
        _assert_no_secrets(public_obj)
        if not isinstance(obj.get("keystores"), list) or not isinstance(obj.get("labels"), list):
            raise ExchangeError("Invalid keystore/label lists")
        from .descriptors import add_checksum, normalize_xpub

        ks_list = []
        allowed = set(Keystore.__dataclass_fields__) - {"non_mainnet_seed"}
        for raw in obj["keystores"]:
            if not isinstance(raw, dict):
                raise ExchangeError("Invalid keystore entry")
            ks = Keystore(**{k: v for k, v in raw.items() if k in allowed})
            if ks.xpub:
                canonical, _, _ = normalize_xpub(ks.xpub)
                ks.xpub = canonical
            ks.public_dict()  # validates recovery marker
            if raw.get("bip39_mnemonic") is not None:
                from bdkpython import Mnemonic

                try:
                    Mnemonic.from_string(raw["bip39_mnemonic"])
                except Exception as exc:
                    raise ExchangeError("Invalid BIP39 mnemonic") from exc
                ks.non_mainnet_seed = raw["bip39_mnemonic"]
            ks_list.append(ks)
        labels = []
        for raw in obj["labels"]:
            if not isinstance(raw, dict):
                raise ExchangeError("Invalid BIP329 label entry")
            labels.append(
                Label(
                    type=raw["type"],
                    ref=raw["ref"],
                    label=raw.get("label"),
                    origin=raw.get("origin"),
                    spendable=raw.get("spendable"),
                    extra={
                        k: raw[k]
                        for k in ("height", "time", "fee", "value", "rate", "keypath", "fmv", "heights")
                        if k in raw
                    },
                )
            )
        utxos = [UTXO(**x) for x in obj.get("utxos", [])]
        desc_keys = ("descriptor", "receive_descriptor", "change_descriptor")
        descs = {key: add_checksum(obj[key]) if obj.get(key) else None for key in desc_keys}
        frozen_outpoints = list(obj.get("frozen_outpoints") or [])
        if any(not isinstance(x, str) or not OUTPOINT.fullmatch(x) for x in frozen_outpoints):
            raise ExchangeError("Malformed frozen outpoint in interchange")
        return cls(
            source_wallet=str(obj["source_wallet"]),
            name=str(obj["name"]),
            network=str(obj.get("network") or "unknown"),
            keystores=ks_list,
            labels=labels,
            utxos=utxos,
            frozen_addresses=list(obj.get("frozen_addresses") or []),
            frozen_outpoints=frozen_outpoints,
            gap_limit=obj.get("gap_limit"),
            next_receive_index=obj.get("next_receive_index"),
            next_change_index=obj.get("next_change_index"),
            birth_height=obj.get("birth_height"),
            threshold=obj.get("threshold"),
            address_type=obj.get("address_type"),
            warnings=list(obj.get("warnings") or []),
            extra=dict(obj.get("extra") or {}),
            **descs,
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def labels_jsonl(self) -> str:
        return "\n".join(json.dumps(x.to_bip329(), ensure_ascii=False) for x in self.labels) + (
            "\n" if self.labels else ""
        )


def _assert_no_secrets(obj: Any):
    forbidden_keys = re.compile(
        r"(^|[_-])(seed|mnemonic|private.?key|xprv|tprv|password|secret|passphrase)([_-]|$)", re.I
    )
    if isinstance(obj, dict):
        for k, v in obj.items():
            if forbidden_keys.search(str(k)):
                raise ExchangeError("Secret-like key in output data; refusing export")
            _assert_no_secrets(v)
    elif isinstance(obj, (tuple, list)):
        for v in obj:
            _assert_no_secrets(v)
    elif isinstance(obj, str) and re.search(
        r"(?:[xyztuvUV]prv|\b(?:xprv|tprv))[1-9A-HJ-NP-Za-km-z]{20,}", obj
    ):
        raise ExchangeError("Private extended key in output data; refusing export")
