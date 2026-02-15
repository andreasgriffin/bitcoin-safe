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

LOCKTIME_THRESHOLD = 500_000_000
MEDIAN_TIME_PAST_LAG_MINUTES = 60
MAX_NLOCKTIME = 0xFFFFFFFF


def estimate_locktime_datetime(
    nlocktime: int,
    current_height: int,
    now: datetime | None = None,
    median_time_past_lag_minutes: int = MEDIAN_TIME_PAST_LAG_MINUTES,
) -> datetime:
    """Estimate the datetime for a given nlocktime.

    - For timestamp locktimes (>= LOCKTIME_THRESHOLD), returns the UTC datetime.
    - For block-height locktimes, estimates using 10 minutes per block.
    """
    now = now or datetime.now(timezone.utc)
    if nlocktime == 0:
        return now
    if nlocktime >= LOCKTIME_THRESHOLD:
        return datetime.fromtimestamp(nlocktime, tz=timezone.utc) + timedelta(
            minutes=median_time_past_lag_minutes
        )
    # see: https://en.bitcoin.it/wiki/NLockTime
    block_delta = nlocktime - current_height
    if block_delta <= 0:
        return now
    max_datetime = datetime.max.replace(tzinfo=timezone.utc)
    max_minutes = int((max_datetime - now).total_seconds() // 60)
    estimated_minutes = 10 * block_delta
    if estimated_minutes >= max_minutes:
        return max_datetime
    return now + timedelta(minutes=estimated_minutes)


def is_nlocktime_already_valid(
    nlocktime: int,
    current_height: int,
    now: datetime | None = None,
    median_time_past_lag_minutes: int = MEDIAN_TIME_PAST_LAG_MINUTES,
) -> bool:
    """Return whether a locktime is already valid."""
    estimated_datetime = estimate_locktime_datetime(
        nlocktime, current_height, now=now, median_time_past_lag_minutes=median_time_past_lag_minutes
    )
    now = now or datetime.now(timezone.utc)
    return estimated_datetime <= now
