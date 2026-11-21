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

"""Public wallet importers for Bitcoin Safe."""

from .adapters import (
    from_bitbox_config,
    from_descriptor,
    from_green,
    from_ledger_account,
    from_sparrow_json,
    from_specter,
    from_trezor_account,
    import_bip329_jsonl,
    import_specter_address_csv,
    load_file,
    load_json_obj,
)
from .additional import from_wasabi
from .bitcoin_safe_bridge import apply_bip329_labels, make_protowallet
from .electrum import decrypt_electrum, from_electrum
from .h2_verify import verify_sparrow_h2_password
from .ledger_live_db import decrypt_ledger_live_accounts, from_ledger_live_app
from .model import UTXO, ExchangeError, Keystore, Label, PasswordRequired, WalletExchange
from .passwords import verify_wasabi_password
from .sparrow_h2 import from_sparrow_h2_rows, load_sparrow_h2

__all__ = [
    "ExchangeError",
    "PasswordRequired",
    "Keystore",
    "Label",
    "UTXO",
    "WalletExchange",
    "from_descriptor",
    "from_specter",
    "from_sparrow_json",
    "from_bitbox_config",
    "from_trezor_account",
    "from_ledger_account",
    "from_ledger_live_app",
    "decrypt_ledger_live_accounts",
    "from_green",
    "import_bip329_jsonl",
    "import_specter_address_csv",
    "load_file",
    "load_json_obj",
    "make_protowallet",
    "apply_bip329_labels",
    "load_sparrow_h2",
    "from_sparrow_h2_rows",
    "from_electrum",
    "decrypt_electrum",
    "from_wasabi",
    "verify_wasabi_password",
    "verify_sparrow_h2_password",
]
