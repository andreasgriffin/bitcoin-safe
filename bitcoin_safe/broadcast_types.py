#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

import bdkpython as bdk

if TYPE_CHECKING:
    from bitcoin_safe.client import Client


class BroadcastOutcome(Enum):
    success = "success"
    failure = "failure"
    no_routes = "no_routes"


@dataclass(frozen=True)
class BroadcastRequest:
    request_id: str
    tx: bdk.Transaction

    @classmethod
    def create(cls, tx: bdk.Transaction) -> BroadcastRequest:
        """Create a uniquely identifiable broadcast request."""
        return cls(request_id=str(uuid4()), tx=tx)

    @property
    def txid(self) -> str:
        """Return the transaction identifier."""
        return str(self.tx.compute_txid())


@dataclass(frozen=True)
class WalletBroadcastRoute:
    client: Client
    wallet_ids: tuple[str, ...]


@dataclass(frozen=True)
class BroadcastAttempt:
    route_type: str
    success: bool
    backend: str | None = None
    wallet_ids: tuple[str, ...] = ()
    peer: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class BroadcastCompletion:
    txid: str
    request_ids: tuple[str, ...]
    outcome: BroadcastOutcome
    successful_route: BroadcastAttempt | None
    attempts: tuple[BroadcastAttempt, ...]
    wallet_timeout: bool = False
