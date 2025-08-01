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
from typing import Any, Dict, List

from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init

MIN_RELAY_FEE = 1

logger = logging.getLogger(__name__)


class MempoolData(BaseSaveableClass):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    def __init__(
        self,
        mempool_blocks: List[Dict[str, Any]] | None = None,
        recommended: Dict[str, int] | None = None,
        mempool_dict: Dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.mempool_blocks = mempool_blocks if mempool_blocks else self._empty_mempool_blocks()
        self.recommended: Dict[str, int] = (
            recommended
            if recommended
            else {
                "fastestFee": MIN_RELAY_FEE,
                "halfHourFee": MIN_RELAY_FEE,
                "hourFee": MIN_RELAY_FEE,
                "economyFee": MIN_RELAY_FEE,
                "minimumFee": MIN_RELAY_FEE,
            }
        )
        self.mempool_dict: Dict[str, Any] = (
            mempool_dict
            if mempool_dict
            else {
                "count": 0,
                "vsize": 0,
                "total_fee": 0,
                "fee_histogram": [],
            }
        )

    def dump(self) -> Dict[str, Any]:
        d = super().dump()
        d["mempool_blocks"] = self.mempool_blocks
        d["recommended"] = self.recommended
        d["mempool_dict"] = self.mempool_dict
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None):
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def _empty_mempool_blocks(self) -> List[Dict[str, Any]]:
        return [
            {
                "blockSize": 1,
                "blockVSize": 1,
                "nTx": 0,
                "totalFees": MIN_RELAY_FEE,
                "medianFee": MIN_RELAY_FEE,
                "feeRange": [MIN_RELAY_FEE, MIN_RELAY_FEE],
            }
        ]
