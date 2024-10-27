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
import os
import platform
import sys
from ctypes.util import find_library
from importlib.metadata import PackageMetadata
from pathlib import Path
from typing import Optional

import bitcoin_usb
import bitcointx

from .html import link
from .i18n import translate

logger = logging.getLogger(__name__)


from PyQt6.QtWidgets import QApplication, QMessageBox


# Function to show the warning dialog before starting the QApplication
def show_message_before_quit(msg: str) -> None:
    # Initialize QApplication first
    app = QApplication(sys.argv)
    # Without an application instance, some features might not work as expected
    QMessageBox.warning(None, "Warning", msg, QMessageBox.StandardButton.Ok)  # type: ignore[arg-type]
    sys.exit(app.exec())


def get_libsecp256k1_electrumsv_path() -> str:
    from electrumsv_secp256k1 import _libsecp256k1

    # Get the platform-specific path to the binary library
    if platform.system() == "Windows":
        # On Windows, construct the path to the DLL
        here = os.path.dirname(os.path.abspath(_libsecp256k1.__file__))
        lib_path = os.path.join(here, "libsecp256k1.dll")
    else:
        # On Linux and macOS, directly use the __file__ attribute
        lib_path = _libsecp256k1.__file__
    return lib_path


def get_libsecp256k1_os_path() -> str | None:
    "This cannot be used directly, because it doesnt return an absolute path"
    lib_name = "secp256k1"
    return find_library(lib_name)


def get_packaged_libsecp256k1_path() -> str | None:
    # for apppimage it is
    # __file__ = squashfs-root/usr/lib/python3.10/site-packages/bitcoin_safe/dynamic_lib_load.py
    # and the lib is in
    # squashfs-root/usr/lib/libsecp256k1.so.0.0.0
    packaged_lib_path = Path(__file__).parent.parent.parent.parent
    for name in ["libsecp256k1.so.0.0.0", "libsecp256k1.so.0"]:
        lib_path = packaged_lib_path / name
        if lib_path.exists():
            return str(lib_path)
    return None


def setup_libsecp256k1() -> None:
    """The operating system might, or might not provide libsecp256k1 needed for bitcointx

    Therefore we require https://pypi.org/project/electrumsv-secp256k1/ in the build process as additional_requires
    and point the bicointx library here to this binary.

    This isn't ideal, but:
        # electrumsv-secp256k1 offers libsecp256k1 prebuild for different platforms
        # which is needed for bitcointx.
        # bitcointx and with it the prebuild libsecp256k1 is not used for anything security critical
        # key derivation with bitcointx is restricted to testnet/regtest/signet
        # and the PSBTTools using bitcointx is safe because it handles no key material
    """

    lib_path = None

    # 1 choice is the packaged version
    packaged_libsecp256k1_path = get_packaged_libsecp256k1_path()
    if packaged_libsecp256k1_path:
        logger.info(f"libsecp256k1 found in package.: {packaged_libsecp256k1_path}")
        lib_path = packaged_libsecp256k1_path

    # Fallback choice is the electrumsv version
    if not lib_path:
        binary_lib_path_from_electrumsv = get_libsecp256k1_electrumsv_path()
        if binary_lib_path_from_electrumsv:
            logger.info(f"libsecp256k1 found via fallbackmethod: {binary_lib_path_from_electrumsv}")
            lib_path = binary_lib_path_from_electrumsv

    if lib_path:
        logger.info(f"Setting libsecp256k1: {lib_path}")
        bitcoin_usb.set_custom_secp256k1_path(lib_path)
        bitcointx.set_custom_secp256k1_path(lib_path)
    else:
        logger.info(f"libsecp256k1 could not be found at all. This app will not start")


def ensure_pyzbar_works() -> None:
    "Ensure Visual C++ Redistributable Packages for Visual Studio 2013"
    # Get the platform-specific path to the binary library
    logger.info(f"Platform: {platform.system()}")
    if platform.system() == "Windows":
        logger.info("Trying to import pyzbar to see if Visual C++ Redistributable is installed. ")
        try:
            from pyzbar import pyzbar

            pyzbar.__name__
            logger.info(f"pyzbar successfully loaded ")
        except FileNotFoundError:
            logger.info(f"pyzbar not loaded ")
            show_message_before_quit(
                translate("lib_load", """You are missing the {link}\nPlease install it.""").format(
                    link=link(
                        "https://www.microsoft.com/en-US/download/details.aspx?id=40784",
                        "Visual C++ Redistributable Packages for Visual Studio 2013",
                    )
                ),
            )
            sys.exit()
    else:
        # On Linux this shoudn't be a problem, because I specidfied
        # system_runtime_requires = [ "libzbar0",  ....#
        pass


def get_briefcase_meta_data() -> Optional[PackageMetadata]:
    import sys
    from importlib import metadata as importlib_metadata

    # Find the name of the module that was used to start the app
    app_module = sys.modules["__main__"].__package__
    if not app_module:
        return None
    # Retrieve the app's metadata
    metadata = importlib_metadata.metadata(app_module)

    return metadata
