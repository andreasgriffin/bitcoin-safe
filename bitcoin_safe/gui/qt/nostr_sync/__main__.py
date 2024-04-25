import logging
from typing import Dict

from bitcoin_safe.signals import SignalsMin

logging.basicConfig(level=logging.DEBUG)


import hashlib
import json

import bdkpython as bdk
from nostr_sdk import Keys, SecretKey
from PyQt6.QtGui import QCloseEvent

from .nostr_sync import NostrSync

logger = logging.getLogger()  # Getting the root logger

if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication, QMainWindow

    def save_dict_to_file(dict_obj: Dict, file_path: str):
        """
        Serialize a dictionary and save it to a file in JSON format.

        Args:
        - dict_obj: The dictionary to be serialized.
        - file_path: The path of the file where the dictionary will be saved.
        """
        try:
            with open(file_path, "w") as json_file:
                json.dump(dict_obj, json_file)
        except IOError as e:
            print(f"Error saving dictionary to {file_path}: {e}")

    def load_dict_from_file(file_path: str):
        """
        Load and deserialize a JSON-formatted file into a dictionary.

        Args:
        - file_path: The path of the file to load the dictionary from.

        Returns:
        - The dictionary restored from the file. Returns None if an error occurs.
        """
        try:
            with open(file_path, "r") as json_file:
                return json.load(json_file)
        except IOError as e:
            print(f"Error loading dictionary from {file_path}: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {file_path}: {e}")
            return None

    class DemoApp(QMainWindow):
        def __init__(self, signals_min: SignalsMin):
            super().__init__()

            d = load_dict_from_file("my_dict.json")
            if d:
                self.nostr_sync = NostrSync.from_dump(d, network=bdk.Network.REGTEST, signals_min=signals_min)
            else:

                protcol_secret_str = "112343112231115111111111311311"
                keys = Keys(
                    sk=SecretKey.from_hex(hashlib.sha256(protcol_secret_str.encode("utf-8")).hexdigest())
                )

                self.nostr_sync = NostrSync.from_keys(
                    network=bdk.Network.REGTEST,
                    protocol_keys=keys,
                    device_keys=Keys.generate(),
                    signals_min=signals_min,
                )
            self.nostr_sync.subscribe()
            self.setCentralWidget(self.nostr_sync.gui)
            self.setWindowTitle("Demo App")

        def closeEvent(self, event: QCloseEvent) -> None:
            save_dict_to_file(self.nostr_sync.dump(), "my_dict.json")
            event.accept()  # Proceed to close the application

    if __name__ == "__main__":
        app = QApplication(sys.argv)
        demoApp = DemoApp(SignalsMin())
        demoApp.show()
        sys.exit(app.exec())
