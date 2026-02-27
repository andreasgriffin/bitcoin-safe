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

from bitcoin_safe.labels import Labels
from bitcoin_safe.plugin_framework.plugins.chat_sync.label_syncer import DataType, LabelSyncer
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason


class DummyAuthor:
    def to_bech32(self) -> str:
        return "npub1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"


class DummyData:
    def __init__(self, data: str, data_type: DataType) -> None:
        self.data = data
        self.data_type = data_type


class DummyUpdatedSignal:
    def __init__(self) -> None:
        self.emitted: list[UpdateFilter] = []

    def emit(self, update_filter: UpdateFilter) -> None:
        self.emitted.append(update_filter)


class DummyWalletSignals:
    def __init__(self) -> None:
        self.updated = DummyUpdatedSignal()


class DummyNostrSync:
    @staticmethod
    def is_me(author: DummyAuthor) -> bool:
        return False


def make_syncer(labels: Labels, wallet_signals: DummyWalletSignals) -> LabelSyncer:
    syncer = LabelSyncer.__new__(LabelSyncer)
    syncer.labels = labels
    syncer.enabled = True
    syncer.nostr_sync = DummyNostrSync()
    syncer.wallet_signals = wallet_signals
    syncer.apply_own_labels = True
    return syncer


def test_on_nostr_label_bip329_received_accepts_raw_bip329_jsonline() -> None:
    labels = Labels()
    wallet_signals = DummyWalletSignals()
    syncer = make_syncer(labels=labels, wallet_signals=wallet_signals)

    address = "some_address"
    category = "from_nostr_category"
    data = DummyData(
        data='{"type":"addr","ref":"some_address","label":"from nostr","category":"from_nostr_category"}',
        data_type=DataType.LabelsBip329,
    )

    syncer.on_nostr_label_bip329_received(data, DummyAuthor())

    assert labels.get_label(address) == "from nostr"
    assert labels.get_category(address) == category
    assert len(wallet_signals.updated.emitted) == 1

    update_filter = wallet_signals.updated.emitted[0]
    assert update_filter.reason == UpdateFilterReason.SourceLabelSyncer
    assert update_filter.addresses == {address}
