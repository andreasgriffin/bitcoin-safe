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

import logging
import sys
from time import sleep

import bdkpython as bdk
from PyQt6.QtCore import QCoreApplication

from bitcoin_safe.network_config import Peers
from bitcoin_safe.network_utils import ProxyInfo

from .p2p_client import Peer
from .p2p_listener import P2pListener
from .tools import transaction_table

logging.basicConfig(level=logging.DEBUG)

app = QCoreApplication(sys.argv)
proxy_info = None

# initial_peer = Peer(host="127.0.0.1", port=18444)
# network = bdk.Network.REGTEST

# initial_peer = Peer(host="192.168.178.21", port=8333)
# network = bdk.Network.BITCOIN

# with proxy
initial_peer = Peer(host="ffty2pbxzcpvvscktdp6cnmhmyqo5wegmgy5tkjkj2nyh7ygmsd7tsid.onion", port=8333)
network = bdk.Network.BITCOIN
proxy_info = ProxyInfo.parse("socks5h://127.0.0.1:9050")


client = P2pListener(network=network, loop_in_thread=None, discovered_peers=Peers([initial_peer]))
# client.set_address_filter(None)


def on_tx(tx: bdk.Transaction):
    """On tx."""
    print(transaction_table(tx, network))


client.signal_tx.connect(on_tx)
client.start(proxy_info=proxy_info, preferred_peers=[initial_peer])


while input("type q") != "q":
    sleep(1)
