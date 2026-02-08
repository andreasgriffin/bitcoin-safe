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

from __future__ import annotations

import logging

import bdkpython as bdk
import pytest
from bitcoin_qr_tools.data import ConverterMultisigWalletExport, Data, DataType

from bitcoin_safe.descriptors import from_multisig_wallet_export

logger = logging.getLogger(__name__)


def test_from_multisig_wallet_export() -> None:
    """Test from multisig wallet export."""
    s = """# Keystone Multisig setup file (created on 0439f926)
#
Name: MultiSig
Policy: 2 of 3
Format: P2WSH

Derivation: m/48'/0'/0'/2'
0439F926: Zpub74Jru6aftwwHxCUCWEvP6DgrfFsdA4U6ZRtQ5i8qJpMcC39yZGv3egBhQfV3MS9pZtH5z8iV5qWkJsK6ESs6mSzt4qvGhzJxPeeVS2e1zUG
Derivation: m/48'/0'/0'/2'
A32EFFFD: Zpub75UB4yd3NBeRmYLa6cjEMLH512cBgqS5SmVhhQoF6NFciXhKosNFQr74cjDAqtGapYBXJL7D3YN59kGr8d6aSNcrVNgZLLSS3Z1EHURN8qG
Derivation: m/48'/0'/0'/2'
95AF25EF: Zpub75PxF38JVVfjW4whYWpS7CMs4g88N7D187jnJx5RKPzRrxq3jMgCdRyz1ayQHrw9NhWbHmrzrB9UhpTxHwUWGSuHNzbdv9hZ6q74DBxpRQ6
"""

    # Parse the text export and convert into a descriptor.
    data = Data.from_str(s, network=bdk.Network.BITCOIN)
    assert data.data_type == DataType.MultisigWalletExport
    assert isinstance(data.data, ConverterMultisigWalletExport)
    descriptor = from_multisig_wallet_export(data.data, network=bdk.Network.BITCOIN)
    assert isinstance(descriptor, bdk.Descriptor)

    # see also https://jlopp.github.io/xpub-converter/
    # Descriptor string should match the known output for this export.
    assert (
        str(descriptor)
        == "wsh(sortedmulti(2,[0439f926/48'/0'/0'/2']xpub6DkFAXWQ2dHxq2vatrt9qyA3bXYU4ToWQwCHbf5XB2mSTexcHZCeKS1VZYcPoBd5X8yVcbXFHJR9R8UCVpt82VX1VhR28mCyxUFL4r6KFrf/<0;1>/*,[95af25ef/48'/0'/0'/2']xpub6EqLWU42dB2QNuQ5w8nCrwq3zwnyGWYQyd3fpu27BcQG8adgTdxoJBonAU6kjcQQKxCzvEfm3e3sp5d4ZKVXXVRQor6PLvbafehtr8QwtgS/<0;1>/*,[a32efffd/48'/0'/0'/2']xpub6EuZLQYmVs16eNnxVEh175kFwJH2bEmVJGobDMjvxafSz9VxY9er5bvrmcLXHdjqmnsvvnuyF1GUG1RxQ17bhR8yvEBJm7LTcNc4vKY7xds/<0;1>/*))#j5x0rym8"
    )


def test_from_multisig_wallet_export_incompatible() -> None:
    """Test from multisig wallet export incompatible."""
    s = """# Coldcard Multisig setup file (created by Sparrow)
#
Name: jhdfgre
Policy: 2 of 2
Derivation: m/48'/1'/0'/1'
Format: P2WSH-P2SH

7C85F2B5: tpubDEBYeoKBCaY1fZ3PSpdYjeedEx5oWowEn8Pa8pS19RWQK5bvAJVFa7Qe8N8e6uCxtwJvwtWiGnHawY3GwbHiUtv17RUpL3FYxckC5QmRWip
34BE20D9: tpubDEGiMrEBpyW7bqPePiQQ9FV2FsLnqwewrVL4HRByVoXnAohhi73iBGMFc5zKfRJ5ZipYmumysgxR7Uw6ZPz5NaAjzZuxWv2CfU7gutnV52o
    """

    # Parse an export with an incompatible format order.
    data = Data.from_str(s, network=bdk.Network.REGTEST)
    assert data.data_type == DataType.MultisigWalletExport
    assert isinstance(data.data, ConverterMultisigWalletExport)

    # This format ordering is not handled; ensure we raise.
    with pytest.raises(Exception):  # noqa: B017
        # https://github.com/bitcoin/bips/blob/master/bip-0048.mediawiki
        # clearly specifies
        # Nested Segwit (p2sh-p2wsh) mainnet, account 0: 1': Nested Segwit (p2sh-p2wsh) m/48'/0'/0'/1'
        # however the wallet export reverses this order of P2WSH-P2SH
        # Currently I dont have a consitent way of handling this, therefore it is better to raise an error here.
        descriptor = from_multisig_wallet_export(data.data, network=bdk.Network.REGTEST)
        assert isinstance(descriptor, bdk.Descriptor)
