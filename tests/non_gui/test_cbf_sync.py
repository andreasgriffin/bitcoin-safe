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

import asyncio
from unittest.mock import Mock

from bitcoin_safe.cbf.cbf_sync import CbfSync


def test_need_connections_rebuilds_node_after_delay(monkeypatch) -> None:
    """A prolonged lack of connections rebuilds the CBF node once."""

    async def _run() -> None:
        cbf_sync = object.__new__(CbfSync)
        cbf_sync.wallet_id = "test-wallet"
        cbf_sync._need_connections_task = None
        cbf_sync.shutdown_node = Mock()
        cbf_sync.build_node = Mock()
        monkeypatch.setattr("bitcoin_safe.cbf.cbf_sync.NEED_CONNECTIONS_REBUILD_DELAY", 0)

        cbf_sync._handle_need_connections()
        first_task = cbf_sync._need_connections_task
        cbf_sync._handle_need_connections()

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert cbf_sync._need_connections_task is first_task
        cbf_sync.shutdown_node.assert_called_once_with()
        cbf_sync.build_node.assert_called_once_with()

    asyncio.run(_run())


def test_need_connections_rebuild_can_be_cancelled() -> None:
    """A recovered connection cancels the pending rebuild."""

    async def _run() -> None:
        cbf_sync = object.__new__(CbfSync)
        cbf_sync._need_connections_task = asyncio.create_task(asyncio.sleep(60))

        cbf_sync._cancel_need_connections_rebuild()

        assert cbf_sync._need_connections_task is None

    asyncio.run(_run())
