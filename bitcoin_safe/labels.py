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


import copy
import enum
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple, Union

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from packaging import version

from bitcoin_safe.util import (
    jsonlines_to_list_of_dict,
    list_of_dict_to_jsonline_list,
    list_of_dict_to_jsonlines,
)

from .storage import BaseSaveableClass, SaveAllClass, filtered_for_init

logger = logging.getLogger(__name__)
# see https://github.com/bitcoin/bips/blob/master/bip-0329.mediawiki


AUTOMATIC_TIMESTAMP = 0.1


class Key(enum.Enum):
    type = enum.auto()
    ref = enum.auto()
    label = enum.auto()
    origin = enum.auto()
    spendable = enum.auto()
    category = enum.auto()
    timestamp = enum.auto()


class LabelType(enum.Enum):
    tx = "tx"
    addr = "addr"
    pubkey = "pubkey"
    input = "input"
    output = "output"
    xpub = "xpub"


class Label(SaveAllClass):
    VERSION = "0.0.3"
    known_classes = {**BaseSaveableClass.known_classes, LabelType.__name__: LabelType}
    bip329_keys = ["type", "ref", "label"]
    separator = " #"

    def __init__(
        self,
        type: LabelType,
        ref: str,
        timestamp: Union[Literal["now", "old"], float],
        label: Optional[str] = None,
        origin: Optional[str] = None,
        spendable: Optional[bool] = None,
        category: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.type = type
        self.ref = ref
        self.label = label
        self.origin = origin
        self.spendable = spendable
        self.category = category
        self.timestamp = self._to_timestamp(timestamp)

    @staticmethod
    def _to_timestamp(timestamp: Union[Literal["now", "old"], float]) -> float:
        if timestamp == "now":
            return datetime.now().timestamp()
        elif timestamp == "old":
            return AUTOMATIC_TIMESTAMP
        else:
            return timestamp

    def set_timestamp(self, timestamp: Union[Literal["now", "old"], float]):
        new_timestamp = self._to_timestamp(timestamp=timestamp)
        if new_timestamp > self.timestamp:
            self.timestamp = new_timestamp

    def to_bip329(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}

        d["type"] = self.type.name
        d["ref"] = self.ref
        d["label"] = (
            f'{self.label if self.label else ""}{self.separator}{self.category}'
            if self.category
            else self.label
        )

        if self.origin is not None:
            d["origin"] = self.origin
        if self.spendable is not None:
            d["spendable"] = self.spendable
        return d

    @classmethod
    def from_bip329(
        cls, d: Dict[str, Any], timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> "Label":
        """
        Can import bip329,
        Also uses additional fields (like timestamp)
        if available.
        """
        d["timestamp"] = (
            label_timestamp
            if (label_timestamp := d.get("timestamp"))
            else (datetime.now().timestamp() if timestamp == "now" else timestamp)
        )
        d["type"] = LabelType[d["type"]]
        label = Label(**filtered_for_init(d, cls=cls))

        if label.label and (not label.category) and cls.separator in label.label:
            label.label, *categories = label.label.split(cls.separator)
            if categories:
                if len(categories) > 1:
                    logger.warning(f"categories = {categories}. Dropping all but the first non-empty.")

                for category in categories:
                    # clean category
                    category = category.replace(cls.separator.strip(), "").strip()
                    if not category:
                        continue
                    label.category = category
                    break
        return label

    def dump(self, preserve_bip329_keys=True) -> Dict:
        d = super().dump()
        d["type"] = self.type.name

        # remove the  key:value with value==none
        for key in list(d.keys()):
            if preserve_bip329_keys and key in self.bip329_keys:
                continue
            if d[key] is None:
                del d[key]

        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None):
        super()._from_dump(dct, class_kwargs=class_kwargs)

        dct["type"] = LabelType[dct["type"]]

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.1"):
            if "flat_data" in dct:
                #
                dct["timestamp"] = dct["timestamp"] if dct["timestamp"] else datetime.now().timestamp()

        return super().from_dump_migration(dct=dct)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Label):
            return False
        return self.dump() == other.dump()


