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

import bdkpython as bdk
from bitcoin_usb.software_signer import SoftwareSigner

from tests.util import make_psbt

from ..setup_fulcrum import Faucet

logger = logging.getLogger(__name__)
import logging


def test_compare_software_signer_to_bdk(
    faucet: Faucet,
):
    wallet = faucet.bdk_wallet

    psbt = make_psbt(
        bdk_wallet=wallet,
        network=faucet.network,
        destination_address=str(wallet.reveal_next_address(keychain=bdk.KeychainKind.EXTERNAL).address),
        amount=1000,
        fee_rate=100,
    )

    # SoftwareSigner
    software_signer = SoftwareSigner(
        mnemonic=str(faucet.mnemonic),
        network=faucet.network,
        receive_descriptor=str(faucet.descriptor),
        change_descriptor=str(faucet.change_descriptor),
    )
    software_signed_psbt = software_signer.sign_psbt(psbt)
    software_tx = software_signed_psbt.extract_tx().serialize()

    #
    success = faucet.bdk_wallet.sign(psbt, None)
    assert success
    tx = psbt.extract_tx().serialize()

    assert software_tx == tx
