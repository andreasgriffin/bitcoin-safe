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

import datetime
import json
from time import sleep

from bitcoin_safe.config import UserConfig
from bitcoin_safe.labels import AUTOMATIC_TIMESTAMP, Label, Labels, LabelType
from bitcoin_safe.util import clean_lines
from bitcoin_safe.wallet import Wallet

from .utils import create_multisig_protowallet


def test_label_export():
    """Test label export."""
    labels = Labels()
    timestamp = datetime.datetime(2000, 1, 1, 0, 0, 0).timestamp()
    labels.set_addr_label("some_address", "my label", timestamp=timestamp)
    labels.set_addr_category("some_address", "category 0", timestamp=timestamp)

    assert labels.dump()["__class__"] == "Labels"
    assert labels.dump()["categories"] == ["category 0"]

    data = list(labels.dump()["data"].values())
    assert len(data) == 1
    assert data[0].dump() == {
        "VERSION": data[0].VERSION,
        "__class__": "Label",
        "category": "category 0",
        "label": "my label",
        "ref": "some_address",
        "timestamp": timestamp,
        "type": "addr",
    }

    labels._snapshots = []
    assert (
        labels.dumps()
        == """{"VERSION": """
        + f'"{labels.VERSION}"'
        + """, "__class__": "Labels", "_snapshots": [], "categories": ["category 0"], "data": {"some_address": {"VERSION": """
        + f'"{data[0].VERSION}"'
        + ', "__class__": "Label", "category": "category 0", "label": "my label", "ref": "some_address", "timestamp": '
        + f"{timestamp}"
        + ', "type": "addr"}}, "default_category": "default"}'
    )


def test_dumps_data():
    """Test dumps data."""
    timestamp = datetime.datetime(2000, 1, 1, 0, 0, 0).timestamp()

    labels = Labels()
    labels.set_addr_label("some_address", "my label", timestamp=timestamp)
    labels.set_addr_category("some_address", "category 0")

    serialized_labels = labels.dumps_data_jsonlines()

    labels2 = Labels()
    labels2.import_dumps_data(serialized_labels)

    assert labels.data == labels2.data

    assert labels2.get_category("some_address") == "category 0"
    assert labels2.get_label("some_address") == "my label"

    a = labels2.data.get("some_address")
    assert isinstance(a, Label)
    # the 2. assignment set_addr_category("some_address", "category 0" )
    # should update the timestamp. therefore  is should NOT be the old timestamp
    assert a.timestamp != timestamp


def test_preservebip329_keys_for_single_label():
    """Test preservebip329 keys for single label."""
    import json

    labels = Labels()
    labels.set_addr_category("some_address", "category 0", timestamp=0)

    serialized_labels = labels.dumps_data_jsonlines()

    jsondict = json.loads(serialized_labels)
    for key in Label.bip329_keys:
        assert key in jsondict

    assert (
        serialized_labels
        == '{"__class__": "Label", "VERSION": "0.0.3", "type": "addr", "ref": "some_address", "label": null, "category": "category 0", "timestamp": 0}'
    )


def test_label_bip329_import():
    """Test label bip329 import."""
    timestamp = datetime.datetime(2000, 1, 1, 0, 0, 0).timestamp()

    labels = Labels()
    labels.set_addr_label("some_address", "my label", timestamp=timestamp)
    labels.set_addr_category("some_address", "category 0", timestamp=timestamp)

    s = labels.export_bip329_jsonlines()
    assert s == '{"type": "addr", "ref": "some_address", "label": "my label #category 0"}'

    labels2 = Labels()
    labels2.import_bip329_jsonlines(s, timestamp=timestamp)

    assert labels.data == labels2.data

    assert labels2.get_category("some_address") == "category 0"
    assert labels2.get_label("some_address") == "my label"


