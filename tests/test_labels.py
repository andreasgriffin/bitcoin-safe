import datetime

from bitcoin_safe.labels import Label, Labels, LabelType
from bitcoin_safe.util import clean_lines


def test_label_export():
    labels = Labels()
    labels.set_addr_label(
        "some_address", "my label", timestamp=datetime.datetime(2000, 1, 1, 0, 0, 0).timestamp()
    )
    labels.set_addr_category("some_address", "category 0")

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
        "timestamp": 946681200.0,
        "type": "addr",
    }

    assert (
        labels.dumps()
        == """{"VERSION": """
        + f'"{labels.VERSION}"'
        + """, "__class__": "Labels", "categories": ["category 0"], "data": {"some_address": {"VERSION": """
        + f'"{data[0].VERSION}"'
        + """, "__class__": "Label", "category": "category 0", "label": "my label", "ref": "some_address", "timestamp": 946681200.0, "type": "addr"}}}"""
    )


def test_dumps_data():
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
    assert a.timestamp == timestamp


def test_label_bip329_import():
    timestamp = datetime.datetime(2000, 1, 1, 0, 0, 0).timestamp()

    labels = Labels()
    labels.set_addr_label("some_address", "my label", timestamp=timestamp)
    labels.set_addr_category("some_address", "category 0")

    s = labels.export_bip329_jsonlines()

    labels2 = Labels()
    labels2.import_bip329_jsonlines(s, timestamp=timestamp)

    assert labels.data == labels2.data

    assert labels2.get_category("some_address") == "category 0"
    assert labels2.get_label("some_address") == "my label"


def test_import():
    s = """
    
    {"type": "tx", "ref": "f91d0a8a78462bc59398f2c5d7a84fcff491c26ba54c4833478b202796c8aafd", "label": "Transaction", "origin": "wpkh([d34db33f/84'/0'/0'])"}
            {"type": "addr", "ref": "bc1q34aq5drpuwy3wgl9lhup9892qp6svr8ldzyy7c", "label": "Address"}
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
    assert labels.get_label("bc1q34aq5drpuwy3wgl9lhup9892qp6svr8ldzyy7c") == "Address"
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
