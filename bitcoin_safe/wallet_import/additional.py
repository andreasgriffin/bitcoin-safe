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

"""Public-data importer for Wasabi wallet JSON."""

from __future__ import annotations

from typing import Any

from .adapters import _public_key, _resolve_network
from .descriptors import (
    add_checksum,
    descriptor_for_keys,
    strip_checksum,
)
from .model import ExchangeError, WalletExchange


def from_wasabi(
    data: dict[str, Any], name: str = "Wasabi wallet", password: str | None = None
) -> list[WalletExchange]:
    """Decode the public account portion of Wasabi KeyManager wallet JSON.

    Wasabi stores separate BIP84 and BIP86 account keys. Both are offered as
    separate WalletExchange instances; don't incorrectly combine script types.
    """
    if not isinstance(data, dict) or "ExtPubKey" not in data or "BlockchainState" not in data:
        raise ExchangeError("Not a Wasabi KeyManager file")
    if password is not None:
        from .passwords import verify_wasabi_password

        verify_wasabi_password(data, password)
    state = data["BlockchainState"]
    if not isinstance(state, dict):
        raise ExchangeError("Malformed Wasabi BlockchainState")
    net = {
        "main": "mainnet",
        "mainnet": "mainnet",
        "testnet": "testnet",
        "testnet4": "testnet4",
        "regtest": "regtest",
        "signet": "signet",
    }.get(str(state.get("Network", "")).lower(), "unknown")
    if net == "unknown":
        raise ExchangeError("Unsupported Wasabi network; cannot safely infer account")
    specs = [
        ("Segwit", "ExtPubKey", "AccountKeyPath", "P2WPKH"),
        ("Taproot", "TaprootExtPubKey", "TaprootAccountKeyPath", "P2TR"),
    ]
    result: list[WalletExchange] = []
    for display, keyname, pathname, script in specs:
        raw_xpub = data.get(keyname)
        if not isinstance(raw_xpub, str) or not raw_xpub:
            continue
        path = data.get(pathname) or (
            "m/84h/1h/0h"
            if net in ("testnet", "testnet4", "signet", "regtest") and script == "P2WPKH"
            else "m/84h/0h/0h"
            if script == "P2WPKH"
            else "m/86h/1h/0h"
            if net in ("testnet", "testnet4", "signet", "regtest")
            else "m/86h/0h/0h"
        )
        w = WalletExchange("wasabi", f"{name} ({display})", network=net)
        k = _public_key(
            raw_xpub,
            fingerprint=data.get("MasterFingerprint"),
            path=path,
            device="wasabi",
            source="software" if data.get("EncryptedSecret") is not None else "hardware/watch-only",
        )
        if data.get("EncryptedSecret") is not None:
            k.recovery_material = "PRIVATE_KEY_REDACTED"
            w.warnings.append(
                "Wasabi private signing material was not copied"
                + ("; BIP38 password verified" if password is not None else "")
            )
        w.keystores = [k]
        _resolve_network(w)
        w.descriptor = descriptor_for_keys([k], script)
        w.address_type = script
        w.threshold = 1
        w.gap_limit = data.get("MinGapLimit") if isinstance(data.get("MinGapLimit"), int) else None
        birth = state.get("BirthHeight")
        if isinstance(birth, int) or isinstance(birth, str) and birth.isdecimal():
            w.birth_height = int(birth)
        if w.descriptor:
            d = strip_checksum(w.descriptor)
            w.receive_descriptor = add_checksum(d.replace("/<0;1>/*", "/0/*"))
            w.change_descriptor = add_checksum(d.replace("/<0;1>/*", "/1/*"))
        # Wasabi HdPubKeys have FullKeyPath and Label, but no address. Keep
        # unresolved path annotations for a future address-derivation layer.
        rows = data.get("HdPubKeys") or []
        for r in rows:
            if (
                isinstance(r, dict)
                and isinstance(r.get("FullKeyPath"), str)
                and isinstance(r.get("Label"), str)
                and r["Label"]
            ):
                w.extra.setdefault("unresolved_path_labels", []).append(
                    {"path": r["FullKeyPath"], "label": r["Label"]}
                )
        if w.extra.get("unresolved_path_labels"):
            w.warnings.append(
                "Wasabi key labels require derivation of addresses before conversion to BIP329 addr records"
            )
        if data.get("ExcludedCoinsFromCoinJoin"):
            w.extra["coinjoin_exclusion_count"] = len(data["ExcludedCoinsFromCoinJoin"])
            w.warnings.append("Wasabi CoinJoin exclusions are not spend freezes")
        result.append(w)
    if not result:
        raise ExchangeError("Wasabi wallet has no supported Bitcoin account xpub")
    return result
