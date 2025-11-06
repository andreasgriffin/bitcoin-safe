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

import datetime
import logging
import threading
from collections.abc import Hashable
from threading import Lock

logger = logging.getLogger(__name__)


class PasswordCache:
    """A thread-safe cache for storing passwords with automatic expiration."""

    def __init__(self, retain_password: datetime.timedelta = datetime.timedelta(minutes=5)) -> None:
        """Initialize the PasswordCache.

        Args:
            retain_password: Duration (in minutes) to retain each password,
                or a datetime.timedelta for custom durations. Defaults to 5 minutes.
        """
        self._retain = retain_password

        # Internal store and timer registry
        self._store: dict[Hashable, tuple[str, datetime.datetime]] = {}
        self._timers: dict[Hashable, threading.Timer] = {}
        self._lock = Lock()

    def set_password(self, key: Hashable, password: str) -> None:
        """Store a password in the cache and schedule its automatic deletion.

        Args:
            key: Identifier for the password.
            password: The password to store.
        """
        expires_at = datetime.datetime.now() + self._retain
        with self._lock:
            # Cancel existing timer if present
            existing_timer = self._timers.get(key)
            if existing_timer:
                existing_timer.cancel()

            # Store password and expiration
            self._store[key] = (password, expires_at)

            # Schedule deletion after retention period
            timer = threading.Timer(self._retain.total_seconds(), self._expire_key, args=(key,))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def get_password(self, key: Hashable) -> str | None:
        """Retrieve a password from the cache if it has not expired.

        Args:
            key: Identifier for the password.

        Returns:
            The password if present and not yet expired; otherwise None.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None

            password, expires_at = entry
            if datetime.datetime.now() >= expires_at:
                # Expired (timer may not have fired yet)
                return None

            return password

    def _expire_key(self, key: Hashable) -> None:
        """Internal callback to remove a password from the cache once expired."""
        with self._lock:
            # Remove stored entry and its timer
            self._store.pop(key, None)
            self._timers.pop(key, None)
            # No need to cancel here; timer just fired
