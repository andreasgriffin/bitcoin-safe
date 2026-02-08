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

import json
import time

import bdkpython as bdk

from bitcoin_safe.labels import AUTOMATIC_TIMESTAMP
from bitcoin_safe.wallet import Wallet

from ..helpers import TestConfig
from .utils import create_multisig_protowallet


def test_chained_label_timestamp_updates() -> None:
    """Chain several label operations and assert timestamp semantics.

    The test follows the flow of automatically assigned timestamps, manual updates and label imports to ensure
    the timestamp logic works as intended.
    """

    protowallet = create_multisig_protowallet(
        threshold=1,
        signers=1,
        key_origins=["m/41h/1h/0h/2h"],
        wallet_id="test",
        network=bdk.Network.REGTEST,
    )

    config = TestConfig()
    config.network = bdk.Network.REGTEST
    wallet = Wallet.from_protowallet(protowallet=protowallet, config=config, loop_in_thread=None)

    # Use a fresh receiving address for timestamp changes.
    addr = str(wallet.get_force_new_address(is_change=False).address)

    # 1) Automatic category assignment uses the special AUTOMATIC_TIMESTAMP so
    #    that later manual labels can override it.
    wallet.set_addr_category_if_unused("auto", addr)
    assert wallet.labels.get_timestamp(addr) == AUTOMATIC_TIMESTAMP

    # 2) Manually setting a label uses "now" and must have a greater timestamp.
    wallet.labels.set_addr_label(addr, "manual-0")
    timestamp_manual = wallet.labels.get_timestamp(addr)
    assert timestamp_manual and timestamp_manual > AUTOMATIC_TIMESTAMP

    # 3) Providing an older timestamp must not decrease the stored timestamp.
    wallet.labels.set_addr_label(addr, "manual-old", timestamp=timestamp_manual - 1000)
    assert wallet.labels.get_timestamp(addr) == timestamp_manual

    # 4) A subsequent "now" overwrites the previous timestamp.
    time.sleep(0.01)
    wallet.labels.set_addr_label(addr, "manual-new")
    timestamp_new = wallet.labels.get_timestamp(addr)
    assert timestamp_new and timestamp_new > timestamp_manual

    # 5) Manually setting the category refreshes the timestamp again.
    time.sleep(0.01)
    wallet.labels.set_addr_category(addr, "cat-0")
    timestamp_cat = wallet.labels.get_timestamp(addr)
    assert timestamp_cat and timestamp_cat > timestamp_new

    time.sleep(0.01)

    # 6) Renaming the category touches the label and therefore updates timestamp.
    wallet.labels.rename_category("cat-0", "cat-1")
    timestamp_renamed = wallet.labels.get_timestamp(addr)
    assert timestamp_renamed and timestamp_renamed > timestamp_cat

    # Prepare dumps for import checks.
    current_dump = wallet.labels.data[addr].dump()

    # 7) Importing a label with an older timestamp must not overwrite data.
    older = current_dump.copy()
    older["label"] = "import-old"
    older["timestamp"] = timestamp_renamed - 1000
    wallet.labels.import_dumps_data(json.dumps(older))
    assert wallet.labels.get_label(addr) == "manual-new"  # label untouched
    assert wallet.labels.get_timestamp(addr) == timestamp_renamed

    # 8) Importing with a newer timestamp should overwrite label and timestamp.
    newer = current_dump.copy()
    newer["label"] = "import-new"
    newer["timestamp"] = timestamp_renamed + 1000
    wallet.labels.import_dumps_data(json.dumps(newer))
    assert wallet.labels.get_label(addr) == "import-new"
    assert wallet.labels.get_timestamp(addr) and wallet.labels.get_timestamp(addr) > timestamp_renamed
