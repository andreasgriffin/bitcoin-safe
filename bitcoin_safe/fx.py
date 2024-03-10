import logging
from typing import Dict

logger = logging.getLogger(__name__)


from PyQt6.QtCore import QObject, pyqtSignal

from .mempool import threaded_fetch


class FX(QObject):
    signal_data_updated = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()

        self.rates: Dict[str, Dict] = {}
        self.update()

    def update(self):
        def on_success(data):
            if not data:
                logger.debug(f"empty result of https://api.coingecko.com/api/v3/exchange_rates")
                return
            self.rates = data.get("rates", {})
            self.signal_data_updated.emit()

        threaded_fetch("https://api.coingecko.com/api/v3/exchange_rates", on_success, self)
