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

from bitcoin_safe.message_signature_verifyer import MessageSignatureVerifyer
from bitcoin_safe.message_signing_result import MessageSigningInfo, verify_signing_result
from bitcoin_safe.signer import seed_sign_options

from .test_seed_sign_message import _address_info, _wallet


def test_multisig_signer_identity_and_armour(test_config) -> None:
    wallet = _wallet(signers=3, test_config=test_config, threshold=2)
    address_info = _address_info(wallet, is_change=True)
    message = "  first line  \n second line\n"
    for option in seed_sign_options(wallet, address_info):
        signing_info = MessageSigningInfo(option.bip32_path, wallet.network, tuple(wallet.keystores))
        signature = option.signer.sign_message(message=message, bip32_path=option.bip32_path)
        result = verify_signing_result(message, signing_info, signature)
        assert result.signer
        assert result.signer.fingerprint.lower() == option.signer.get_fingerprint().lower()
        assert result.address != address_info.address
        assert result.armored
        verifier = MessageSignatureVerifyer()
        assert verifier.verify_message_asciguarded(result.armored).match
        assert verifier._parse_bip137_block(result.armored)[1] == message
        assert not verify_signing_result(message, signing_info, signature[:-2] + "xx").signer
        assert not verify_signing_result(message + "x", signing_info, signature).signer


def test_different_account_path_is_not_attributed(test_config) -> None:
    wallet = _wallet(signers=2, test_config=test_config, threshold=2)
    options = seed_sign_options(wallet, _address_info(wallet))
    message = "hello"
    signature = options[1].signer.sign_message(message=message, bip32_path=options[1].bip32_path)
    assert not verify_signing_result(
        message, MessageSigningInfo(options[0].bip32_path, wallet.network, tuple(wallet.keystores)), signature
    ).signer