def test_label_bip329_import_with_timestamp():
    """Test label bip329 import with timestamp."""
    timestamp = datetime.datetime(2000, 1, 1, 0, 0, 0).timestamp()

    d = {"type": "addr", "ref": "some_address", "label": "my label #category 0", "timestamp": timestamp}
    s = json.dumps(d)

    labels2 = Labels()
    labels2.import_bip329_jsonlines(s)

    assert labels2.data["some_address"].dump() == {
        "__class__": "Label",
        "VERSION": "0.0.3",
        "type": "addr",
        "ref": "some_address",
        "label": "my label",
        "category": "category 0",
        "timestamp": timestamp,
    }


def test_label_bip329_category_drop_multiple_categories():
    """Test label bip329 category drop multiple categories."""
    s = '{"type": "addr", "ref": "some_address", "label": "my label #category 0 #category 1"}'

    labels2 = Labels()
    labels2.import_bip329_jsonlines(s)

    assert labels2.get_category("some_address") == "category 0"
    # dropping second category
    assert labels2.get_label("some_address") == "my label"


def test_label_bip329_category_bad_input():
    # empty
    """Test label bip329 category bad input."""
    s = '{"type": "addr", "ref": "some_address", "label": "my label #"}'

    labels2 = Labels()
    labels2.import_bip329_jsonlines(s)
    assert labels2.get_category("some_address") == labels2.default_category
    assert labels2.get_label("some_address") == "my label"

    #   double hashtag
    s = '{"type": "addr", "ref": "some_address", "label": "my label ##category 0"}'

    labels2 = Labels()
    labels2.import_bip329_jsonlines(s)
    assert labels2.get_category("some_address") == "category 0"
    assert labels2.get_label("some_address") == "my label"

    #   double hashtag with spaces
    s = '{"type": "addr", "ref": "some_address", "label": "my label # ### category 0 # ## category 1"}'

    labels2 = Labels()
    labels2.import_bip329_jsonlines(s)
    assert labels2.get_category("some_address") == "category 0"
    assert labels2.get_label("some_address") == "my label"


def test_import():
    """Test import."""
    s = """
    
    {"type": "tx", "ref": "f91d0a8a78462bc59398f2c5d7a84fcff491c26ba54c4833478b202796c8aafd", "label": "Transaction", "origin": "wpkh([d34db33f/84'/0'/0'])"}
            {"type": "addr", "ref": "tb1q6xhxcrzmjwf6ce5jlj08gyrmu4eq3zwpv0ss3f", "label": "Address"}
            {"type": "pubkey", "ref": "0283409659355b6d1cc3c32decd5d561abaac86c37a353b52895a5e6c196d6f448", "label": "Public Key"}
            {"type": "input", "ref": "f91d0a8a78462bc59398f2c5d7a84fcff491c26ba54c4833478b202796c8aafd:0", "label": "Input"}
            {"type": "output", "ref": "f91d0a8a78462bc59398f2c5d7a84fcff491c26ba54c4833478b202796c8aafd:1", "label": "Output", "spendable": "false"}
            {"type": "xpub", "ref": "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8", "label": "Extended Public Key"}
            {"type": "tx", "ref": "f546156d9044844e02b181026a1a407abfca62e7ea1159f87bbeaa77b4286c74", "label": "Account #1 Transaction", "origin": "wpkh([d34db33f/84'/0'/1'])"}

            """

    labels = Labels()
    labels.import_bip329_jsonlines(s)

    assert len(labels.data) == 7
    assert (
        labels.get_label("f91d0a8a78462bc59398f2c5d7a84fcff491c26ba54c4833478b202796c8aafd") == "Transaction"
    )
    assert labels.get_label("tb1q6xhxcrzmjwf6ce5jlj08gyrmu4eq3zwpv0ss3f") == "Address"
    assert (
        labels.get_label("0283409659355b6d1cc3c32decd5d561abaac86c37a353b52895a5e6c196d6f448") == "Public Key"
    )
    assert labels.get_label("f91d0a8a78462bc59398f2c5d7a84fcff491c26ba54c4833478b202796c8aafd:0") == "Input"

    l1 = labels.data.get(
        "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"
    )
    assert isinstance(l1, Label)
    assert l1.type == LabelType.xpub

    l2 = labels.data.get("f546156d9044844e02b181026a1a407abfca62e7ea1159f87bbeaa77b4286c74")
    assert isinstance(l2, Label)
    assert l2.type == LabelType.tx

    cleaned_s = "\n".join(clean_lines(s.strip().splitlines()))
    assert cleaned_s == labels.export_bip329_jsonlines()


