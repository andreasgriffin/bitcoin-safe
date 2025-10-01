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

from typing import Any, Dict

import bdkpython as bdk

from bitcoin_safe.persister.changeset_converter import ChangeSetConverter
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init


class SerializePersistence(bdk.Persistence, BaseSaveableClass):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    def __init__(self, change_set: bdk.ChangeSet | None = None):
        super().__init__()
        self.change_set = change_set if change_set else bdk.ChangeSet()

    #####
    # Persistence
    #####

    def initialize(self) -> bdk.ChangeSet:
        return self.change_set

    def persist(self, changeset: bdk.ChangeSet):
        self.change_set = bdk.ChangeSet.from_merge(self.change_set, changeset)

    def has_descriptor(self) -> bool:
        return bool(self.change_set.descriptor())

    #####
    # BaseSaveableClass
    #####

    def dump(self) -> Dict[str, Any]:
        d = super().dump()
        d["change_set"] = ChangeSetConverter.to_dict(self.change_set)
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None):
        super()._from_dump(dct, class_kwargs=class_kwargs)

        dct["change_set"] = (
            ChangeSetConverter.from_dict(change_set) if (change_set := dct.get("change_set")) else None
        )
        return cls(**filtered_for_init(dct, cls))
