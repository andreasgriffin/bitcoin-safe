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

import logging
from concurrent.futures import Future
from typing import cast

from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from btcpay_tools.btcpay_subscription_nostr.pos_item_lookup import (
    BtcpayPosItemData,
    BtcpayPosItemLookup,
)
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.plugin_framework.subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)


class _SubscriptionPriceLookupState:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class SubscriptionPriceLookup(QObject):
    signal_prices_changed = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.signal_tracker = SignalTracker()
        self._state = _SubscriptionPriceLookupState()
        self._items_by_pos_url: dict[str, dict[str, BtcpayPosItemData]] = {}
        self._loading_pos_urls: set[str] = set()
        self._fetch_tasks_by_pos_url: dict[str, Future[dict[str, BtcpayPosItemData]]] = {}
        self.signal_tracker.connect(cast(SignalProtocol[[]], self.destroyed), self._state.close)

    @property
    def _closed(self) -> bool:
        return self._state.closed

    def ensure_prices(self, subscription_manager: SubscriptionManager) -> None:
        if self._closed:
            return

        subscription_product = subscription_manager.subscription_product
        pos_url = subscription_manager.subscription_pos_base_url
        if subscription_product is None or not pos_url:
            return
        if pos_url in self._items_by_pos_url or pos_url in self._loading_pos_urls:
            return

        proxy_dict = subscription_manager.proxy_dict()
        self._loading_pos_urls.add(pos_url)
        if subscription_manager.loop_in_thread is None:
            try:
                self._set_items(pos_url, self._fetch_btcpay_pos_items(pos_url, proxy_dict))
            except Exception as exc:
                self._handle_fetch_error(pos_url, exc)
            return

        future: Future[dict[str, BtcpayPosItemData]] | None = None

        def on_success(items: dict[str, BtcpayPosItemData] | None) -> None:
            self._on_fetch_success(pos_url, items, future)

        def on_error(error_info: ExcInfo | Exception | None) -> None:
            self._handle_fetch_error(pos_url, error_info, future)

        future = subscription_manager.loop_in_thread.run_task(
            self._fetch_btcpay_pos_items_async(pos_url, proxy_dict),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"subscription_prices:{pos_url}",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )
        if future is not None:
            self._fetch_tasks_by_pos_url[pos_url] = future

    def raw_price_text_for_manager(self, subscription_manager: SubscriptionManager) -> str | None:
        if self._closed:
            return None

        subscription_product = subscription_manager.subscription_product
        pos_url = subscription_manager.subscription_pos_base_url
        if subscription_product is None or not pos_url:
            return None

        item = self._items_by_pos_url.get(pos_url, {}).get(subscription_product.pos_id)
        if item is None or not item.price_text:
            return None

        price_text = item.price_text.strip()
        return price_text or None

    def close(self) -> bool:
        if self._closed:
            return True

        self._state.close()
        for future in self._fetch_tasks_by_pos_url.values():
            if not future.done():
                future.cancel()
        self._fetch_tasks_by_pos_url.clear()
        self.signal_tracker.disconnect_all()
        self._loading_pos_urls.clear()
        return True

    async def _fetch_btcpay_pos_items_async(
        self,
        pos_url: str,
        proxy_dict: dict[str, str] | None,
    ) -> dict[str, BtcpayPosItemData]:
        return self._fetch_btcpay_pos_items(pos_url, proxy_dict)

    def _fetch_btcpay_pos_items(
        self,
        pos_url: str,
        proxy_dict: dict[str, str] | None,
    ) -> dict[str, BtcpayPosItemData]:
        return BtcpayPosItemLookup(proxy_dict=proxy_dict).fetch(
            pos_url=pos_url,
            proxy_dict=proxy_dict,
        )

    def _on_fetch_success(
        self,
        pos_url: str,
        items: dict[str, BtcpayPosItemData] | None,
        future: Future[dict[str, BtcpayPosItemData]] | None = None,
    ) -> None:
        if self._closed:
            return

        self._clear_fetch_task(pos_url, future)
        self._set_items(pos_url, items or {})

    def _set_items(self, pos_url: str, items: dict[str, BtcpayPosItemData]) -> None:
        if self._closed:
            return

        self._loading_pos_urls.discard(pos_url)
        self._items_by_pos_url[pos_url] = items
        self.signal_prices_changed.emit(pos_url)

    def _handle_fetch_error(
        self,
        pos_url: str,
        error_info: ExcInfo | Exception | None,
        future: Future[dict[str, BtcpayPosItemData]] | None = None,
    ) -> None:
        if self._closed:
            return

        self._clear_fetch_task(pos_url, future)
        logger.debug("BTCPay POS item lookup failed: %s", error_info)
        self._loading_pos_urls.discard(pos_url)
        self._items_by_pos_url[pos_url] = {}
        self.signal_prices_changed.emit(pos_url)

    def _clear_fetch_task(
        self,
        pos_url: str,
        future: Future[dict[str, BtcpayPosItemData]] | None,
    ) -> None:
        current_future = self._fetch_tasks_by_pos_url.get(pos_url)
        if future is None or current_future is future:
            self._fetch_tasks_by_pos_url.pop(pos_url, None)
