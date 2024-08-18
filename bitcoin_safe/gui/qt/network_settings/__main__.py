import logging

import bdkpython as bdk
import numpy as np
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.network_config import NetworkConfigs

from .main import NetworkSettingsUI

logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    import os
    import sys

    from PyQt6.QtWidgets import QApplication, QMainWindow

    class DemoApp(QMainWindow):
        def __init__(self):
            super().__init__()

            if os.path.exists("network_configs.json"):
                with open("network_configs.json", "r") as file:
                    network_configs = NetworkConfigs.from_file("network_configs.json")
            else:
                network_configs = NetworkConfigs()

            self.network_settings_ui = NetworkSettingsUI(
                network=np.random.choice(np.array(list(bdk.Network)), size=1)[0],
                network_configs=network_configs,
                signals=None,
            )

            self.setCentralWidget(self.network_settings_ui)
            self.setWindowTitle("Demo App")

            self.network_settings_ui.signal_apply_and_restart.connect(self.save_and_close)
            self.network_settings_ui.signal_cancel.connect(self.close)

        def save_and_close(self):
            self.network_settings_ui.network_configs.save("network_configs.json")
            self.close()

    app = QApplication(sys.argv)
    demoApp = DemoApp()
    demoApp.show()
    sys.exit(app.exec())
