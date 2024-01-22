import logging

from ...signals import Signals, UpdateFilter
from ...wallet import Wallet
from .qr_components.quick_receive import QuickReceive, ReceiveGroup
from .taglist.main import hash_color

logger = logging.getLogger(__name__)


class BitcoinQuickReceive(QuickReceive):
    def __init__(
        self,
        signals: Signals,
        wallet: Wallet,
        title="Quick Receive",
        limit_to_categories=None,
    ):
        super().__init__(title)
        self.signals = signals
        self.wallet = wallet
        self.limit_to_categories = limit_to_categories

        self.setFixedHeight(250)
        self.signals.category_updated.connect(self.update)

    def update(self):
        self.clear_boxes()
        old_tips = self.wallet.tips

        for category in self.wallet.labels.categories:
            if self.limit_to_categories and category not in self.limit_to_categories:
                continue

            address_info = self.wallet.get_unused_category_address(category)

            self.add_box(
                ReceiveGroup(
                    category,
                    hash_color(category).name(),
                    address_info.address.as_string(),
                    address_info.address.to_qr_uri(),
                )
            )

        if not self.wallet.labels.categories:
            address_info = self.wallet.get_unused_category_address(None)

            self.add_box(
                ReceiveGroup(
                    "Receive Address",
                    hash_color("None").name(),
                    address_info.address.as_string(),
                    address_info.address.to_qr_uri(),
                )
            )
        if old_tips != self.wallet.tips:
            self.signals.addresses_updated.emit(UpdateFilter(refresh_all=True))
