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

"""Source-specific adapters, based on publicly documented/reviewed source fields.

Accepts only explicit local files/exports. No filesystem wallet discovery, no
network calls, no hardware access. Unsupported formats fail closed.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from .descriptors import (
    add_checksum,
    combine_receive_change,
    descriptor_for_keys,
    infer_network,
    infer_script_type,
    norm_path,
    normalize_xpub,
    parse_keystores_from_descriptor,
)
from .model import OUTPOINT, TXID, UTXO, ExchangeError, Keystore, Label, WalletExchange
from .sparrow_crypto import decrypt_sprw1, is_sprw1

MAX_FILE = 32 * 1024 * 1024


def _network(s: Any) -> str:
    if isinstance(s, dict):
        s = s.get("name") or s.get("id") or ""
    s = str(s or "").lower()
    if s in ("main", "bitcoin", "mainnet", "btc"):
        return "mainnet"
    if s in ("tbtc", "test", "testnet", "testnet3", "testnetv3"):
        return "testnet"
    if s in ("testnet4", "testnetv4"):
        return "testnet4"
    if s in ("regtest", "rbtc"):
        return "regtest"
    if s == "signet":
        return "signet"
    return "unknown"


def _int(x: Any) -> int | None:
    try:
        return int(x) if x is not None and not isinstance(x, bool) else None
    except (TypeError, ValueError):
        return None


def _public_key(
    xpub: Any,
    fingerprint: Any = None,
    path: Any = None,
    device: Any = None,
    label: Any = None,
    source: Any = None,
) -> Keystore:
    ks = Keystore(
        device_type=str(device) if device else None,
        label=str(label) if label else None,
        source=str(source) if source else None,
    )
    if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-fA-F]{8}", fingerprint):
        ks.fingerprint = fingerprint.lower()
    ks.key_origin = norm_path(path) if isinstance(path, str) else None
    if isinstance(xpub, str) and xpub:
        # Can have '[fingerprint/path]xpub' in common export formats.
        if xpub.startswith("["):
            end = xpub.find("]")
            if end < 0:
                raise ExchangeError("Invalid origin bracket in xpub")
            origin = xpub[1:end].split("/")
            if len(origin[0]) == 8:
                ks.fingerprint = origin[0].lower()
            if len(origin) > 1:
                ks.key_origin = norm_path("/".join(origin[1:]))
            xpub = xpub[end + 1 :]
        if "/" in xpub:
            xpub, ks.derivation_suffix = xpub.split("/", 1)
            ks.derivation_suffix = "/" + ks.derivation_suffix
        ks.xpub, _net, ks.raw_xpub_prefix = normalize_xpub(xpub)
    return ks


def _resolve_network(wallet: WalletExchange, *additional: str) -> None:
    key_net = infer_network(wallet.keystores)
    candidates = [n for n in additional if n != "unknown"]
    if wallet.network != "unknown":
        candidates.append(wallet.network)
    # Mainnet vs non-mainnet must not mismatch. Testnet/signet/regtest
    # share tpub serialization; keep explicit network when present.
    if key_net != "unknown" and candidates:
        if any((n == "mainnet") != (key_net == "mainnet") for n in candidates):
            raise ExchangeError("Network conflicts with extended public key version")
    if wallet.network == "unknown":
        if not candidates:
            wallet.extra["network_inferred_from_keys"] = True
        wallet.network = candidates[0] if candidates else key_net
    if wallet.network == "unknown":
        wallet.warnings.append("Network unknown: verify network before Bitcoin Safe import")


def _set_descriptors(
    wallet: WalletExchange, receive: str | None, change: str | None = None, descriptor: str | None = None
) -> None:
    wallet.receive_descriptor = add_checksum(receive) if receive else None
    wallet.change_descriptor = add_checksum(change) if change else None
    wallet.descriptor = add_checksum(descriptor) if descriptor else combine_receive_change(receive, change)
    source_descriptor = wallet.descriptor or receive
    if wallet.keystores and source_descriptor:
        descriptor_keys = parse_keystores_from_descriptor(source_descriptor)
        known = sorted(k.xpub for k in wallet.keystores if k.xpub)
        found = sorted(k.xpub for k in descriptor_keys if k.xpub)
        if found and known and known != found:
            wallet.warnings.append(
                "Descriptor public keys conflict with source keystores; refusing combined descriptor"
            )
            wallet.descriptor = None
    if not wallet.keystores:
        d = wallet.descriptor or receive or change
        if d:
            wallet.keystores = parse_keystores_from_descriptor(d)
    wallet.address_type = infer_script_type(wallet.descriptor or receive)
    if not wallet.descriptor:
        wallet.warnings.append("Combined receive/change descriptor not established; check both branches")


def _label_from_dict(obj: dict[str, Any]) -> Label:
    return Label(
        type=str(obj["type"]),
        ref=str(obj["ref"]),
        label=obj.get("label"),
        origin=obj.get("origin"),
        spendable=obj.get("spendable"),
        extra={
            k: obj[k]
            for k in ("height", "time", "fee", "value", "rate", "keypath", "fmv", "heights")
            if k in obj
        },
    )


def import_bip329_jsonl(wallet: WalletExchange, text: str) -> int:
    count = 0
    for number, row in enumerate(text.splitlines(), start=1):
        if not row.strip():
            continue
        try:
            obj = json.loads(row)
            if not isinstance(obj, dict):
                raise ExchangeError("BIP329 record must be a JSON object")
            if obj.get("type") not in {"tx", "addr", "pubkey", "input", "output", "xpub", "spscan", "wallet"}:
                # Forward compatible: unknown types intentionally ignored.
                continue
            label = _label_from_dict(obj)
            wallet.add_label(label)
            if label.type == "output" and label.spendable is False and OUTPOINT.fullmatch(label.ref):
                wallet.add_frozen_outpoint(label.ref)
            count += 1
        except (KeyError, ValueError, TypeError) as exc:
            raise ExchangeError(f"BIP329 line {number}: {exc}") from exc
    return count


def from_descriptor(
    text: str, name: str = "Imported descriptor", network: str = "unknown", source: str = "descriptor"
) -> WalletExchange:
    w = WalletExchange(source_wallet=source, name=name, network=network)
    # `strip_checksum` / parse will refuse wrong checksums.
    _set_descriptors(w, text, descriptor=text if "<0;1>" in text else None)
    if not w.keystores:
        w.warnings.append("No BIP32 public keys recognized in descriptor")
    _resolve_network(w)
    return w


def from_specter(data: dict[str, Any], address_csv: str | None = None) -> WalletExchange:
    w = WalletExchange("specter-desktop", str(data.get("name") or data.get("alias") or "Specter wallet"))
    for idx, key in enumerate(data.get("keys") or []):
        if not isinstance(key, dict):
            continue
        try:
            w.keystores.append(
                _public_key(
                    key.get("xpub") or key.get("original"),
                    fingerprint=key.get("fingerprint"),
                    path=key.get("derivation"),
                    label=(data.get("devices") or [])[idx] if idx < len(data.get("devices") or []) else None,
                    source="hardware-or-watch-only",
                )
            )
        except ExchangeError:
            w.warnings.append(f"Could not parse public key from Specter signer {idx}")
    _set_descriptors(w, data.get("recv_descriptor"), data.get("change_descriptor"), data.get("descriptor"))
    _resolve_network(w)
    w.next_receive_index = _int(data.get("address_index"))
    w.next_change_index = _int(data.get("change_index"))
    w.gap_limit = _int(data.get("keypool"))
    w.birth_height = _int(data.get("blockheight"))
    w.threshold = _int(data.get("sigs_required"))
    w.extra.update(
        {
            "alias": data.get("alias"),
            "change_keypool": _int(data.get("change_keypool")),
            "current_address": data.get("address"),
            "current_change_address": data.get("change_address"),
        }
    )
    for item in data.get("frozen_utxo") or []:
        if isinstance(item, str):
            w.add_frozen_outpoint(item)
        elif isinstance(item, dict):
            txid, vout = item.get("txid"), _int(item.get("vout"))
            if txid and vout is not None:
                w.add_frozen_outpoint(f"{txid}:{vout}")
    # Specter JSON export labels are label -> array of addresses.
    labels = data.get("labels") or {}
    if isinstance(labels, dict):
        for label, addresses in labels.items():
            for address in addresses if isinstance(addresses, list) else [addresses]:
                if isinstance(address, str) and address:
                    w.add_label(Label("addr", address, str(label)))
    if address_csv:
        import_specter_address_csv(w, address_csv)
    elif "labels" not in data:
        w.warnings.append("Specter local labels are stored in adjacent _addr.csv; supply that file")
    if data.get("pending_psbts"):
        w.warnings.append("Pending PSBTs intentionally not copied; resolve/recreate them after migration")
    return w


def import_specter_address_csv(w: WalletExchange, text: str) -> None:
    reader = csv.DictReader(io.StringIO(text))
    for original in reader:
        item = {k.lower(): v for k, v in original.items() if k}
        address, label = item.get("address"), item.get("label")
        if address and label and not label.startswith("Address #"):
            w.add_label(Label("addr", address, label))


def _walk_sparrow_node(w: WalletExchange, node: Any) -> None:
    if not isinstance(node, dict):
        return
    address = node.get("address")
    path = node.get("derivationPath")
    if isinstance(address, str) and node.get("label") is not None:
        w.add_label(
            Label(
                "addr", address, str(node["label"]), extra={"keypath": path} if isinstance(path, str) else {}
            )
        )
    if isinstance(address, str) and node.get("status") == "FROZEN":
        if address not in w.frozen_addresses:
            w.frozen_addresses.append(address)
    for out in node.get("transactionOutputs") or []:
        if not isinstance(out, dict):
            continue
        txid, idx = out.get("hash"), _int(out.get("index"))
        if not isinstance(txid, str) or not TXID.fullmatch(txid) or idx is None:
            continue
        outpoint = f"{txid.lower()}:{idx}"
        frozen = out.get("status") == "FROZEN" and not out.get("spentBy")
        utxo = UTXO(
            outpoint,
            address=address if isinstance(address, str) else None,
            value_sats=_int(out.get("value")),
            frozen=frozen,
            label=out.get("label") if isinstance(out.get("label"), str) else None,
            spent=bool(out.get("spentBy")),
        )
        w.utxos.append(utxo)
        if utxo.label:
            w.add_label(Label("output", outpoint, utxo.label))
        if frozen:
            w.add_frozen_outpoint(outpoint)
    for ch in node.get("children") or []:
        _walk_sparrow_node(w, ch)


def from_sparrow_json(data: dict[str, Any]) -> WalletExchange:
    w = WalletExchange(
        "sparrow",
        str(data.get("label") or data.get("name") or "Sparrow wallet"),
        network=_network(data.get("network")),
    )
    for idx, raw in enumerate(data.get("keystores") or []):
        if not isinstance(raw, dict):
            continue
        kd = raw.get("keyDerivation") or {}
        try:
            ks = _public_key(
                raw.get("extendedPublicKey"),
                fingerprint=kd.get("masterFingerprint"),
                path=kd.get("derivationPath") or kd.get("derivation"),
                device=raw.get("walletModel"),
                label=raw.get("label"),
                source=raw.get("source"),
            )
            seed = raw.get("seed")
            if isinstance(seed, dict) and seed.get("type") in (0, "BIP39"):
                phrase = seed.get("mnemonicString")
                if not phrase and isinstance(seed.get("mnemonicCode"), list):
                    phrase = " ".join(seed["mnemonicCode"])
                if isinstance(phrase, str) and phrase and not seed.get("needsPassphrase"):
                    from .sparrow_seed_public import recover_bip39_public_key

                    if recover_bip39_public_key(ks, phrase, w.network) and w.network not in (
                        "mainnet",
                        "unknown",
                    ):
                        ks.non_mainnet_seed = phrase
            indicators = raw.get("h2_signer_indicators")
            if isinstance(indicators, dict):
                ks.extra.update(indicators)
            if raw.get("seed") is not None:
                ks.recovery_material = "SEED_REDACTED"
            elif raw.get("masterPrivateExtendedKey") is not None:
                ks.recovery_material = "PRIVATE_KEY_REDACTED"
            if ks.recovery_material:
                w.warnings.append(
                    f"Sparrow signer {idx + 1}: BIP39 seed retained for test-network signing"
                    if ks.non_mainnet_seed
                    else f"Sparrow signer {idx + 1}: {ks.recovery_material}; recovery data was not copied"
                )
            w.keystores.append(ks)
            if not ks.xpub:
                w.warnings.append(
                    f"Sparrow keystore {idx} lacks an xpub (e.g. encrypted seed); use Sparrow's descriptor export"
                )
        except ExchangeError as exc:
            if "BIP39 seed and" in str(exc):
                raise
            w.warnings.append(f"Sparrow keystore {idx}: {exc}")
    policy = data.get("defaultPolicy") or {}
    script = ((policy.get("miniscript") or {}).get("script") if isinstance(policy, dict) else None) or ""
    match = re.search(r"(?<![a-z])(?:sorted)?multi\((\d+)", script)
    w.threshold = int(match.group(1)) if match else (1 if len(w.keystores) == 1 else None)
    w.gap_limit = _int(data.get("gapLimit"))
    w.next_receive_index = None
    w.birth_height = _int(data.get("birthHeight"))
    # Sparrow's Policy uses Keystore.getScriptName(), which strips whitespace
    # and non-alphanumeric characters from the human-readable keystore label.
    keynames = ["".join(ch for ch in (k.label or "") if ch.isalnum()) or "Keystore" for k in w.keystores]
    # Sparrow defaultPolicy contains an exact miniscript referring to key IDs.
    # Only reconstruct multisig from the explicit policy; do NOT assume sortedmulti.
    script_type = str(data.get("scriptType") or "")
    ordered = ("multi(" in script and "sortedmulti(" not in script) if match else None
    if len(w.keystores) > 1 and script:
        # Ensure source policy order is the same as the saved keystores.
        m = re.search(r"(?:sorted)?multi\(\d+,([^)]*)\)", script)
        if m:
            names_in_script = [s.strip() for s in m.group(1).split(",")]
            if (
                len(names_in_script) == len(keynames)
                and len(set(keynames)) == len(keynames)
                and sorted(names_in_script) == sorted(keynames)
            ):
                w.keystores = [w.keystores[keynames.index(s)] for s in names_in_script]
            else:
                ordered = None
                w.warnings.append("Sparrow multisig policy key order cannot be verified")
    generated = descriptor_for_keys(w.keystores, script_type, threshold=w.threshold, ordered_multisig=ordered)
    if generated:
        _set_descriptors(w, generated, descriptor=generated)
    else:
        w.warnings.append("No verified descriptor reconstructed; export descriptor from Sparrow")
        w.address_type = script_type or None
    _resolve_network(w)
    for purpose in data.get("purposeNodes") or []:
        _walk_sparrow_node(w, purpose)
    for txid, entry in (data.get("transactions") or {}).items():
        if TXID.fullmatch(str(txid)) and isinstance(entry, dict) and isinstance(entry.get("label"), str):
            w.add_label(Label("tx", txid, entry["label"]))
    for ref, label in (data.get("detachedLabels") or {}).items():
        if not isinstance(label, str):
            continue
        if TXID.fullmatch(ref):
            w.add_label(Label("tx", ref, label))
        elif ref.startswith(("bc1", "tb1", "bcrt1", "1", "3", "m", "n", "2")):
            w.add_label(Label("addr", ref, label))
    if data.get("walletConfig"):
        w.extra["has_wallet_config"] = True
    if data.get("birthDate"):
        w.extra["birth_date_raw"] = str(data.get("birthDate"))
    return w


def from_bitbox_config(data: dict[str, Any]) -> list[WalletExchange]:
    result = []
    hw = {
        str(k.get("rootFingerprint", "")).lower(): k
        for k in (data.get("keystores") or [])
        if isinstance(k, dict)
    }
    for entry in data.get("accounts") or []:
        if not isinstance(entry, dict) or _network(entry.get("coinCode")) == "unknown":
            continue
        configurations: list[dict[str, Any]] = []
        for config in entry.get("configurations") or []:
            if isinstance(config, dict) and isinstance(config.get("bitcoinSimple"), dict):
                configurations.append(config["bitcoinSimple"])
        if not configurations:
            continue
        preferred = entry.get("receiveScriptType")
        chosen = next((x for x in configurations if x.get("scriptType") == preferred), configurations[0])
        kinfo = chosen.get("keyInfo") or {}
        net = _network(entry.get("coinCode"))
        w = WalletExchange(
            "bitbox-app", str(entry.get("name") or entry.get("code") or "BitBox account"), network=net
        )
        try:
            fp = kinfo.get("rootFingerprint")
            device = hw.get(str(fp).lower(), {})
            ks = _public_key(
                kinfo.get("xpub"),
                fingerprint=fp,
                path=kinfo.get("keypath"),
                device="bitbox02",
                label=device.get("name"),
                source="hardware",
            )
            w.keystores = [ks]
            _resolve_network(w)
            desc = chosen.get("descriptor")
            if desc:
                supplied_keys = parse_keystores_from_descriptor(desc)
                if supplied_keys and any(x.xpub != ks.xpub for x in supplied_keys):
                    raise ExchangeError("BitBox descriptor does not match signing configuration xpub")
            w.descriptor = (
                add_checksum(desc) if desc else descriptor_for_keys(w.keystores, chosen.get("scriptType", ""))
            )
            w.address_type = chosen.get("scriptType")
            if not w.descriptor:
                w.warnings.append("BitBox descriptor could not be constructed")
        except ExchangeError as exc:
            w.warnings.append(f"BitBox signing configuration: {exc}")
        w.extra.update(
            {
                "code": entry.get("code"),
                "used": bool(entry.get("used")),
                "inactive": bool(entry.get("inactive")),
                "available_script_types": [x.get("scriptType") for x in configurations],
            }
        )
        result.append(w)
    return result


def _format_bip32_indices(path: Any) -> str | None:
    if isinstance(path, str):
        return norm_path(path)
    if not isinstance(path, list) or not path:
        return None
    try:
        return "m/" + "/".join(f"{int(n) & 0x7FFFFFFF}{'h' if int(n) & 0x80000000 else ''}" for n in path)
    except (ValueError, TypeError):
        return None


def from_trezor_account(data: dict[str, Any]) -> WalletExchange:
    symbol = str(data.get("symbol") or "").lower()
    if symbol not in ("btc", "test", "regtest"):
        raise ExchangeError("Not a Trezor Bitcoin account")
    w = WalletExchange(
        "trezor-suite",
        str(data.get("accountLabel") or data.get("name") or "Trezor account"),
        network=_network(symbol),
    )
    type_name = str(data.get("accountType") or "")
    # Source: trezor connect-common ACCOUNT_TYPES: normal=84, segwit=49, legacy=44.
    script = {"normal": "wpkh", "segwit": "sh-wpkh", "legacy": "pkh", "taproot": "tr"}.get(type_name)
    raw_descriptor = data.get("descriptor")
    if isinstance(raw_descriptor, str) and "(" in raw_descriptor:
        _set_descriptors(w, raw_descriptor, descriptor=raw_descriptor if "<0;1>" in raw_descriptor else None)
    else:
        path = _format_bip32_indices(data.get("path"))
        fp = data.get("fingerprint") or data.get("masterFingerprint")
        try:
            w.keystores = [
                _public_key(raw_descriptor, fingerprint=fp, path=path, device="trezor", source="hardware")
            ]
            w.descriptor = descriptor_for_keys(w.keystores, script or "")
            w.address_type = script
            if fp is None:
                w.warnings.append("Trezor Suite account lacks master fingerprint; verify against device")
        except ExchangeError as exc:
            w.warnings.append(f"Could not construct Trezor descriptor: {exc}")
    _resolve_network(w)
    w.extra.update(
        {"account_type": type_name, "index": _int(data.get("index")), "visible": data.get("visible")}
    )
    return w


def from_ledger_account(data: dict[str, Any]) -> WalletExchange:
    currency = data.get("currency") or {}
    coin = str(
        data.get("currencyId")
        or (currency.get("id") or currency.get("ticker") or "" if isinstance(currency, dict) else currency)
    ).lower()
    networks = {
        "bitcoin": "mainnet",
        "btc": "mainnet",
        "bitcoin_testnet": "testnet",
        "bitcoin_regtest": "regtest",
        "bitcoin_signet": "signet",
        "bitcoin_testnet4": "testnet4",
    }
    if coin and coin not in networks:
        raise ExchangeError("Ledger account is not a supported Bitcoin network")
    w = WalletExchange(
        "ledger-live", str(data.get("name") or "Ledger account"), network=networks.get(coin, "unknown")
    )
    raw = data.get("xpub")
    mode = str(data.get("derivationMode") or "")
    script = {
        "": "pkh",
        "unsplit": "pkh",
        "segwit": "sh-wpkh",
        "segwit_unsplit": "sh-wpkh",
        "native_segwit": "wpkh",
        "taproot": "tr",
    }.get(mode)
    # freshAddressPath is typically m/84h/0h/0h/0/0. Drop the last 2
    # unhardened components to identify the account-level xpub origin.
    fresh_path = norm_path(data.get("freshAddressPath"))
    account_path = None
    if fresh_path:
        bits = fresh_path.split("/")
        if len(bits) >= 5 and bits[-2] in ("0", "1") and bits[-1].isdigit():
            account_path = "/".join(bits[:-2])
    try:
        w.keystores = [
            _public_key(
                raw,
                fingerprint=data.get("masterFingerprint"),
                path=account_path,
                device="ledger",
                source="hardware",
            )
        ]
        _resolve_network(w)
        if script:
            w.descriptor = descriptor_for_keys(w.keystores, script)
        else:
            w.warnings.append(f"Unrecognized Ledger derivationMode {mode!r}; refusing to guess descriptor")
        w.address_type = script
    except ExchangeError as exc:
        w.warnings.append(f"Ledger account xpub: {exc}")
    if not data.get("masterFingerprint"):
        w.warnings.append("Ledger Live account has no master fingerprint; verify signer origin on device")
    w.next_receive_index = _int(data.get("freshAddressIndex"))
    w.extra.update({"derivation_mode": mode, "index": _int(data.get("index"))})
    expected_address = data.get("freshAddress")
    if (
        isinstance(expected_address, str)
        and expected_address
        and account_path
        and fresh_path
        and w.address_type in ("pkh", "wpkh", "sh-wpkh")
        and w.keystores
        and w.keystores[0].xpub
    ):
        bits = fresh_path.split("/")
        if len(bits) >= 5 and bits[-2] in ("0", "1") and bits[-1].isdigit() and w.network != "unknown":
            from .verification import address_from_public_keys

            computed = address_from_public_keys(
                w.keystores, w.address_type, w.network, int(bits[-2]), int(bits[-1])
            )
            if computed != expected_address:
                raise ExchangeError(
                    "Ledger Live stored address does not match public account xpub and policy"
                )
            w.extra["address_verification"] = {"branch": int(bits[-2]), "index": int(bits[-1])}
    utxos = (data.get("bitcoinResources") or {}).get("utxos") or []
    for item in utxos:
        if isinstance(item, list) and len(item) >= 5:
            txid, vout, _height, address, value = item[:5]
        elif isinstance(item, dict):
            txid, vout, address, value = (
                item.get("hash"),
                item.get("outputIndex"),
                item.get("address"),
                item.get("value"),
            )
        else:
            continue
        output_index = _int(vout)
        if isinstance(txid, str) and TXID.fullmatch(txid) and output_index is not None:
            w.utxos.append(UTXO(f"{txid}:{output_index}", address=address, value_sats=_int(value)))
    return w


def from_green(data: dict[str, Any]) -> WalletExchange:
    # Blockstream green_qt wallets2 records are login records, NOT wallet
    # descriptors (src/models/wallet.cpp). API subaccount exports MAY contain
    # explicit `descriptor` fields. Never infer keys from an xpub_hash_id.
    w = WalletExchange(
        "blockstream-green",
        str(data.get("name") or data.get("account_name") or "Green wallet"),
        network=_network(data.get("deployment") or data.get("network")),
    )
    supplied = data.get("descriptor") or data.get("output_descriptor")
    if supplied:
        _set_descriptors(w, supplied, descriptor=supplied if "<0;1>" in supplied else None)
        _resolve_network(w)
    else:
        w.warnings.append(
            "Green local wallets2 records contain login metadata, not descriptors; obtain an explicit subaccount export"
        )
    w.extra.update(
        {
            "record_type": "login-only" if not supplied else "descriptor",
            "has_device_login": "device" in data,
        }
    )
    return w


def load_json_obj(obj: Any, hint: str | None = None, password: str | None = None) -> list[WalletExchange]:
    """Conservative auto-detection; explicit hint may be 'specter', 'sparrow',
    'bitbox', 'trezor', 'ledger', 'green'.
    """
    if isinstance(obj, list):
        all_wallets: list[WalletExchange] = []
        for item in obj:
            all_wallets.extend(load_json_obj(item, hint=hint, password=password))
        return all_wallets
    if not isinstance(obj, dict):
        raise ExchangeError("Expected a JSON wallet object")
    fmt = (hint or "").lower()
    from .ledger_live_db import from_ledger_live_app, is_ledger_live_app

    if is_ledger_live_app(obj) and fmt in ("", "ledger", "ledger-app", "ledger-live-db"):
        return from_ledger_live_app(obj, password=password)
    if password is not None and not (
        fmt == "wasabi" or (not hint and "ExtPubKey" in obj and "BlockchainState" in obj)
    ):
        raise ExchangeError("This wallet export is plaintext; its app or device password does not decrypt it")
    if fmt == "electrum" or (
        not hint and "wallet_type" in obj and ("keystore" in obj or "x1" in obj or "addresses" in obj)
    ):
        from .electrum import from_electrum

        return [from_electrum(obj)]
    if fmt == "wasabi" or (not hint and "ExtPubKey" in obj and "BlockchainState" in obj):
        from .additional import from_wasabi

        return from_wasabi(obj, password=password)
    if fmt in ("specter", "specter-desktop") or (not hint and "recv_descriptor" in obj and "keys" in obj):
        return [from_specter(obj)]
    if fmt == "sparrow" or (not hint and "purposeNodes" in obj and "keystores" in obj):
        return [from_sparrow_json(obj)]
    if fmt == "bitbox" or (
        not hint
        and "accounts" in obj
        and "keystores" in obj
        and any(isinstance(a, dict) and "configurations" in a for a in (obj.get("accounts") or []))
    ):
        return from_bitbox_config(obj)
    if fmt == "trezor" or (not hint and "accountType" in obj and "symbol" in obj and "descriptor" in obj):
        return [from_trezor_account(obj)]
    if fmt == "ledger" or (not hint and obj.get("type") == "Account" and "derivationMode" in obj):
        return [from_ledger_account(obj)]
    if fmt == "green" or (
        not hint
        and "deployment" in obj
        and any(k in obj for k in ("pin", "device", "watchonly", "hashes", "xpub_hash_id"))
    ):
        return [from_green(obj)]
    if not hint and isinstance(obj.get("accounts"), list):
        accounts = obj["accounts"]
        if accounts and all(
            isinstance(item, dict) and "accountType" in item and "symbol" in item for item in accounts
        ):
            return [
                from_trezor_account(item)
                for item in accounts
                if item.get("symbol") in ("btc", "test", "regtest")
            ]
        if accounts and all(
            isinstance(item, dict) and "derivationMode" in item and "xpub" in item for item in accounts
        ):
            eligible = []
            for item in accounts:
                currency = item.get("currency") or {}
                currency_id = currency.get("id", "bitcoin") if isinstance(currency, dict) else str(currency)
                if str(currency_id).lower().startswith("bitcoin"):
                    eligible.append(from_ledger_account(item))
            return eligible
    raise ExchangeError("Unknown wallet format; choose a source-specific export or --format")


def load_file(
    path: str | Path,
    password: str | None = None,
    hint: str | None = None,
    labels: list[str | Path] | None = None,
    specter_addresses: str | Path | None = None,
    derive_public_from_seeds: bool = True,
    trezor_metadata: str | Path | None = None,
    trezor_account_key: str | None = None,
    trezor_usb: bool = False,
    trezor_metadata_version: int = 1,
    bip39_passphrase: str | None = None,
) -> list[WalletExchange]:
    if bool(trezor_metadata) != trezor_usb:
        raise ExchangeError("Trezor metadata and device access must be provided together")
    if trezor_account_key and not trezor_metadata:
        raise ExchangeError("Trezor metadata account key requires a metadata file")
    file = Path(path)
    # Route recognized binary H2 files to the read-only Sparrow decoder before
    # applying the JSON size limit or decoding the file as text.
    from .sparrow_h2 import is_sparrow_h2, load_sparrow_h2

    with file.open("rb") as fp:
        head = fp.read(64)
    if is_sparrow_h2(file, head):
        if trezor_metadata:
            raise ExchangeError("Trezor labels require a Trezor account")
        if hint and hint.lower() not in ("sparrow", "sparrow-h2"):
            raise ExchangeError("This is a Sparrow H2 database; --format must be sparrow")
        out = load_sparrow_h2(
            file,
            password=password,
            derive_public_from_seeds=derive_public_from_seeds,
            bip39_passphrase=bip39_passphrase,
        )
        if specter_addresses:
            raise ExchangeError("--specter-addresses is for Specter, not Sparrow")
        for label_path in labels or []:
            p = Path(label_path)
            if p.stat().st_size > MAX_FILE:
                raise ExchangeError("BIP329 labels file too large")
            if len(out) != 1:
                raise ExchangeError(
                    "Ambiguous multi-account labels; apply BIP329 labels to accounts individually"
                )
            import_bip329_jsonl(out[0], p.read_text(encoding="utf-8-sig"))
        return out
    if file.stat().st_size > MAX_FILE:
        raise ExchangeError("Wallet file exceeds safe maximum size")
    raw = file.read_bytes()
    consumed_password = False
    from .electrum import decrypt_electrum, is_electrum_encrypted

    if is_electrum_encrypted(raw):
        if hint and hint.lower() != "electrum":
            raise ExchangeError("This is an Electrum wallet; select the Electrum format")
        if password is None:
            raise ExchangeError("Encrypted Electrum wallet requires an explicit password; use --ask-password")
        raw = decrypt_electrum(raw, password)
        consumed_password = True
        hint = hint or "electrum"
    elif is_sprw1(raw):
        if hint and hint.lower() != "sparrow":
            raise ExchangeError("This is a Sparrow wallet; select the Sparrow format")
        if password is None:
            raise ExchangeError("Sparrow SPRW1 file requires explicit password; use --ask-password")
        raw = decrypt_sprw1(raw, password)
        consumed_password = True
        hint = hint or "sparrow"
    elif raw.startswith(b"H2encrypt\n"):
        raise ExchangeError("Unrecognized H2-encrypted file; expected Sparrow .mv.db")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExchangeError("Binary wallet format not recognized; use an application export") from exc
    if text.strip().startswith(("wpkh(", "sh(", "pkh(", "wsh(", "tr(")):
        if not hint or hint.lower() != "green":
            raise ExchangeError("This descriptor is only supported for Blockstream Green imports")
        if password is not None and not consumed_password:
            raise ExchangeError("Descriptor text is plaintext; do not supply a password")
        out = [from_descriptor(text.strip(), name=file.stem, source="blockstream-green")]
    else:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExchangeError("Not a supported wallet JSON/descriptor export") from exc
        out = load_json_obj(obj, hint=hint, password=None if consumed_password else password)
    if trezor_metadata:
        if len(out) != 1 or out[0].source_wallet != "trezor-suite":
            raise ExchangeError("Trezor labels require exactly one Trezor account")
        if password is not None or not trezor_account_key:
            raise ExchangeError("Supply the original Trezor metadata account key, without a wallet password")
        from .trezor_metadata import apply_trezor_mtdt_labels, get_legacy_master_key_from_usb

        device_master = get_legacy_master_key_from_usb(encryption_version=trezor_metadata_version)
        apply_trezor_mtdt_labels(
            out[0], trezor_metadata, trezor_account_key, device_master, trezor_metadata_version
        )
    if specter_addresses:
        if len(out) != 1 or out[0].source_wallet != "specter-desktop":
            raise ExchangeError("--specter-addresses requires one Specter wallet")
        address_file = Path(specter_addresses)
        if address_file.stat().st_size > MAX_FILE:
            raise ExchangeError("Specter address CSV is too large")
        import_specter_address_csv(out[0], address_file.read_text(encoding="utf-8-sig"))
    for path in labels or []:
        p = Path(path)
        if p.stat().st_size > MAX_FILE:
            raise ExchangeError("BIP329 labels file too large")
        content = p.read_text(encoding="utf-8-sig")
        if len(out) > 1:
            raise ExchangeError(
                "Ambiguous multi-account labels; import accounts individually to prevent metadata leakage"
            )
        import_bip329_jsonl(out[0], content)
    return out
