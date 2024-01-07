import logging

logger = logging.getLogger(__name__)


import copy
import json
from typing import (
    Dict,
    List,
)


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


class Type(enum.Enum):
    tx = enum.auto()
    addr = enum.auto()
    pubkey = enum.auto()
    input = enum.auto()
    output = enum.auto()
    xpub = enum.auto()


class Labels(BaseSaveableClass):
    def __init__(self, data=None, categories=None) -> None:
        super().__init__()

        # "bc1q34aq5drpuwy3wgl9lhup9892qp6svr8ldzyy7c":{ "type": "addr", "ref": "bc1q34aq5drpuwy3wgl9lhup9892qp6svr8ldzyy7c", "label": "Address" }
        self.data: Dict[str, Dict] = data if data else {}
        self.categories: List[str] = categories if categories else []

        self.separator = ";;"

    def add_category(self, value):
        if value not in self.categories:
            self.categories.append(value)

    def del_item(self, ref):
        if ref in self.data:
            del self.data[ref]

    def get_label(self, ref, default_value=None):
        item = self.data.get(ref, {})
        return item.get(Key.label.name, default_value)

    def get_category(self, ref, default_value=None):
        item = self.data.get(ref, {})
        return item.get(
            Key.category.name,
            default_value if default_value else self.get_default_category(),
        )

    def set_label(self, type: Type, ref, value):
        item = self.data.setdefault(ref, {})
        item[Key.ref.name] = ref
        item[Key.label.name] = value
        item[Key.type.name] = type.name

        if value is None:
            del item[Key.label.name]

    def set_category(self, type: Type, ref, value):
        item = self.data.setdefault(ref, {})
        item[Key.ref.name] = ref
        item[Key.category.name] = value
        item[Key.type.name] = type.name

        if value is None:
            del item[Key.category.name]
            return

        if value and value not in self.categories:
            self.categories.append(value)

    def set_tx_label(self, ref, value):
        return self.set_label(Type.tx, ref, value)

    def set_addr_label(self, ref, value):
        return self.set_label(Type.addr, ref, value)

    def set_pubkey_label(self, ref, value):
        return self.set_label(Type.pubkey, ref, value)

    def set_input_label(self, ref, value):
        return self.set_label(Type.input, ref, value)

    def set_output_label(self, ref, value):
        return self.set_label(Type.output, ref, value)

    def set_xpub_label(self, ref, value):
        return self.set_label(Type.xpub, ref, value)

    def set_addr_category(self, ref, value):
        return self.set_category(Type.addr, ref, value)

    def set_tx_category(self, ref, value):
        return self.set_category(Type.tx, ref, value)

    def get_default_category(self):
        return self.categories[0] if self.categories else None

    def set_addr_category_default(self, ref):
        if not self.categories:
            return
        return self.set_category(Type.addr, ref, self.get_default_category())

    def serialize(self):
        d = super().serialize()

        keys = ["data", "categories"]
        for k in keys:
            d[k] = copy.deepcopy(self.__dict__[k])
        return d

    @classmethod
    def deserialize(cls, dct, class_kwargs=None):
        super().deserialize(dct, class_kwargs=class_kwargs)

        return Labels(**dct)

    def _convert_item_to_bip329(self, item):
        new_item = item.copy()
        if Key.category.name in new_item:
            new_item[
                Key.label.name
            ] = f'{new_item.get(Key.category.name,"")}{self.separator}{new_item.get(Key.label.name,"")}'
        return new_item

    def _bip329_to_item(self, item):
        new_item = item.copy()
        if self.separator in new_item[Key.label.name]:
            new_item[Key.category.name], new_item[Key.label.name] = new_item[Key.label.name].split(
                self.separator, 1
            )
        return new_item

    def get_bip329_json_str(self):
        result = [json.dumps(self._convert_item_to_bip329(item)) for item in self.data.values()]
        return "\n".join(result)

    def parse_from_bip329_json_str(self, lines):
        values = [self._bip329_to_item(json.loads(line)) for line in lines]
        return {value[Key.ref.name]: value for value in values}

    def set_data_from_bip329_json_str(self, lines, fill_categories=True):
        self.data = self.parse_from_bip329_json_str(lines)
        if fill_categories:
            for item in self.data.values():
                if Key.category.name not in item:
                    continue
                category = item[Key.category.name]
                if category not in self.categories:
                    self.categories.append(category)
        return self.data

    def rename_category(self, old_category, new_category):
        affected_keys = []
        for key, item in list(self.data.items()):
            if item.get(Key.category.name) and item.get(Key.category.name) == old_category:
                item[Key.category.name] = new_category
                affected_keys.append(key)

        if old_category in self.categories:
            idx = self.categories.index(old_category)
            self.categories.pop(idx)
            self.categories.insert(idx, new_category)
        return affected_keys

    def delete_category(self, category) -> List[str]:
        affected_keys = []
        for key, item in list(self.data.items()):
            if item.get(Key.category.name) and item.get(Key.category.name) == category:
                affected_keys.append(key)
                del item[Key.category.name]

        if category in self.categories:
            idx = self.categories.index(category)
            self.categories.pop(idx)

        return affected_keys
