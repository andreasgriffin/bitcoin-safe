from bitcoin_safe.signals import SignalsMin

from .connected_devices import ConnectedDevices, UnTrustedDevice

if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication, QMainWindow

    class DemoApp(QMainWindow):
        def __init__(self):
            super().__init__()
            signals_min = SignalsMin()
            self.connect_devices = ConnectedDevices(signals_min=signals_min)
            self.setCentralWidget(self.connect_devices)
            self.setWindowTitle("Demo App")
            self.connect_devices.add_untrusted_device(
                UnTrustedDevice("npub_untrusted", signals_min=signals_min)
            )

    if __name__ == "__main__":
        app = QApplication(sys.argv)
        demoApp = DemoApp()
        demoApp.show()
        sys.exit(app.exec())
