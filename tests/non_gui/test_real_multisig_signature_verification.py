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

from __future__ import annotations

import io

import bdkpython as bdk
from embit.ec import Signature
from embit.util import secp256k1

from bitcoin_safe.input_signature_verifier import (
    InputVerdict,
    Prevout,
    _normalize_low_s,
    verify_transaction,
)

# Parent transaction that created the 2-of-3 P2WSH output spent by SPEND_HEX.
PARENT_HEX = "0200000001ea6fcddf135b57eb5bdb3bec572b76f1318e733fea8692847cb83babf68961c80000000000fdffffff01ab1900000000000022002060342ed5f202c24ddae8785a902a00d9b73c5f9866d4a8d289ef549b752bf8d1cfdf0e00"

# Valid 2-of-3 P2WSH spend (witness: empty dummy, 2 signatures, witnessScript).
SPEND_HEX = (
    "02000000000101dbabc111bafc8d2a4911170998bec31ace6da52bf186c41662737ab052c49748"
    "0000000000fdffffff010c190000000000002200202a191bc32dcf444f378b5213e3f3eb301fd3dce56d17c107a6c7c06b57f9410f0400483045022100fb90495572b22709ae6b88fb7238204283d063d3e04c0776ec2f0b56197c7ded022067eae80f0615e6c5bfa24a7b3dfba87294b790ed6b50dbabee2288b6637b29eb0147304402203c81761df3c4e4069b3bf872a8bf373cf0b50da604cd1cf9b1cd90de5e67376302204723068e7989b98fddb965a0d1286857e7f03481cdab20b23aa39c1fe441095301695221025cba20175e8b162adaf71f63a2c5b7164895ef887100750108f82aae2c96d7ce210396b9f6d19d7466801fbe9f471ef227ddb08d0b4540c69cd8dc1b24fcd5637fb92103abd2bce24cb3a5a8ab485016a6d6bbfd1c650a5f3d24ec56c36d79ec7f44112b53aed1df0e00"
)


def test_real_2_of_3_p2wsh_spend_is_valid() -> None:
    parent = bdk.Transaction(bytes.fromhex(PARENT_HEX))
    spend = bdk.Transaction(bytes.fromhex(SPEND_HEX))

    # The spend must reference the parent transaction's output 0.
    spent_outpoint = spend.input()[0].previous_output
    assert str(spent_outpoint.txid) == str(parent.compute_txid())
    assert spent_outpoint.vout == 0

    parent_output = parent.output()[0]
    prevout = Prevout(
        script_pubkey=bytes(parent_output.script_pubkey.to_bytes()),
        value=parent_output.value.to_sat(),
    )

    result = verify_transaction(spend, [prevout], [True])

    assert result.verdicts == [InputVerdict.valid]


# Order n of secp256k1, written independently of the implementation under test.
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _der_signature(r: int, s: int) -> bytes:
    compact = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return secp256k1.ecdsa_signature_serialize_der(secp256k1.ecdsa_signature_parse_compact(compact))


def _signature_parts(signature: Signature) -> tuple[int, int]:
    stream = io.BytesIO()
    signature.write_to(stream)
    compact = secp256k1.ecdsa_signature_serialize_compact(
        secp256k1.ecdsa_signature_parse_der(stream.getvalue())
    )
    return int.from_bytes(compact[:32], "big"), int.from_bytes(compact[32:], "big")


def test_high_s_signature_is_normalized_to_low_s() -> None:
    r, high_s = 12345, SECP256K1_N - 1
    assert _signature_parts(_normalize_low_s(_der_signature(r, high_s))) == (r, 1)


def test_low_s_signature_is_unchanged() -> None:
    r, s = 12345, SECP256K1_N // 2
    assert _signature_parts(_normalize_low_s(_der_signature(r, s))) == (r, s)


def test_s_just_above_half_order_is_normalized() -> None:
    r, s = 12345, SECP256K1_N // 2 + 1
    assert _signature_parts(_normalize_low_s(_der_signature(r, s))) == (r, SECP256K1_N // 2)
