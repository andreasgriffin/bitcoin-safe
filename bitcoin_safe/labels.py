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

import copy
import enum
import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType

from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason
from bitcoin_safe.util import (
    jsonlines_to_list_of_dict,
    list_of_dict_to_jsonline_list,
    list_of_dict_to_jsonlines,
)
from bitcoin_safe.wallet_util import get_default_categories

from .storage import BaseSaveableClass, SaveAllClass, filtered_for_init
from .util import fast_version

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
        timestamp: Literal["now", "old"] | float,
        label: str | None = None,
        origin: str | None = None,
        spendable: bool | None = None,
        category: str | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.type = type
        self.ref = ref
        self.label = label
        self.origin = origin
        self.spendable = spendable
        self.category = category
        self.timestamp = self._to_timestamp(timestamp)

    @staticmethod
    def _to_timestamp(timestamp: Literal["now", "old"] | float) -> float:
        """To timestamp."""
        if timestamp == "now":
            return datetime.now().timestamp()
        elif timestamp == "old":
            return AUTOMATIC_TIMESTAMP
        else:
            return timestamp

    def set_timestamp(self, timestamp: Literal["now", "old"] | float):
        """Set timestamp."""
        new_timestamp = self._to_timestamp(timestamp=timestamp)
        if new_timestamp > self.timestamp:
            self.timestamp = new_timestamp

    def to_bip329(self) -> dict[str, Any]:
        """To bip329."""
        d: dict[str, Any] = {}

        d["type"] = self.type.name
        d["ref"] = self.ref
        d["label"] = (
            f"{self.label if self.label else ''}{self.separator}{self.category}"
            if self.category
            else self.label
        )

        if self.origin is not None:
            d["origin"] = self.origin
        if self.spendable is not None:
            d["spendable"] = self.spendable
        return d

    @classmethod
    def from_bip329(cls, d: dict[str, Any], timestamp: Literal["now", "old"] | float = "now") -> Label:
        """Can import bip329, Also uses additional fields (like timestamp) if
        available."""
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

    def dump(self, preserve_bip329_keys=True) -> dict:
        """Dump."""
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
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)

        dct["type"] = LabelType[dct["type"]]

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            pass

        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.1"):
            if "flat_data" in dct:
                #
                dct["timestamp"] = dct["timestamp"] if dct["timestamp"] else datetime.now().timestamp()

        return super().from_dump_migration(dct=dct)

    def __eq__(self, other: object) -> bool:
        """Eq."""
        if not isinstance(other, Label):
            return False
        return self.dump() == other.dump()


class LabelSnapshotReason(enum.Enum):
    AUTOMATIC = "automatic"
    RESTORE = "restore"


@dataclass
class LabelSnapshot(SaveAllClass):
    VERSION = "0.0.0"
    known_classes = {**BaseSaveableClass.known_classes, LabelSnapshotReason.__name__: LabelSnapshotReason}

    created_at: datetime
    state: str
    reason: LabelSnapshotReason = LabelSnapshotReason.AUTOMATIC
    count: int = 0
    count_address_labels: int = 0

    def dump(self):
        """Dump."""
        d = super().dump()
        d["created_at"] = self.created_at.timestamp()
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        dct["created_at"] = datetime.fromtimestamp(dct["created_at"])
        return cls(**filtered_for_init(dct, cls))


class ChangedItems(dict[str, Label]):
    def to_update_filter(self, reason: UpdateFilterReason) -> UpdateFilter:
        """To update filter."""
        addresses = []
        txids = []
        for label in self.values():
            if label.type == LabelType.addr:
                addresses.append(label.ref)
            elif label.type == LabelType.tx:
                txids.append(label.ref)
        return UpdateFilter(addresses=addresses, txids=txids, reason=reason)


