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

import json
from pathlib import Path

import pytest

from bitcoin_safe.wallet_import.adapters import load_file
from bitcoin_safe.wallet_import.model import ExchangeError, WalletExchange, _assert_no_secrets
from bitcoin_safe.wallet_import.verification import address_from_public_keys

WALLET_DIR = Path(__file__).parents[2] / "data" / "wallet imports"


def test_import_wasabi_wallet_fixture() -> None:
    wallets = load_file(WALLET_DIR / "wasabi single sig.json")
    assert len(wallets) == 2
    for wallet, address_type, purpose, prefix in zip(
        wallets, ("P2WPKH", "P2TR"), (84, 86), ("wpkh(", "tr("), strict=True
    ):
        assert wallet.source_wallet == "wasabi"
        assert wallet.network == "regtest"
        assert wallet.threshold == 1
        assert wallet.address_type == address_type
        assert wallet.descriptor and wallet.descriptor.startswith(prefix)
        assert len(wallet.keystores) == 1
        key = wallet.keystores[0]
        assert key.key_origin == f"m/{purpose}h/0h/0h"
        assert key.xpub and key.xpub.startswith("tpub")
        assert key.recovery_material == "PRIVATE_KEY_REDACTED"
        assert "6PYTvTFQ" not in wallet.to_json()
    assert [(label.ref, label.label) for label in wallets[0].labels] == [
        ("bcrt1qxvqyy8hasw4n9cgl90qwvlc4thrkl5wgnlrulh", "segwittt")
    ]
    assert len(wallets[1].labels) == 2
    assert all(not wallet.extra.get("unresolved_path_labels") for wallet in wallets)


def test_private_extended_key_in_text_is_rejected() -> None:
    with pytest.raises(ExchangeError, match="Private extended key"):
        _assert_no_secrets("prefixxprv" + "1" * 107)


@pytest.mark.parametrize(
    ("filename", "source", "threshold", "script_type", "markers"),
    [
        ("electrum single sig", "electrum", 1, "wpkh", ["PRIVATE_KEY_REDACTED"]),
        ("electrum-multisig", "electrum", 2, "wsh", ["PRIVATE_KEY_REDACTED", None, None]),
        ("sparrow single sig.mv.db", "sparrow-h2", 1, "wpkh", ["SEED_REDACTED"]),
        ("sparrow single sig-no seed.mv.db", "sparrow-h2", 1, "wpkh", [None]),
        ("sparrow-multisig.mv.db", "sparrow-h2", 2, "wsh", ["SEED_REDACTED"] * 3),
    ],
)
def test_import_wallet_fixture(
    filename: str, source: str, threshold: int, script_type: str, markers: list[str | None]
) -> None:
    wallets = load_file(WALLET_DIR / filename, password="0000")
    assert len(wallets) == 1
    wallet = wallets[0]
    assert wallet.source_wallet == source
    assert wallet.network == "regtest"
    assert wallet.threshold == threshold
    assert wallet.address_type == script_type
    assert wallet.descriptor and wallet.descriptor.startswith(
        "wpkh(" if threshold == 1 else "wsh(sortedmulti(2,"
    )
    assert [key.recovery_material for key in wallet.keystores] == markers
    assert all(key.xpub for key in wallet.keystores)
    if source == "electrum":
        assert wallet.extra["address_verification"] == {"receiving": 3, "change": 3}
    serialized = wallet.to_json()
    assert "tprv" not in serialized and "xprv" not in serialized
    restored = WalletExchange.from_dict(json.loads(serialized))
    assert restored.descriptor == wallet.descriptor
    assert [key.recovery_material for key in restored.keystores] == [
        "BIP39_RETAINED_TESTNET" if marker == "SEED_REDACTED" else marker for marker in markers
    ]


@pytest.mark.parametrize(
    "filename",
    [
        "electrum single sig",
        "electrum-multisig",
        "sparrow single sig.mv.db",
        "sparrow single sig-no seed.mv.db",
        "sparrow-multisig.mv.db",
    ],
)
def test_wallet_fixture_rejects_wrong_password(filename: str) -> None:
    with pytest.raises(ExchangeError, match="(?i)password"):
        load_file(WALLET_DIR / filename, password="incorrect")


@pytest.mark.parametrize(
    "filenames",
    [
        ("electrum single sig", "sparrow single sig.mv.db", "sparrow single sig-no seed.mv.db"),
        ("electrum-multisig", "sparrow-multisig.mv.db"),
    ],
)
def test_matching_wallets_derive_same_addresses(filenames: tuple[str, ...]) -> None:
    wallets = [load_file(WALLET_DIR / filename, password="0000")[0] for filename in filenames]
    for branch in (0, 1):
        for index in (0, 1):
            addresses = [
                address_from_public_keys(
                    wallet.keystores, wallet.address_type, wallet.network, branch, index, wallet.threshold
                )
                for wallet in wallets
            ]
            assert len(set(addresses)) == 1
