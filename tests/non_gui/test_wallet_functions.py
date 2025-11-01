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

import bdkpython as bdk
from bitcoin_usb.address_types import AddressTypes

from bitcoin_safe.util import filename_clean
from bitcoin_safe.wallet import (
    LOCAL_TX_LAST_SEEN,
    ProtoWallet,
    TxStatus,
    is_in_mempool,
    is_local,
)


def test_is_local_and_in_mempool():
    """Test is local and in mempool."""
    unconfirmed_local = bdk.ChainPosition.UNCONFIRMED(timestamp=LOCAL_TX_LAST_SEEN)
    assert is_local(unconfirmed_local)
    assert not is_in_mempool(unconfirmed_local)

    unconfirmed_mempool = bdk.ChainPosition.UNCONFIRMED(timestamp=LOCAL_TX_LAST_SEEN + 1)
    assert not is_local(unconfirmed_mempool)
    assert is_in_mempool(unconfirmed_mempool)

    confirmed = bdk.ChainPosition.CONFIRMED(
        confirmation_block_time=bdk.ConfirmationBlockTime(
            block_id=bdk.BlockId(height=5, hash="00" * 32),
            confirmation_time=123,
        ),
        transitively=None,
    )
    assert not is_local(confirmed)
    assert not is_in_mempool(confirmed)


def test_txstatus_states():
    # Confirmed transaction
    """Test txstatus states."""
    confirmed_cp = bdk.ChainPosition.CONFIRMED(
        confirmation_block_time=bdk.ConfirmationBlockTime(
            block_id=bdk.BlockId(height=5, hash="00" * 32),
            confirmation_time=123,
        ),
        transitively=None,
    )
    confirmed_status = TxStatus(
        tx=None,
        chain_position=confirmed_cp,
        get_height=lambda: 10,
    )
    assert confirmed_status.is_confirmed()
    assert confirmed_status.confirmations() == 6
    assert confirmed_status.sort_id() == 6

    # Unconfirmed transaction
    unconfirmed_cp = bdk.ChainPosition.UNCONFIRMED(timestamp=LOCAL_TX_LAST_SEEN + 1)
    unconfirmed_status = TxStatus(
        tx=None,
        chain_position=unconfirmed_cp,
        get_height=lambda: 0,
    )
    assert unconfirmed_status.is_unconfirmed()
    assert unconfirmed_status.confirmations() == 0
    assert unconfirmed_status.can_rbf()

    # Local transaction
    local_cp = bdk.ChainPosition.UNCONFIRMED(timestamp=LOCAL_TX_LAST_SEEN)
    local_status = TxStatus(
        tx=None,
        chain_position=local_cp,
        get_height=lambda: 0,
    )
    assert local_status.is_local()
    assert local_status.can_do_initial_broadcast()
    assert local_status.can_edit()


def test_filename_clean():
    """Test filename clean."""
    result = filename_clean("inv@lid name", replace_spaces_by="_")
    assert result == "invlid_name.wallet"


def test_protowallet_keystore_management():
    """Test protowallet keystore management."""
    pw = ProtoWallet(
        wallet_id="w",
        threshold=1,
        network=bdk.Network.REGTEST,
        keystores=[None],
        address_type=AddressTypes.p2wpkh,
    )
    assert not pw.is_multisig()

    pw.set_number_of_keystores(2)
    assert pw.is_multisig()
    assert len(pw.keystores) == 2

    pw.set_number_of_keystores(1)
    assert len(pw.keystores) == 1
    assert not pw.is_multisig()
