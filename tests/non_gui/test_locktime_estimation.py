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

from datetime import datetime, timedelta, timezone

from bitcoin_safe.locktime_estimation import (
    LOCKTIME_THRESHOLD,
    estimate_locktime_datetime,
)


def test_estimate_locktime_datetime_zero_returns_now_without_height() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert estimate_locktime_datetime(0, current_height=0, now=now) == now


def test_estimate_locktime_datetime_past_timestamp_is_in_past() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    past_timestamp_locktime = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())

    estimated = estimate_locktime_datetime(past_timestamp_locktime, current_height=900_000, now=now)

    assert estimated is not None
    assert estimated.tzinfo == timezone.utc
    assert estimated < now


def test_estimate_locktime_datetime_future_timestamp_is_in_future() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    two_hours_ahead = int((now + timedelta(hours=2)).timestamp())

    estimated = estimate_locktime_datetime(two_hours_ahead, current_height=900_000, now=now)

    assert estimated is not None
    assert estimated.tzinfo == timezone.utc
    assert estimated > now


def test_estimate_locktime_datetime_timestamp_ignores_current_height() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    timestamp_locktime = LOCKTIME_THRESHOLD + 123_456

    estimated_without_height = estimate_locktime_datetime(timestamp_locktime, current_height=0, now=now)
    estimated_with_height = estimate_locktime_datetime(timestamp_locktime, current_height=950_000, now=now)

    assert estimated_without_height == estimated_with_height


def test_estimate_locktime_datetime_block_height_at_tip_returns_now() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    current_height = 840_000

    estimated = estimate_locktime_datetime(current_height, current_height=current_height, now=now)

    assert estimated == now


def test_estimate_locktime_datetime_block_height_in_past_returns_now() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    current_height = 840_000

    estimated = estimate_locktime_datetime(current_height - 10, current_height=current_height, now=now)

    assert estimated == now


def test_estimate_locktime_datetime_block_height_in_future_returns_future_time() -> None:
    now = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    current_height = 840_000

    estimated = estimate_locktime_datetime(current_height + 1, current_height=current_height, now=now)

    assert estimated is not None
    assert estimated > now
