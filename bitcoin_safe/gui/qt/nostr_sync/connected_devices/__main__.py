from .connected_devices import ConnectedDevices, UnTrustedDevice

if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication, QMainWindow

    class DemoApp(QMainWindow):
        def __init__(self):
            super().__init__()
            self.connect_devices = ConnectedDevices()
            self.setCentralWidget(self.connect_devices)
            self.setWindowTitle("Demo App")
            self.connect_devices.add_untrusted_device(UnTrustedDevice("npub_untrusted"))

    if __name__ == "__main__":
        app = QApplication(sys.argv)
        demoApp = DemoApp()
        demoApp.show()
        sys.exit(app.exec())
