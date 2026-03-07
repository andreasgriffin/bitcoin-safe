#
# Bitcoin Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import bdkpython as bdk
import numpy as np
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.network_settings.main import NetworkSettingsUI
from bitcoin_safe.network_config import NetworkConfigs

logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    import os
    import sys

    from PyQt6.QtWidgets import QApplication, QMainWindow

    class DemoApp(QMainWindow):
        def __init__(self):
            """Initialize instance."""
            super().__init__()

            if os.path.exists("network_configs.json"):
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

            self.network_settings_ui.signal_apply_and_shutdown.connect(self.save_and_close)
            self.network_settings_ui.signal_cancel.connect(self.close)

        def save_and_close(self, network: bdk.Network):
            """Save and close."""
            self.network_settings_ui.network_configs.save("network_configs.json")
            self.close()

    app = QApplication(sys.argv)
    demoApp = DemoApp()
    demoApp.show()
    sys.exit(app.exec())
