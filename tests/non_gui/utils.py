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


import logging
from typing import List, Optional

import bdkpython as bdk
from bitcoin_usb.software_signer import derive

from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.wallet import ProtoWallet

from .test_signers import test_seeds

logger = logging.getLogger(__name__)


def create_keystore(seed_str: str, key_origin: str, label: str, network=bdk.Network.REGTEST) -> KeyStore:
    mnemonic = str(bdk.Mnemonic.from_string(seed_str))
    key_origin = key_origin
    xpub, fingerprint = derive(mnemonic, key_origin, network)

    return KeyStore(
        xpub,
        fingerprint,
        key_origin,
        label,
        network=network,
        mnemonic=seed_str,
        description=label,
    )


def create_test_seed_keystores(
    signers: int, key_origins: List[str], network=bdk.Network.REGTEST, test_seed_offset=0
) -> List[KeyStore]:
    keystores: List[KeyStore] = []
    for i, seed_str in enumerate(test_seeds[test_seed_offset : test_seed_offset + signers]):
        keystores.append(
            create_keystore(seed_str=seed_str, key_origin=key_origins[i], label=f"{i}", network=network)
        )
    return keystores


def create_multisig_protowallet(
    threshold: int, signers: int, key_origins: List[str], wallet_id="some id", network=bdk.Network.REGTEST
) -> ProtoWallet:

    keystores: List[Optional[KeyStore]] = create_test_seed_keystores(signers, key_origins, network)  # type: ignore

    return ProtoWallet(
        threshold=threshold,
        keystores=keystores,
        network=network,
        wallet_id=wallet_id,
    )
