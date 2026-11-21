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

"""Ledger Desktop app.json discovery and versioned account import regressions.

Synthetic public account data only; no real wallet files, passwords or seeds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bitcoin_safe.wallet_import import ExchangeError, load_file, load_json_obj
from bitcoin_safe.wallet_import.ledger_live_db import discover_ledger_live_app_json

from .test_wallet_exchange import xpub


def test_ledger_autodiscovery_linux_xdg(tmp_path: Path) -> None:
    config = tmp_path / "custom-xdg"
    app_json = config / "Ledger Live" / "app.json"
    app_json.parent.mkdir(parents=True)
    app_json.write_text("{}", encoding="utf-8")
    assert (
        discover_ledger_live_app_json(
            environ={"XDG_CONFIG_HOME": str(config)}, home=tmp_path, platform="linux"
        )
        == app_json
    )


def test_ledger_autodiscovery_macos(tmp_path: Path) -> None:
    path = tmp_path / "Library" / "Application Support" / "Ledger Live" / "app.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    assert discover_ledger_live_app_json(environ={}, home=tmp_path, platform="darwin") == path


def test_ledger_autodiscovery_windows(tmp_path: Path) -> None:
    roaming = tmp_path / "Roaming"
    path = roaming / "Ledger Live" / "app.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    assert (
        discover_ledger_live_app_json(environ={"APPDATA": str(roaming)}, home=tmp_path, platform="win32")
        == path
    )


def test_ledger_directory_override_is_not_a_recursive_search(tmp_path: Path) -> None:
    custom = tmp_path / "moved"
    custom.mkdir()
    with pytest.raises(FileNotFoundError, match="LEDGER_CONFIG_DIRECTORY"):
        discover_ledger_live_app_json(
            environ={"LEDGER_CONFIG_DIRECTORY": str(custom)}, home=tmp_path, platform="linux"
        )
    direct = custom / "app.json"
    direct.write_text("{}", encoding="utf-8")
    assert (
        discover_ledger_live_app_json(
            environ={"LEDGER_CONFIG_DIRECTORY": str(direct)}, home=tmp_path, platform="linux"
        )
        == direct
    )


def _versioned_bitcoin_account() -> dict:
    key = xpub()
    return {
        "version": 3,
        "data": {
            "id": "js:2:bitcoin:synthetic-public-xpub:native_segwit",
            "seedIdentifier": "public-test-only",
            "currencyId": "bitcoin",
            "derivationMode": "native_segwit",
            "name": "Bitcoin 1",
            "index": 0,
            "xpub": key,
            "freshAddressPath": "84'/0'/0'/0/0",
            "bitcoinResources": {
                "utxos": [],
                "walletAccount": {
                    "params": {
                        "xpub": key,
                        "path": "84'/0'",
                        "index": 0,
                        "network": "mainnet",
                        "derivationMode": "Native SegWit",
                    },
                    "xpub": {"xpub": key, "data": {"addressCache": {}}},
                },
            },
        },
    }


def test_ledger_live_v3_app_json_envelope_and_multiple_accounts(tmp_path: Path) -> None:
    wrapped = _versioned_bitcoin_account()
    second = json.loads(json.dumps(wrapped))
    second["data"]["name"] = "Bitcoin 2"
    second["data"]["index"] = 1
    source = tmp_path / "app.json"
    source.write_text(
        json.dumps(
            {
                "data": {
                    "accounts": [
                        wrapped,
                        second,
                        {"version": 3, "data": {"currencyId": "ethereum", "xpub": "not-a-bitcoin-key"}},
                    ]
                }
            }
        )
    )
    wallets = load_file(source, hint="ledger")
    assert [w.name for w in wallets] == ["Bitcoin 1", "Bitcoin 2"]
    assert all(w.network == "mainnet" and w.address_type == "wpkh" for w in wallets)
    assert all(w.keystores[0].key_origin == "m/84h/0h/0h" for w in wallets)
    assert all(w.descriptor and w.descriptor.startswith("wpkh(") for w in wallets)


def test_ledger_nested_account_public_key_conflict_is_rejected() -> None:
    wrapped = _versioned_bitcoin_account()
    wrapped["data"]["bitcoinResources"]["walletAccount"]["params"]["xpub"] = xpub(0x043587CF)
    with pytest.raises(ExchangeError, match="xpubs disagree"):
        load_json_obj({"data": {"accounts": [wrapped]}}, hint="ledger")


@pytest.mark.parametrize("removed", ["bitbox", "trezor", "core", "bitcoin-core", "descriptor", "interchange"])
def test_retired_import_formats_are_not_available(removed: str) -> None:
    with pytest.raises(ExchangeError, match="Unsupported wallet import format"):
        load_json_obj({"accounts": []}, hint=removed)


def test_unknown_app_json_explains_missing_ledger_data(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="app.json"):
        discover_ledger_live_app_json(environ={}, home=tmp_path, platform="linux")