class Labels(BaseSaveableClass):
    VERSION = "0.1.0"
    known_classes = {**BaseSaveableClass.known_classes, Label.__name__: Label}

    def __init__(
        self,
        data: Dict[str, Label] | None = None,
        categories: Optional[List[str]] = None,
        default_category: str = "default",
    ) -> None:
        super().__init__()

        # "tb1q6xhxcrzmjwf6ce5jlj08gyrmu4eq3zwpv0ss3f":{ "type": "addr", "ref": "tb1q6xhxcrzmjwf6ce5jlj08gyrmu4eq3zwpv0ss3f", "label": "Address" }
        self.data: Dict[str, Label] = data if data else {}
        self.categories: List[str] = categories if categories else []
        self.default_category = default_category

    def add_category(self, value: str) -> None:
        if value not in self.categories:
            self.categories.append(value)

    def del_item(self, ref: str) -> None:
        if ref in self.data:
            del self.data[ref]

    def get_label(self, ref: str, default_value: str | None = None) -> Optional[str]:
        item = self.data.get(ref)
        if not item:
            return default_value
        return item.label

    def get_category_raw(self, ref: str) -> str | None:
        item = self.data.get(ref)
        if not item or item.category is None:
            return None

        return item.category

    def get_category(self, ref: str, default_value=None) -> str:
        item = self.data.get(ref)
        if not item or item.category is None:
            return default_value if default_value else self.get_default_category()

        return item.category

    def get_timestamp(self, ref: str, default_value=None) -> Optional[float]:
        item = self.data.get(ref)
        if not item or not item.timestamp:
            return default_value

        return item.timestamp

    def set_label(
        self, type: LabelType, ref: str, label_value, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        label = self.data.get(ref)

        if not label:
            self.data[ref] = label = Label(type, ref, timestamp)

        label.label = label_value
        label.set_timestamp(timestamp)

        if all(value is None for value in [label.category, label.spendable, label.label, label.origin]):
            del self.data[ref]

    def set_category(
        self, type: LabelType, ref: str, category, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        label = self.data.get(ref)
        if not label:
            self.data[ref] = label = Label(type, ref, timestamp)

        label.category = category
        label.set_timestamp(timestamp)

        if all(value is None for value in [label.category, label.spendable, label.label, label.origin]):
            del self.data[ref]

        if category and category not in self.categories:
            self.categories.append(category)

    def set_tx_label(
        self, label_value, value, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        return self.set_label(LabelType.tx, label_value, value, timestamp=timestamp)

    def set_addr_label(
        self, ref: str, label_value, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        return self.set_label(LabelType.addr, ref, label_value, timestamp=timestamp)

    def set_pubkey_label(
        self, ref: str, label_value, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        return self.set_label(LabelType.pubkey, ref, label_value, timestamp=timestamp)

    def set_input_label(
        self, ref: str, label_value, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        return self.set_label(LabelType.input, ref, label_value, timestamp=timestamp)

    def set_output_label(
        self, ref: str, label_value, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        return self.set_label(LabelType.output, ref, label_value, timestamp=timestamp)

    def set_xpub_label(
        self, ref: str, label_value, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        return self.set_label(LabelType.xpub, ref, label_value, timestamp=timestamp)

    def set_addr_category(
        self, ref: str, category, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        return self.set_category(LabelType.addr, ref, category, timestamp=timestamp)

    def set_tx_category(
        self, ref: str, category, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> None:
        return self.set_category(LabelType.tx, ref, category, timestamp=timestamp)

    def get_default_category(self) -> str:
        return self.categories[0] if self.categories else self.default_category

    def get_category_dict_raw(self, filter_type: LabelType | None) -> Dict[str | None, List[Label]]:
        d: Dict[str | None, List[Label]] = defaultdict(list)
        for label in self.data.values():
            if filter_type and label.type != filter_type:
                continue
            d[label.category].append(label)
        return d

    def dump(self) -> Dict:
        d = super().dump()

        d["data"] = self.data
        d["default_category"] = self.default_category

        keys = ["categories"]
        for k in keys:
            d[k] = copy.deepcopy(self.__dict__[k])
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None) -> "Labels":
        super()._from_dump(dct, class_kwargs=class_kwargs)

        # handle a case of incorrectly saved labels
        # (only ever happend when there was a savings bug in a development version)
        if "data" in dct:
            for key, value in list(dct["data"].items()):
                # it should be Label
                if isinstance(value, dict):
                    # but if it is just a dict, then convert it to a label
                    dct["data"][key] = Label(**value)
                    logger.debug(f"Incorrect saved label data. Converting {value} to Label")

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
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
                dct["data"] = {
                    k: Label(**v, timestamp=datetime.now().timestamp()) for k, v in dct["data"].items()
                }
        return super().from_dump_migration(dct=dct)

    def export_bip329_jsonlines(self) -> str:
        list_of_dict = [item.to_bip329() for item in self.data.values()]
        return list_of_dict_to_jsonlines(list_of_dict)

    def import_bip329_jsonlines(
        self, jsonlines: str, fill_categories=True, timestamp: Union[Literal["now", "old"], float] = "now"
    ) -> Dict[str, Label]:
        list_of_dict = jsonlines_to_list_of_dict(jsonlines)
        labels = [Label.from_bip329(d, timestamp=timestamp) for d in list_of_dict]
        return self.import_labels(labels=labels, fill_categories=fill_categories)

    def import_electrum_wallet_json(
        self,
        file_content: str,
        network: bdk.Network,
        fill_categories=True,
        timestamp: Union[Literal["now", "old"], float] = "now",
    ) -> Dict[str, Label]:
        electrum_dict = json.loads(file_content)
        list_of_dict = []
        for key, label in electrum_dict.items():
            data = Data.from_str(key, network)
            data_type = "addr"
            if data.data_type == DataType.Txid:
                data_type = "tx"
            list_of_dict.append({"type": data_type, "ref": key, "label": label})

        labels = [Label.from_bip329(d, timestamp=timestamp) for d in list_of_dict]
        return self.import_labels(labels=labels, fill_categories=fill_categories)

    def _should_overwrite(
        self, new_label: Label, old_label: Optional[Label], tiebreaker: Optional[bool]
    ) -> bool:
        if not old_label:
            return True
        if not new_label.timestamp:
            return False
        if not old_label.timestamp:
            return True
        if new_label.timestamp == old_label.timestamp and tiebreaker is not None:
            return tiebreaker
        return new_label.timestamp > old_label.timestamp

    @staticmethod
    def get_timestamp_range(
        labels: Iterable[Label], exclude_automatic=True
    ) -> Tuple[float | None, float | None]:
        earliest_timestamp: float | None = None
        latest_timestamp: float | None = None
        for label in labels:
            if label.timestamp:
                if exclude_automatic and label.timestamp <= AUTOMATIC_TIMESTAMP:
                    continue
                earliest_timestamp = (
                    min(earliest_timestamp, label.timestamp) if earliest_timestamp else label.timestamp
                )
                latest_timestamp = (
                    max(latest_timestamp, label.timestamp) if latest_timestamp else label.timestamp
                )
        return earliest_timestamp, latest_timestamp

    def _should_overwrite_mine_when_tie(self, new_labels: List[Label]) -> None | bool:
        my_earliest_timestamp, _ = self.get_timestamp_range(self.data.values())
        other_earliest_timestamp, _ = self.get_timestamp_range(new_labels)

        if not other_earliest_timestamp:
            return False
        if not my_earliest_timestamp:
            return True

        # prefer the labels with the oldest (non_automatic) entries
        return False if my_earliest_timestamp < other_earliest_timestamp else True

    def import_labels(
        self,
        labels: List[Label],
        fill_categories=True,
        force_overwrite=False,
    ) -> Dict[str, Label]:
        changed_data: Dict[str, Label] = {}

        tiebreaker = self._should_overwrite_mine_when_tie(new_labels=labels)

        for label in labels:
            old_label = self.data.get(label.ref)

            if self.data.get(label.ref) != label and (
                force_overwrite
                or self._should_overwrite(new_label=label, old_label=old_label, tiebreaker=tiebreaker)
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

    def dumps_data_jsonline_list(self, refs: list[str] | None = None) -> List[str]:
        return list_of_dict_to_jsonline_list(
            [label.dump() for ref, label in self.data.items() if (refs is None) or (ref in refs)]
        )

    def dumps_data_jsonlines(self, refs: list[str] | None = None) -> str:
        return list_of_dict_to_jsonlines(
            [label.dump() for ref, label in self.data.items() if (refs is None) or (ref in refs)]
        )

    def import_dumps_data(
        self, dumps_data: str, fill_categories=True, force_overwrite=False
    ) -> Dict[str, Label]:
        labels = [Label.from_dump(label_dict) for label_dict in jsonlines_to_list_of_dict(dumps_data)]
        return self.import_labels(
            labels=labels, fill_categories=fill_categories, force_overwrite=force_overwrite
        )

    def rename_category(self, old_category: str, new_category: str) -> List[str]:
        affected_keys: List[str] = []
        for key, item in list(self.data.items()):
            if (item.category and item.category == old_category) or (
                not item.category and old_category == self.default_category
            ):
                item.category = new_category
                item.set_timestamp(datetime.now().timestamp())
                affected_keys.append(key)

        if old_category in self.categories:
            idx = self.categories.index(old_category)
            self.categories.pop(idx)
            if new_category not in self.categories:
                self.categories.insert(idx, new_category)
        return affected_keys

    def delete_category(self, category: str) -> List[str]:
        affected_keys = []
        for key, item in list(self.data.items()):
            if item.category and item.category == category:
                affected_keys.append(key)
                item.category = self.get_default_category()
                item.set_timestamp(datetime.now().timestamp())

        if category in self.categories:
            idx = self.categories.index(category)
            self.categories.pop(idx)

        return affected_keys
