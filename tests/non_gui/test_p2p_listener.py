#
# Bitcoin Safe
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

import bdkpython as bdk

from bitcoin_safe.network_config import ConnectionInfo, Peer
from bitcoin_safe.p2p.p2p_listener import P2pListener


def test_p2p_listener_shared_state_accessors_return_snapshots() -> None:
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    peer = Peer(host="127.0.0.1", port=18444)
    connection = ConnectionInfo(peer=peer, proxy_info=None)
    try:
        listener.add_peers([peer])
        with listener._state_lock:
            listener._current_peers[0] = connection

        discovered_snapshot = listener.discovered_peers
        active_snapshot = listener.active_connections

        discovered_snapshot.clear()
        active_snapshot.clear()

        assert listener.discovered_peers == [peer]
        assert listener.active_connections == [connection]
    finally:
        listener.stop()
