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

"""Validation of outputs when constructing transactions."""

import bdkpython as bdk

from . import execute_config
from .i18n import translate


def validate_raw_output_script(script: bytes, amount: int = 0) -> None:
    """Check a raw output script without changing it."""
    if not script:
        raise ValueError(translate("wallet", "Output script cannot be empty."))
    if script.startswith(b"\x6a"):
        if amount:
            raise ValueError(translate("wallet", "OP_RETURN outputs must have an amount of zero."))
        if execute_config.ALLOW_OP_RETURN:
            return
    elif execute_config.ALLOW_ALL_SCRIPTS:
        return
    raise ValueError(translate("wallet", "This output script is not allowed when creating a transaction."))


def validate_transaction_outputs(tx: bdk.Transaction, network: bdk.Network) -> None:
    """Validate non-address outputs, including outputs retained by fee bumping."""
    for output in tx.output():
        script = bytes(output.script_pubkey.to_bytes())
        try:
            bdk.Address.from_script(output.script_pubkey, network)
        except Exception:
            validate_raw_output_script(script, output.value.to_sat())
