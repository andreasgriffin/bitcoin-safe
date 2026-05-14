#
# Bitcoin Safe
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

from __future__ import annotations

from bitcoin_safe.hardware_signers import FeatureLevel, HardwareSigners


def test_list_brands_is_stable_and_unique() -> None:
    """Test brands are returned once in declaration order."""
    assert HardwareSigners.list_brands(include_generic=False) == [
        "Coinkite",
        "Shift Crypto",
        "Blockstream",
        "Foundation",
        "Keystone",
        "Trezor",
        "Ledger",
        "Specter",
        "SeedSigner",
        "Krux",
    ]


def test_models_for_brand_returns_expected_signers() -> None:
    """Test brand filtering returns the expected models."""
    assert [signer.id for signer in HardwareSigners.models_for_brand("Coinkite")] == [
        HardwareSigners.coldcard.id,
        HardwareSigners.q.id,
    ]


def test_generic_signer_is_available() -> None:
    """Test the generic signer can be resolved and exposes broad capabilities."""
    generic = HardwareSigners.from_id(HardwareSigners.generic.id)
    assert generic == HardwareSigners.generic
    assert generic
    assert generic.usb == FeatureLevel.capable
    assert generic.supports_qr


def test_q_supports_usb() -> None:
    """Test Coinkite Q is exposed as a USB-capable signer."""
    assert HardwareSigners.q.usb == FeatureLevel.supported


def test_infer_from_text_matches_display_name() -> None:
    """Test free-form text inference resolves a known display name."""
    assert HardwareSigners.infer_from_text("Krux App backup") == HardwareSigners.krux_diy


def test_signer_ids_are_unique() -> None:
    """Test each configured signer has a unique persisted identifier."""
    signer_ids = [signer.id for signer in HardwareSigners.as_list()]
    assert len(signer_ids) == len(set(signer_ids))


def test_trezor_models_resolve_by_unique_id() -> None:
    """Test Trezor models are individually addressable by their persisted identifier."""
    assert HardwareSigners.from_id(HardwareSigners.trezor5.id) == HardwareSigners.trezor5
    assert HardwareSigners.from_id(HardwareSigners.trezor3.id) == HardwareSigners.trezor3
    assert HardwareSigners.from_id(HardwareSigners.trezor7.id) == HardwareSigners.trezor7


def test_trezor_models_keep_shared_screenshot_assets() -> None:
    """Test distinct Trezor models still point at the bundled shared tutorial screenshots."""
    assert HardwareSigners.trezor5.generate_seed_png == "trezor-generate-seed.png"
    assert HardwareSigners.trezor3.wallet_export_png == "trezor-wallet-export.png"
    assert HardwareSigners.trezor7.register_multisig_decriptor_png == (
        "trezor-register-multisig-decriptor.png"
    )
