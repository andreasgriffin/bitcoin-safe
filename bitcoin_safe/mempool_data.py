#
# Bitcoin-Safe
# Copyright (C) 2025-2026 Andreas Griffin
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

from __future__ import annotations

import logging
from typing import Any

from bitcoin_safe_lib.storage import BaseSaveableClass, filtered_for_init

from bitcoin_safe.constants import MIN_RELAY_FEE

logger = logging.getLogger(__name__)

RECOMMENDED_FEE_KEYS = (
    "fastestFee",
    "halfHourFee",
    "hourFee",
    "economyFee",
    "minimumFee",
)


class MempoolData(BaseSaveableClass):
    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    def __init__(
        self,
        mempool_blocks: list[dict[str, Any]] | None = None,
        recommended: dict[str, float] | None = None,
        mempool_dict: dict[str, Any] | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.mempool_blocks = mempool_blocks if mempool_blocks else self._empty_mempool_blocks()
        # Persisted data may be malformed (e.g. a non-dict), so fall back to defaults unless all keys exist
        self.recommended: dict[str, float] = {key: MIN_RELAY_FEE for key in RECOMMENDED_FEE_KEYS}
        if isinstance(recommended, dict) and all(key in recommended for key in RECOMMENDED_FEE_KEYS):
            self.recommended = recommended
        self.mempool_dict: dict[str, Any] = (
            mempool_dict
            if mempool_dict
            else {
                "count": 0,
                "vsize": 0,
                "total_fee": 0,
                "fee_histogram": [],
            }
        )

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["mempool_blocks"] = self.mempool_blocks
        d["recommended"] = self.recommended
        d["mempool_dict"] = self.mempool_dict
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    def _empty_mempool_blocks(self) -> list[dict[str, Any]]:
        """Empty mempool blocks."""
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
