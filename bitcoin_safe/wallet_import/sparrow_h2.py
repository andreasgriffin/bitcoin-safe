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

"""Read Sparrow H2 databases and convert their public wallet data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .descriptors import b58encode_check
from .model import TXID, ExchangeError, Label, WalletExchange
from .sparrow_crypto import N, _compressed, _scalar_mul

H2_MAGIC = b"H2encrypt\n"
H2_SPRW_MAGIC = b"SPRW1\n"
# The enum ordinals are persisted in Sparrow's database. See Drongo:
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
# Network.java, ScriptType.java, KeystoreSource.java, WalletModel.java.
NETWORK_NAMES = ("mainnet", "testnet", "regtest", "signet", "testnet4", "testnet5")
SCRIPT_NAMES = (
    "P2PK",
    "P2PKH",
    "MULTISIG",
    "P2SH",
    "P2SH_P2WPKH",
    "P2SH_P2WSH",
    "P2WPKH",
    "P2WSH",
    "P2TR",
    "P2A",
)
KEY_SOURCE_NAMES = ("HW_USB", "HW_AIRGAPPED", "SW_SEED", "SW_WATCH", "SW_PAYMENT_CODE")
WALLET_MODEL_NAMES = (
    "SEED",
    "SPARROW",
    "BITCOIN_CORE",
    "ELECTRUM",
    "TREZOR_1",
    "TREZOR_T",
    "COLDCARD",
    "LEDGER_NANO_S",
    "LEDGER_NANO_X",
    "DIGITALBITBOX_01",
    "KEEPKEY",
    "SPECTER_DESKTOP",
    "COBO_VAULT",
    "BITBOX_02",
    "SPECTER_DIY",
    "PASSPORT",
    "BLUE_WALLET",
    "KEYSTONE",
    "SEEDSIGNER",
    "CARAVAN",
    "GORDIAN_SEED_TOOL",
    "JADE",
    "LEDGER_NANO_S_PLUS",
    "EPS",
    "TAPSIGNER",
    "SATSCARD",
    "LABELS",
    "BSMS",
    "KRUX",
    "SATOCHIP",
    "TRANSACTIONS",
    "AIRGAP_VAULT",
    "TREZOR_SAFE_3",
    "SATSCHIP",
    "SAMOURAI",
    "TREZOR_SAFE_5",
    "LEDGER_STAX",
    "LEDGER_FLEX",
    "ONEKEY_CLASSIC_1S",
    "ONEKEY_PRO",
    "KEYCARD_SHELL",
    "KEYCARD",
    "TREZOR_SAFE_7",
    "LEDGER_NANO_GEN5",
    "ERA_WALLET",
)


def is_sparrow_h2(path: Path, head: bytes | None = None) -> bool:
    """Recognize Sparrow H2 files by extension *and* MVStore/encryption magic."""
    if head is None:
        with path.open("rb") as f:
            head = f.read(64)
    return path.name.lower().endswith((".mv.db", ".db")) and (
        head.startswith(H2_MAGIC) or head.startswith((b"H:2,", b"H:2:"))
    )


def sparrow_h2_file_password(
    header: bytes, password: str, _test_costs: tuple[int, int, int] | None = None
) -> str:
    """Derive *H2 file password* from user password; do NOT decrypt/read seeds.

    H2encrypt\\n + 8 H2 salt bytes + SPRW1\\n + 16 Sparrow salt bytes.
    Argon2id(10 iterations, 262144 KiB, parallelism=4, 32 bytes)
    -> secp256k1 compressed public key -> lowercase hex. Sparrow uses this
    public key encoding as the H2 file password, with a blank H2 user password.
    """
    if not isinstance(password, str) or not password:
        raise ExchangeError("Encrypted Sparrow H2 database requires a non-empty password")
    if header[:10] != H2_MAGIC or header[18:24] != H2_SPRW_MAGIC or len(header) < 40:
        raise ExchangeError("Not a recognized Sparrow-encrypted H2 database")
    try:
        from argon2.low_level import Type, hash_secret_raw
    except ImportError as exc:
        raise ExchangeError("Sparrow database password unlock requires argon2-cffi") from exc
    cost = _test_costs if _test_costs is not None else (10, 256 * 1024, 4)
    raw = hash_secret_raw(
        password.encode("utf-8"),
        header[24:40],
        time_cost=cost[0],
        memory_cost=cost[1],
        parallelism=cost[2],
        hash_len=32,
        type=Type.ID,
    )
    d = int.from_bytes(raw, "big")
    if not 0 < d < N:
        raise ExchangeError("Invalid Sparrow H2 password derivation result")
    G = (
        0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
        0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
    )
    return _compressed(_scalar_mul(d, G)).hex()


def _enum(items: tuple[str, ...], raw: Any, kind: str) -> str:
    if not isinstance(raw, int) or isinstance(raw, bool) or not 0 <= raw < len(items):
        raise ExchangeError(f"Unknown Sparrow {kind} enum ordinal {raw!r}; check Drongo version")
    return items[raw]


def _bech32_encode(hrp: str, version: int, payload: bytes) -> str:
    chars = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

    def polymod(values: list[int]) -> int:
        chk = 1
        for v in values:
            b = chk >> 25
            chk = ((chk & 0x1FFFFFF) << 5) ^ v
            for j, g in enumerate((0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)):
                if (b >> j) & 1:
                    chk ^= g
        return chk

    data: list[int] = [version]
    acc = bits = 0
    for byte in payload:
        acc = (acc << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            data.append((acc >> bits) & 31)
    if bits:
        data.append((acc << (5 - bits)) & 31)
    expanded = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    constant = 1 if version == 0 else 0x2BC830A3
    chk = polymod(expanded + data + [0] * 6) ^ constant
    data += [(chk >> (5 * (5 - i))) & 31 for i in range(6)]
    return hrp + "1" + "".join(chars[d] for d in data)


def address_from_h2_data(script_name: str, network: str, rawhex: Any) -> str | None:
    """Convert Drongo WalletNode.addressData payload to the corresponding address."""
    if not isinstance(rawhex, str) or len(rawhex) > 130 or not re.fullmatch("[a-fA-F0-9]*", rawhex):
        return None
    try:
        data = bytes.fromhex(rawhex)
    except ValueError:
        return None
    main = network == "mainnet"
    if script_name in {"P2PKH", "P2SH", "P2SH_P2WPKH", "P2SH_P2WSH"} and len(data) == 20:
        prefix = (b"\x00" if main else b"\x6f") if script_name == "P2PKH" else (b"\x05" if main else b"\xc4")
        return b58encode_check(prefix + data)
    if script_name in {"P2WPKH", "P2WSH", "P2TR"}:
        if len(data) != (20 if script_name == "P2WPKH" else 32):
            return None
        hrp = "bc" if main else "bcrt" if network == "regtest" else "tb"
        return _bech32_encode(hrp, 1 if script_name == "P2TR" else 0, data)
    return None


def from_sparrow_h2_rows(data: dict[str, Any], filename: str = "Sparrow wallet") -> list[WalletExchange]:
    """Convert allowlisted Sparrow rows, rejecting unexpected structures."""
    from .adapters import from_sparrow_json

    if not isinstance(data, dict) or data.get("format") != "sparrow-h2-rows-v1":
        raise ExchangeError("Invalid Sparrow H2 helper JSON format")
    schemas = data.get("schemas")
    if not isinstance(schemas, list) or len(schemas) > 200:
        raise ExchangeError("Invalid Sparrow H2 schema list")
    result = []
    for section in schemas:
        if (
            not isinstance(section, dict)
            or not isinstance(section.get("schema"), str)
            or not str(section["schema"]).startswith("wallet_")
            or not 8 <= len(section["schema"]) <= 255
            or any(ord(c) < 32 or ord(c) == 127 for c in section["schema"])
        ):
            raise ExchangeError("Malformed Sparrow H2 wallet schema")
        schema = section["schema"]
        wallet_rows = section.get("wallet")
        if not isinstance(wallet_rows, list):
            raise ExchangeError(f"Missing Sparrow H2 wallet table in {schema}")
        policies = {r.get("id"): r for r in section.get("policy", []) if isinstance(r, dict)}
        keys = section.get("keystore", [])
        nodes = section.get("walletNode", [])
        outputs = section.get("blockTransactionHashIndex", [])
        txs = section.get("blockTransaction", [])
        detached = section.get("detachedLabel", [])
        external = section.get("externalOutputLabel", [])
        if not all(isinstance(items, list) for items in (keys, nodes, outputs, txs, detached, external)):
            raise ExchangeError(f"Malformed Sparrow H2 tables in {schema}")
        for wallet_row in wallet_rows:
            if not isinstance(wallet_row, dict):
                raise ExchangeError("Malformed Sparrow wallet row")
            wallet_id = wallet_row.get("id")
            if not isinstance(wallet_id, int):
                raise ExchangeError("Missing Sparrow database wallet identifier")
            net = _enum(NETWORK_NAMES, wallet_row.get("network"), "network")
            if net == "testnet5":
                raise ExchangeError("Sparrow TESTNET5 is not yet supported by Bitcoin Safe exchange model")
            script_name = _enum(SCRIPT_NAMES, wallet_row.get("scriptType"), "script type")
            policy = policies.get(wallet_row.get("defaultPolicy"), {})
            key_rows = sorted(
                (r for r in keys if isinstance(r, dict) and r.get("wallet") == wallet_id),
                key=lambda r: r.get("index", 0),
            )
            public_keys = []
            key_indicators = []
            for row in key_rows:
                key_indicators.append(
                    {
                        "software_signer_present": row.get("seed") is not None,
                        "extended_signer_present": row.get("masterPrivateExtendedKey") is not None,
                        "signer_input_ref": row.get("bip39PassphraseRef"),
                        "signer_input_required": bool(row.get("bip39PassphraseRequired")),
                    }
                )
                source = _enum(KEY_SOURCE_NAMES, row.get("source"), "keystore source")
                model_index = row.get("walletModel")
                model = _enum(WALLET_MODEL_NAMES, model_index, "wallet model")
                public_keys.append(
                    {
                        "label": row.get("label"),
                        "source": source,
                        "walletModel": model,
                        "keyDerivation": {
                            "masterFingerprint": row.get("masterFingerprint"),
                            "derivationPath": row.get("derivationPath"),
                        },
                        "extendedPublicKey": row.get("extendedPublicKey"),
                        "seed": row.get("seed"),
                        "masterPrivateExtendedKey": row.get("masterPrivateExtendedKey"),
                        "h2_signer_indicators": key_indicators[-1],
                    }
                )
            node_rows = [row for row in nodes if isinstance(row, dict) and row.get("wallet") == wallet_id]
            node_ids = {r.get("id") for r in node_rows}
            if len(node_ids) != len(node_rows):
                raise ExchangeError("Duplicate walletNode IDs")
            # For stored outputs, the row referenced by another row's spentBy
            # is a synthetic *input record*, not another received output.
            node_outputs = [r for r in outputs if isinstance(r, dict) and r.get("node") in node_ids]
            spent_input_ids = {r["spentBy"] for r in node_outputs if r.get("spentBy") is not None}
            children: dict[Any, list[dict[str, Any]]] = {}
            pending: dict[Any, dict[str, Any]] = {}
            unresolved: list[dict[str, Any]] = []
            for raw in node_rows:
                address = address_from_h2_data(script_name, net, raw.get("addressData"))
                node: dict[str, Any] = {
                    "derivationPath": raw.get("derivationPath"),
                    "children": [],
                    "transactionOutputs": [],
                }
                if address:
                    node["address"] = address
                if isinstance(raw.get("label"), str) and raw["label"]:
                    node["label"] = raw["label"]
                    if not address:
                        unresolved.append(
                            {"derivationPath": raw.get("derivationPath"), "label": raw["label"]}
                        )
                pending[raw.get("id")] = node
                if raw.get("parent") is not None:
                    children.setdefault(raw["parent"], []).append(node)
            # Flat nodes converted into the same tree used by legacy Sparrow JSON.
            for row in node_outputs:
                output_node = pending.get(row.get("node"))
                if output_node is None:
                    continue
                hash_hex = row.get("hash")
                index = row.get("index")
                if (
                    not isinstance(hash_hex, str)
                    or not TXID.fullmatch(hash_hex)
                    or not isinstance(index, int)
                ):
                    continue
                if row.get("id") in spent_input_ids:
                    if row.get("label"):
                        # Sparrow's input labels are indexed by spending txid:vin.
                        pass
                    continue
                status = row.get("status")
                if status is not None and status != 0:
                    raise ExchangeError(f"Unknown Sparrow output freeze status {status!r}")
                output_node["transactionOutputs"].append(
                    {
                        "hash": hash_hex,
                        "index": index,
                        "label": row.get("label"),
                        "value": row.get("outputValue"),
                        "status": "FROZEN" if status == 0 else None,
                        "spentBy": row.get("spentBy"),
                    }
                )
            purpose_nodes = []
            for raw in node_rows:
                node = pending[raw["id"]]
                node["children"] = children.get(raw["id"], [])
                if raw.get("parent") is None:
                    purpose_nodes.append(node)
            # Use exact policy, NEVER assume sortedmulti vs multi.
            wallet_data = {
                "name": wallet_row.get("name") or filename,
                "label": wallet_row.get("label"),
                "network": net,
                "scriptType": script_name,
                "keystores": public_keys,
                "defaultPolicy": {"miniscript": {"script": policy.get("script", "")}},
                "purposeNodes": purpose_nodes,
                "transactions": {
                    str(row.get("txid", "")): {"label": row["label"]}
                    for row in txs
                    if isinstance(row, dict)
                    and row.get("wallet") == wallet_id
                    and isinstance(row.get("txid"), str)
                    and TXID.fullmatch(row["txid"])
                    and isinstance(row.get("label"), str)
                    and row["label"]
                },
                "detachedLabels": {
                    row["entry"]: row["label"]
                    for row in (detached if len(wallet_rows) == 1 else [])
                    if isinstance(row, dict)
                    and isinstance(row.get("entry"), str)
                    and isinstance(row.get("label"), str)
                },
                "gapLimit": wallet_row.get("gapLimit"),
                "birthHeight": wallet_row.get("birthHeight"),
                "birthDate": wallet_row.get("birthDate"),
            }
            w = from_sparrow_json(wallet_data)
            w.source_wallet = "sparrow-h2"
            for row in key_rows:
                mnemonic = row.pop("bip39Mnemonic", None)
                if mnemonic:
                    for index, key in enumerate(w.keystores):
                        if key.xpub == row.get("extendedPublicKey"):
                            w.attach_keystore_seed(index, mnemonic)
                            message = (
                                f"Sparrow signer {index + 1}: SEED_REDACTED; recovery data was not copied"
                            )
                            if message in w.warnings:
                                w.warnings.remove(message)
                            w.warnings.append(
                                f"Sparrow signer {index + 1}: BIP39 seed retained for test-network signing"
                            )
                            break
            if any(row.get("derivedPublicFromSeed") for row in key_rows):
                w.warnings.append(
                    "Public keys were derived from software seeds in memory; verify the descriptor in Sparrow."
                )
            if any(row.get("bip39PassphraseRequired") for row in key_rows):
                w.warnings.append("A BIP39 signer needs its passphrase to derive public keys.")
            if any(row.get("originPathUnknown") for row in key_rows):
                w.warnings.append("A BIP39 signer origin could not be inferred; provide a public descriptor.")
            # Label spending inputs using the *spending* outpoint references.
            for row in node_outputs:
                if row.get("id") in spent_input_ids and isinstance(row.get("label"), str) and row["label"]:
                    if (
                        isinstance(row.get("hash"), str)
                        and TXID.fullmatch(row["hash"])
                        and isinstance(row.get("index"), int)
                    ):
                        w.add_label(Label("input", f"{row['hash']}:{row['index']}", row["label"]))
            if len(wallet_rows) > 1 and (detached or external):
                w.warnings.append(
                    "Detached and external output labels were omitted because this schema contains multiple wallets."
                )
            for row in external if len(wallet_rows) == 1 else []:
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("txid"), str)
                    and TXID.fullmatch(row["txid"])
                    and isinstance(row.get("index"), int)
                    and isinstance(row.get("label"), str)
                ):
                    w.add_label(Label("output", f"{row['txid']}:{row['index']}", row["label"]))
            if unresolved:
                w.extra["unresolved_node_labels"] = unresolved
                w.warnings.append("Some node labels cannot become BIP329 address labels: addressData absent")
            if any(x["software_signer_present"] or x["extended_signer_present"] for x in key_indicators):
                if not any(row.get("derivedPublicFromSeed") for row in key_rows):
                    w.warnings.append(
                        "No public metadata could be derived from available seed records; the seed type, origin or BIP39 passphrase may be unsupported or missing."
                    )
            w.extra.update(
                {
                    "sparrow_h2_schema": schema,
                    "sparrow_h2_wallet_id": wallet_id,
                    "watch_last": wallet_row.get("watchLast"),
                    "stored_block_height": wallet_row.get("storedBlockHeight"),
                }
            )
            result.append(w)
    if not result:
        raise ExchangeError("No wallet records found in Sparrow H2 schemas")
    return result


def load_sparrow_h2(
    path: str | Path,
    password: str | None = None,
    derive_public_from_seeds: bool = True,
    bip39_passphrase: str | None = None,
    bip39_passphrases: dict[str, str] | None = None,
) -> list[WalletExchange]:
    """Recover public metadata from a Sparrow database without modifying it."""
    if not derive_public_from_seeds:
        raise ExchangeError("Sparrow seed-based public metadata recovery is mandatory")
    from .h2_python import extract_sparrow_h2_rows_python

    file = Path(path)
    with file.open("rb") as fp:
        header = fp.read(64)
    if not is_sparrow_h2(file, header):
        raise ExchangeError("Not a recognized Sparrow H2/MVStore .db file")
    if header.startswith(H2_MAGIC) and password is None:
        raise ExchangeError("Encrypted Sparrow H2 database requires a password")
    if not header.startswith(H2_MAGIC) and password is not None:
        raise ExchangeError("Unencrypted Sparrow H2 database: do not supply a password")
    return from_sparrow_h2_rows(
        extract_sparrow_h2_rows_python(file, password, bip39_passphrase, bip39_passphrases),
        filename=file.name,
    )