def test_label_timestamp_correctly(test_config: UserConfig):
    """Automatic category setting also sets a timestamp.

    It is crucial that the automatic timestamp is in the far past, such that when exchaning labels with
    another wallet with manual timestamps, the manual ones superceed the automatic ones.
    """

    def set_timestamps(w: Wallet):
        """Set timestamps."""
        address_info_manual = w.get_address(force_new=True)
        w.labels.set_category(type=LabelType.addr, ref=str(address_info_manual.address), category="manual")
        assert (
            timestamp_manual := w.labels.get_timestamp(str(address_info_manual.address))
        ) and timestamp_manual > AUTOMATIC_TIMESTAMP

        address_info_manual2 = w.get_unused_category_address("manual")
        w.labels.set_addr_label(str(address_info_manual2.address), "test")
        assert (
            timestamp_manual2 := w.labels.get_timestamp(str(address_info_manual2.address))
        ) and timestamp_manual2 > AUTOMATIC_TIMESTAMP

    def check_timestamps_behavior_correct(w: Wallet):
        """Check timestamps behavior correct."""
        address_info_auto = w.get_unused_category_address("manual")
        assert w.labels.get_timestamp(str(address_info_auto.address)) == AUTOMATIC_TIMESTAMP

        assert (
            timestamp_manual := w.labels.get_timestamp("bcrt1q9mvd906xneqp0228uc8rh2nmewvuy87cf4n939")
        ) and timestamp_manual > AUTOMATIC_TIMESTAMP

        assert w.labels.get_label("bcrt1qzkdd9hcph3l2w29jfklwewctxp0hxnnlemtu47") == "test"
        assert (
            timestamp_manual2 := w.labels.get_timestamp("bcrt1qzkdd9hcph3l2w29jfklwewctxp0hxnnlemtu47")
        ) and timestamp_manual2 > AUTOMATIC_TIMESTAMP

    protowallet = create_multisig_protowallet(
        threshold=1,
        signers=1,
        key_origins=[f"m/{i + 41}h/1h/0h/2h" for i in range(5)],
        wallet_id="w org",
        network=test_config.network,
    )

    w_org = Wallet.from_protowallet(protowallet=protowallet, config=test_config, loop_in_thread=None)
    for i in range(4):
        w_org.get_force_new_address(is_change=False)

    w_org.set_addresses_category_if_unused("manual", addresses=w_org.get_addresses())

    set_timestamps(w_org)
    check_timestamps_behavior_correct(w_org)

    w_org_exported = w_org.labels.dumps_data_jsonlines()

    #
    sleep(0.1)

    protowallet2 = create_multisig_protowallet(
        threshold=1,
        signers=1,
        key_origins=[f"m/{i + 41}h/1h/0h/2h" for i in range(5)],
        wallet_id="w 2",
        network=test_config.network,
    )
    w_copy = Wallet.from_protowallet(protowallet=protowallet2, config=test_config, loop_in_thread=None)
    for i in range(4):
        w_copy.get_force_new_address(is_change=False)

    w_copy.set_addresses_category_if_unused("should_be_overwritten", addresses=w_org.get_addresses())

    w_copy_exported = w_copy.labels.dumps_data_jsonlines()

    # import into w org
    w_org.labels.import_dumps_data(w_copy_exported)

    # should have no effect
    check_timestamps_behavior_correct(w_org)

    # importing into w_copy  should work
    w_copy.labels.import_dumps_data(w_org_exported)

    check_timestamps_behavior_correct(w_copy)

    eorg = w_org.labels.dumps_data_jsonline_list()
    ecopy = w_copy.labels.dumps_data_jsonline_list()
    assert len(eorg) == len(ecopy)
    for e1, e2 in zip(eorg, ecopy, strict=False):
        assert e1 == e2
