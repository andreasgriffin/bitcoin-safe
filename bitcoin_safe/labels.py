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
from datetime import datetime

from bitcoin_safe.util import jsonlines_to_list_of_dict, list_of_dict_to_jsonlines

logger = logging.getLogger(__name__)
import copy
import json
from typing import Any, Dict, List, Literal, Union

from bitcoin_qrreader.bitcoin_qr import Data, DataType
from packaging import version

from .pythonbdk_types import *
from .storage import BaseSaveableClass

# see https://github.com/bitcoin/bips/blob/master/bip-0329.mediawiki


class Key(enum.Enum):
    type = enum.auto()
    ref = enum.auto()
    label = enum.auto()
    origin = enum.auto()
    spendable = enum.auto()
    category = enum.auto()
    timestamp = enum.auto()


class LabelType:
    tx = "tx"
    addr = "addr"
    pubkey = "pubkey"
    input = "input"
    output = "output"
    xpub = "xpub"


class Label(SaveAllClass):
    VERSION = "0.0.1"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }
    bip329_keys = ["type", "ref", "label"]

    def __init__(
        self,
        type: str,
        ref: str,
        label: Optional[str] = None,
        origin: Optional[str] = None,
        spendable: Optional[bool] = None,
        category: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        super().__init__()
        self.type = type
        self.ref = ref
        self.label = label
        self.origin = origin
        self.spendable = spendable
        self.category = category
        self.timestamp = timestamp

    def dump(self, preserve_bip329_keys=True) -> Dict:
        d = super().dump()

        # remove the  key:value with value==none
        for key in list(d.keys()):
            if preserve_bip329_keys and key in self.bip329_keys:
                continue
            if d[key] is None:
                del d[key]

        return d

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        # now the version is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Label):
            return False
        return self.dump() == other.dump()


class Labels(BaseSaveableClass):
    VERSION = "0.0.5"
    known_classes = {**BaseSaveableClass.known_classes, "Label": Label}

    def __init__(
        self,
        data: Dict[str, Label] = None,
        categories: Optional[List[str]] = None,
    ) -> None:
        super().__init__()

        # "bc1q34aq5drpuwy3wgl9lhup9892qp6svr8ldzyy7c":{ "type": "addr", "ref": "bc1q34aq5drpuwy3wgl9lhup9892qp6svr8ldzyy7c", "label": "Address" }
        self.data: Dict[str, Label] = data if data else {}
        self.categories: List[str] = categories if categories else []

        self.separator = ";;"

    def add_category(self, value: str):
        if value not in self.categories:
            self.categories.append(value)

    def del_item(self, ref: str):
        if ref in self.data:
            del self.data[ref]

    def get_label(self, ref: str, default_value: str = None) -> Optional[str]:
        item = self.data.get(ref)
        if not item:
            return default_value
        return item.label

    def get_category(self, ref: str, default_value=None) -> Optional[str]:
        item = self.data.get(ref)
        if not item or item.category is None:
            return default_value if default_value else self.get_default_category()

        return item.category

    def get_timestamp(self, ref: str, default_value=None) -> Optional[float]:
        item = self.data.get(ref)
        if not item or not item.timestamp:
            return default_value

        return item.timestamp

    def set_label(self, type: str, ref: str, label_value, timestamp: Union[Literal["now"], float] = None):
        label = self.data.get(ref)
        if not label:
            self.data[ref] = label = Label(type, ref)

        label.label = label_value

        if timestamp:
            label.timestamp = datetime.now().timestamp() if timestamp == "now" else timestamp

        if all(value is None for value in [label.category, label.spendable, label.label, label.origin]):
            del self.data[ref]

    def set_category(self, type: str, ref: str, category, timestamp: Union[Literal["now"], float] = None):
        label = self.data.get(ref)
        if not label:
            self.data[ref] = label = Label(type, ref)

        label.category = category

        if timestamp:
            label.timestamp = datetime.now().timestamp() if timestamp == "now" else timestamp

        if all(value is None for value in [label.category, label.spendable, label.label, label.origin]):
            del self.data[ref]

        if category and category not in self.categories:
            self.categories.append(category)

    def set_tx_label(self, label_value, value, timestamp: Union[Literal["now"], float] = None):
        return self.set_label(LabelType.tx, label_value, value, timestamp=timestamp)

    def set_addr_label(self, ref: str, label_value, timestamp: Union[Literal["now"], float] = None):
        return self.set_label(LabelType.addr, ref, label_value, timestamp=timestamp)

    def set_pubkey_label(self, ref: str, label_value, timestamp: Union[Literal["now"], float] = None):
        return self.set_label(LabelType.pubkey, ref, label_value, timestamp=timestamp)

    def set_input_label(self, ref: str, label_value, timestamp: Union[Literal["now"], float] = None):
        return self.set_label(LabelType.input, ref, label_value, timestamp=timestamp)

    def set_output_label(self, ref: str, label_value, timestamp: Union[Literal["now"], float] = None):
        return self.set_label(LabelType.output, ref, label_value, timestamp=timestamp)

    def set_xpub_label(self, ref: str, label_value, timestamp: Union[Literal["now"], float] = None):
        return self.set_label(LabelType.xpub, ref, label_value, timestamp=timestamp)

    def set_addr_category(self, ref: str, category, timestamp: Union[Literal["now"], float] = None):
        return self.set_category(LabelType.addr, ref, category, timestamp=timestamp)

    def set_tx_category(self, ref: str, category, timestamp: Union[Literal["now"], float] = None):
        return self.set_category(LabelType.tx, ref, category, timestamp=timestamp)

    def get_default_category(self):
        return self.categories[0] if self.categories else None

    def dump(self) -> Dict:
        d = super().dump()

        d["data"] = self.data

        keys = ["categories"]
        for k in keys:
            d[k] = copy.deepcopy(self.__dict__[k])
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs=None):
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return Labels(**dct)

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        "this class should be overwritten in child classes"
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            if "data" in dct:
                #
                dct["flat_data"] = list(dct["data"].values())
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.1"):
            if "flat_data" in dct:
                #
                del dct["flat_data"]
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.4"):
            if "data" in dct:
                #
                dct["data"] = {k: Label(**v) for k, v in dct["data"].items()}

        # now the VERSION is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    def _convert_item_to_bip329(self, label: Label) -> Dict:

        new_label: Label = label.clone()

        if new_label.category:
            new_label.label = (
                f'{new_label.category}{self.separator}{new_label.label if new_label.label else ""}'
            )
            new_label.category = None

        # remove keys, that are non bip329
        new_label.timestamp = None

        dct = new_label.dump()
        del dct["__class__"]
        del dct["VERSION"]
        return dct

    def _bip329_dict_to_label(self, d: Dict, timestamp: Union[Literal["now"], float] = "now") -> Label:
        label = Label(**d)

        if label.label and (not label.category) and self.separator in label.label:
            label.category, label.label = label.label.split(self.separator, 1)

        # this prevents that imported labels are overwritten by old syncronizations
        if timestamp == "now":
            label.timestamp = datetime.now().timestamp()
        elif timestamp:
            label.timestamp = timestamp
        return label

    def export_bip329_jsonlines(self):
        list_of_dict = [self._convert_item_to_bip329(item) for item in self.data.values()]
        return list_of_dict_to_jsonlines(list_of_dict)

    def import_bip329_jsonlines(
        self, jsonlines: str, fill_categories=True, timestamp: Union[Literal["now"], float] = "now"
    ) -> Dict[str, Label]:
        list_of_dict = jsonlines_to_list_of_dict(jsonlines)
        labels = [self._bip329_dict_to_label(d, timestamp=timestamp) for d in list_of_dict]
        return self.import_labels(labels=labels, fill_categories=fill_categories)

    def import_electrum_wallet_json(
        self,
        file_content: str,
        network: bdk.Network,
        fill_categories=True,
        timestamp: Union[Literal["now"], float] = "now",
    ) -> Dict[str, Label]:
        electrum_dict = json.loads(file_content)
        list_of_dict = []
        for key, label in electrum_dict.items():
            data = Data.from_str(key, network)
            data_type = "addr"
            if data.data_type == DataType.Txid:
                data_type = "tx"
            list_of_dict.append({"type": data_type, "ref": key, "label": label})

        labels = [self._bip329_dict_to_label(d, timestamp=timestamp) for d in list_of_dict]
        return self.import_labels(labels=labels, fill_categories=fill_categories)

    def _do_overwrite(self, new_label: Label, old_label: Optional[Label]) -> bool:
        if not old_label:
            return True
        if not new_label.timestamp:
            return False
        if not old_label.timestamp:
            return True
        return new_label.timestamp > old_label.timestamp

    def import_labels(self, labels: List[Label], fill_categories=True) -> Dict[str, Label]:
        changed_data: Dict[str, Label] = {}

        for label in labels:
            if self.data.get(label.ref) != label and self._do_overwrite(
                new_label=label, old_label=self.data.get(label.ref)
            ):
                self.data[label.ref] = label
                changed_data[label.ref] = label

        if fill_categories:
            for item in self.data.values():
                if item.category is None:
                    continue
                if item.category not in self.categories:
                    self.categories.append(item.category)
        return changed_data

    def dumps_data_jsonlines(self, refs: list[str] = None):
        return list_of_dict_to_jsonlines(
            [label.dump() for ref, label in self.data.items() if (refs is None) or (ref in refs)]
        )

    def import_dumps_data(self, dumps_data: str, fill_categories=True) -> Dict[str, Label]:
        labels = [Label.from_dump(label_dict) for label_dict in jsonlines_to_list_of_dict(dumps_data)]
        return self.import_labels(labels=labels, fill_categories=fill_categories)

    def rename_category(self, old_category: str, new_category: str):
        affected_keys = []
        for key, item in list(self.data.items()):
            if item.category and item.category == old_category:
                item.category = new_category
                item.timestamp = datetime.now().timestamp()
                affected_keys.append(key)

        if old_category in self.categories:
            idx = self.categories.index(old_category)
            self.categories.pop(idx)
            self.categories.insert(idx, new_category)
        return affected_keys

    def delete_category(self, category: str) -> List[str]:
        affected_keys = []
        for key, item in list(self.data.items()):
            if item.category and item.category == category:
                affected_keys.append(key)
                item.category = self.get_default_category()
                item.timestamp = datetime.now().timestamp()

        if category in self.categories:
            idx = self.categories.index(category)
            self.categories.pop(idx)

        return affected_keys
