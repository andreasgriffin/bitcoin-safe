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


import logging
from typing import Dict

from bitcoin_safe.signals import SignalsMin

logger = logging.getLogger(__name__)


from PyQt6.QtCore import QObject, pyqtSignal

from .mempool import threaded_fetch


class FX(QObject):
    signal_data_updated = pyqtSignal()

    def __init__(self, signals_min: SignalsMin) -> None:
        super().__init__()
        self.signals_min = signals_min

        self.rates: Dict[str, Dict] = {}
        self.update()
        logger.debug(f"initialized {self}")

    def update(self) -> None:
        def on_success(data) -> None:
            if not data:
                logger.debug(f"empty result of https://api.coingecko.com/api/v3/exchange_rates")
                return
            self.rates = data.get("rates", {})
            self.signal_data_updated.emit()

        threaded_fetch(
            "https://api.coingecko.com/api/v3/exchange_rates", on_success, self, signals_min=self.signals_min
        )