class Labels(BaseSaveableClass):
    VERSION = "0.1.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        Label.__name__: Label,
        LabelSnapshot.__name__: LabelSnapshot,
    }

    _snapshot_limit = 20

    def __init__(
        self,
        data: dict[str, Label] | None = None,
        categories: list[str] | None = None,
        default_category: str | None = None,
        _snapshots: list[LabelSnapshot] | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__()

        # "tb1q6xhxcrzmjwf6ce5jlj08gyrmu4eq3zwpv0ss3f":{ "type": "addr",
        # "ref": "tb1q6xhxcrzmjwf6ce5jlj08gyrmu4eq3zwpv0ss3f", "label": "Address" }
        self.data: dict[str, Label] = data if data else {}
        self.categories: list[str] = categories if categories else []
        self.default_category = default_category or get_default_categories()[0]
        self._snapshots: list[LabelSnapshot] = _snapshots if _snapshots else []

    def count_address_labels(self):
        """Count address labels."""
        return sum(1 for label in self.data.values() if label.label)

    def _store_snapshot(self, reason: LabelSnapshotReason | None = None) -> bool:
        """Store snapshot."""
        snapshot = LabelSnapshot(
            created_at=datetime.now(),
            state=self.dumps_data_jsonlines(),
            count_address_labels=self.count_address_labels(),
            reason=reason or LabelSnapshotReason.AUTOMATIC,
            count=len(self.data),
        )
        if self._snapshots and self._snapshots[-1].state == snapshot.state:
            return False
        self._snapshots.append(snapshot)
        while len(self._snapshots) > self._snapshot_limit:
            self._snapshots.pop(0)
        return True

    def get_snapshots(self) -> list[LabelSnapshot]:
        """Get snapshots."""
        return list(self._snapshots)

    def restore_snapshot(self, snapshot: LabelSnapshot) -> ChangedItems:
        """Restore snapshot."""
        self._store_snapshot(reason=LabelSnapshotReason.RESTORE)
        return self.import_dumps_data(
            snapshot.state,
            force_overwrite=True,
        )

    def add_category(self, value: str) -> None:
        """Add category."""
        if value in self.categories:
            return
        self._store_snapshot()
        self.categories.append(value)

    def del_item(self, ref: str) -> None:
        """Del item."""
        if ref not in self.data:
            return
        self._store_snapshot()
        del self.data[ref]

    def get_label(self, ref: str, default_value: str | None = None) -> str | None:
        """Get label."""
        item = self.data.get(ref)
        if not item:
            return default_value
        return item.label

    def get_category_raw(self, ref: str) -> str | None:
        """Get category raw."""
        item = self.data.get(ref)
        if not item or item.category is None:
            return None

        return item.category

    def get_category(self, ref: str, default_value=None) -> str:
        """Get category."""
        item = self.data.get(ref)
        if not item or item.category is None:
            return default_value if default_value else self.get_default_category()

        return item.category

    def get_timestamp(self, ref: str, default_value=None) -> float | None:
        """Get timestamp."""
        item = self.data.get(ref)
        if not item or not item.timestamp:
            return default_value

        return item.timestamp

    def set_label(
        self, type: LabelType, ref: str, label_value, timestamp: Literal["now", "old"] | float = "now"
    ) -> None:
        """Set label."""
        self._store_snapshot()
        label = self.data.get(ref)

        if not label:
            self.data[ref] = label = Label(type, ref, timestamp)

        label.label = label_value
        label.set_timestamp(timestamp)

        if all(value is None for value in [label.category, label.spendable, label.label, label.origin]):
            del self.data[ref]

    def set_category(
        self, type: LabelType, ref: str, category, timestamp: Literal["now", "old"] | float = "now"
    ) -> None:
        """Set category."""
        self._store_snapshot()
        label = self.data.get(ref)
        if not label:
            self.data[ref] = label = Label(type, ref, timestamp)

        label.category = category
        label.set_timestamp(timestamp)

        if all(value is None for value in [label.category, label.spendable, label.label, label.origin]):
            del self.data[ref]

        if category and category not in self.categories:
            self.categories.append(category)

    def set_tx_label(self, label_value, value, timestamp: Literal["now", "old"] | float = "now") -> None:
        """Set tx label."""
        return self.set_label(LabelType.tx, label_value, value, timestamp=timestamp)

    def set_addr_label(self, ref: str, label_value, timestamp: Literal["now", "old"] | float = "now") -> None:
        """Set addr label."""
        return self.set_label(LabelType.addr, ref, label_value, timestamp=timestamp)

    def set_pubkey_label(
        self, ref: str, label_value, timestamp: Literal["now", "old"] | float = "now"
    ) -> None:
        """Set pubkey label."""
        return self.set_label(LabelType.pubkey, ref, label_value, timestamp=timestamp)

    def set_input_label(
        self, ref: str, label_value, timestamp: Literal["now", "old"] | float = "now"
    ) -> None:
        """Set input label."""
        return self.set_label(LabelType.input, ref, label_value, timestamp=timestamp)

    def set_output_label(
        self, ref: str, label_value, timestamp: Literal["now", "old"] | float = "now"
    ) -> None:
        """Set output label."""
        return self.set_label(LabelType.output, ref, label_value, timestamp=timestamp)

    def set_xpub_label(self, ref: str, label_value, timestamp: Literal["now", "old"] | float = "now") -> None:
        """Set xpub label."""
        return self.set_label(LabelType.xpub, ref, label_value, timestamp=timestamp)

    def set_addr_category(self, ref: str, category, timestamp: Literal["now", "old"] | float = "now") -> None:
        """Set addr category."""
        return self.set_category(LabelType.addr, ref, category, timestamp=timestamp)

    def set_tx_category(self, ref: str, category, timestamp: Literal["now", "old"] | float = "now") -> None:
        """Set tx category."""
        return self.set_category(LabelType.tx, ref, category, timestamp=timestamp)

    def get_default_category(self) -> str:
        """Get default category."""
        return self.categories[0] if self.categories else self.default_category

    def get_category_dict_raw(self, filter_type: LabelType | None) -> dict[str | None, list[Label]]:
        """Get category dict raw."""
        d: dict[str | None, list[Label]] = defaultdict(list)
        for label in self.data.values():
            if filter_type and label.type != filter_type:
                continue
            d[label.category].append(label)
        return d

    def dump(self) -> dict:
        """Dump."""
        d = super().dump()

        d["data"] = self.data
        d["default_category"] = self.default_category
        d["_snapshots"] = self._snapshots

        keys = ["categories"]
        for k in keys:
            d[k] = copy.deepcopy(self.__dict__[k])
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> Labels:
        """From dump."""
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
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            if "data" in dct:
                #
                dct["flat_data"] = list(dct["data"].values())
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.1"):
            if "flat_data" in dct:
                #
                del dct["flat_data"]
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.4"):
            if "data" in dct:
                #
                dct["data"] = {
                    k: Label(**v, timestamp=datetime.now().timestamp()) for k, v in dct["data"].items()
                }
        return super().from_dump_migration(dct=dct)

    def export_bip329_jsonlines(self) -> str:
        """Export bip329 jsonlines."""
        list_of_dict = [item.to_bip329() for item in self.data.values()]
        return list_of_dict_to_jsonlines(list_of_dict)

    def import_bip329_jsonlines(
        self, jsonlines: str, fill_categories=True, timestamp: Literal["now", "old"] | float = "now"
    ) -> dict[str, Label]:
        """Import bip329 jsonlines."""
        list_of_dict = jsonlines_to_list_of_dict(jsonlines)
        labels = [Label.from_bip329(d, timestamp=timestamp) for d in list_of_dict]
        return self.import_labels(labels=labels, fill_categories=fill_categories)

    def import_electrum_wallet_json(
        self,
        file_content: str,
        network: bdk.Network,
        fill_categories=True,
        timestamp: Literal["now", "old"] | float = "now",
    ) -> dict[str, Label]:
        """Import electrum wallet json."""
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

    def _should_overwrite(self, new_label: Label, old_label: Label | None, tiebreaker: bool | None) -> bool:
        """Should overwrite."""
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
    ) -> tuple[float | None, float | None]:
        """Get timestamp range."""
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

    def _should_overwrite_mine_when_tie(self, new_labels: list[Label]) -> None | bool:
        """Should overwrite mine when tie."""
        my_earliest_timestamp, _ = self.get_timestamp_range(self.data.values())
        other_earliest_timestamp, _ = self.get_timestamp_range(new_labels)

        if not other_earliest_timestamp:
            return False
        if not my_earliest_timestamp:
            return True

        # prefer the labels with the oldest (non_automatic) entries
        return False if my_earliest_timestamp < other_earliest_timestamp else True

    def import_labels(self, labels: list[Label], fill_categories=True, force_overwrite=False) -> ChangedItems:
        """Import labels."""
        self._store_snapshot()
        changed_data = ChangedItems()

        tiebreaker = self._should_overwrite_mine_when_tie(new_labels=labels)

        for label in labels:
            old_label = self.data.get(label.ref)

            if self.data.get(label.ref) != label and (
                force_overwrite
                or self._should_overwrite(new_label=label, old_label=old_label, tiebreaker=tiebreaker)
            ):
                if force_overwrite:
                    # setting timestamp as now ensures
                    # that it doesnt get reset by an old state (for example from the LabelSyncer)
                    label.timestamp = datetime.now().timestamp()
                self.data[label.ref] = label
                changed_data[label.ref] = label

        if fill_categories:
            for item in self.data.values():
                if item.category is None:
                    continue
                if item.category not in self.categories:
                    self.categories.append(item.category)
        return changed_data

    def dumps_data_jsonline_list(self, refs: list[str] | None = None) -> list[str]:
        """Dumps data jsonline list."""
        return list_of_dict_to_jsonline_list(
            [label.dump() for ref, label in self.data.items() if (refs is None) or (ref in refs)]
        )

    def dumps_data_jsonlines(self, refs: list[str] | None = None) -> str:
        """Dumps data jsonlines."""
        return list_of_dict_to_jsonlines(
            [label.dump() for ref, label in self.data.items() if (refs is None) or (ref in refs)]
        )

    def import_dumps_data(self, dumps_data: str, fill_categories=True, force_overwrite=False) -> ChangedItems:
        """Import dumps data."""
        labels = [Label.from_dump(label_dict) for label_dict in jsonlines_to_list_of_dict(dumps_data)]
        return self.import_labels(
            labels=labels, fill_categories=fill_categories, force_overwrite=force_overwrite
        )

    def rename_category(self, old_category: str, new_category: str) -> list[str]:
        """Rename category."""
        if old_category == new_category:
            return []
        self._store_snapshot()
        affected_keys: list[str] = []
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

    def delete_category(self, category: str) -> list[str]:
        """Delete category."""
        self._store_snapshot()
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
