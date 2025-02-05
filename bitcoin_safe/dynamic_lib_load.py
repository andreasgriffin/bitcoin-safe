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
import platform
import sys
from ctypes.util import find_library
from pathlib import Path

import bitcoin_usb
import bitcointx

from .html_utils import link
from .i18n import translate

logger = logging.getLogger(__name__)


from PyQt6.QtWidgets import QApplication, QMessageBox


# Function to show the warning dialog before starting the QApplication
def show_warning_before_failiure(msg: str) -> None:
    # Initialize QApplication if not already running
    # the variable app, MUST be here, otherwise the QApplication will not be created
    app = QApplication.instance() or QApplication(sys.argv)

    # Show the warning dialog
    QMessageBox().warning(None, "Warning", msg, QMessageBox.StandardButton.Ok)
    app.quit()


def get_libsecp256k1_os_path() -> str | None:
    "This cannot be used directly, because it doesnt return an absolute path"
    lib_name = "secp256k1"
    return find_library(lib_name)


def get_packaged_libsecp256k1_path() -> str | None:
    if platform.system() == "Linux":
        # for apppimage it is
        # __file__ = squashfs-root/usr/lib/python3.10/site-packages/bitcoin_safe/dynamic_lib_load.py
        # and the lib is in
        # squashfs-root/usr/lib/libsecp256k1.so.0.0.0

        for name in ["libsecp256k1.so.0.0.0", "libsecp256k1.so.0"]:
            lib_path = Path(__file__).parent.parent.parent.parent / name
            logger.debug(f"Searching for {name} in {lib_path.absolute()}")
            if lib_path.exists():
                return str(lib_path)

    elif platform.system() == "Windows":
        # for exe the dlls are packages in the same folder as dynamic_lib_load.py
        # packaged in setup:  __file__ = C:/Program Files/Bitcoin Safe/_internals/bitcoin_safe/dynamic_lib_load.pyc
        # the dll is in: C:/Program Files/Bitcoin Safe/_internals/libsecp256k1-2.dll
        for name in ["libsecp256k1-2.dll"]:
            # logger.info(f"file in  {Path(__file__).absolute()}")
            lib_path = Path(__file__).parent.parent / name
            logger.info(f"Searching for {name} in {lib_path.absolute()}")
            if lib_path.exists():
                return str(lib_path)

    elif platform.system() == "Darwin":
        # for exe the dlls are packages in the same folder as dynamic_lib_load.py
        # packaged in setup:  __file__ = bitcoin_safe/dynamic_lib_load.pyc
        # the dll is in: C:/Program Files/Bitcoin Safe/_internals/libsecp256k1.2.dylib
        for name in ["libsecp256k1.2.dylib"]:
            # logger.info(f"file in  {Path(__file__).absolute()}")
            lib_path = Path(__file__).parent.parent / name
            logger.info(f"Searching for {name} in {lib_path.absolute()}")
            if lib_path.exists():
                return str(lib_path)

    return None


def setup_libsecp256k1() -> None:
    """
    The packaged versions com with libsecp256k1

    Only if you install it via pip/git, libsecp256k1 is required to be on the system
    """

    lib_path = None

    # 1 choice is the packaged version
    packaged_libsecp256k1_path = get_packaged_libsecp256k1_path()
    if packaged_libsecp256k1_path:
        logger.info(f"libsecp256k1 found in package.: {packaged_libsecp256k1_path}")
        lib_path = packaged_libsecp256k1_path

    if lib_path:
        logger.info(f"Setting libsecp256k1: {lib_path}")
        bitcoin_usb.set_custom_secp256k1_path(lib_path)
        bitcointx.set_custom_secp256k1_path(lib_path)
    elif get_libsecp256k1_os_path():
        logger.info(translate("setup_libsecp256k1", f"libsecp256k1 was found in the OS"))
    else:
        msg = translate(
            "dynamic_lib_load", "libsecp256k1 could not be found. Please install libsecp256k1 in your OS."
        )
        logger.warning(msg)
        # cannot show a gui message here, because otherwise
        # pyinstaller (which goes through all module inits)  halts


def ensure_pyzbar_works() -> None:
    "Ensure Visual C++ Redistributable Packages for Visual Studio 2013"
    # Get the platform-specific path to the binary library
    logger.info(f"Platform: {platform.system()}")
    if platform.system() == "Windows":
        logger.info(
            translate(
                "ensure_pyzbar_works",
                "Trying to import pyzbar to see if Visual C++ Redistributable is installed. ",
            )
        )
        try:
            from pyzbar import pyzbar

            pyzbar.__name__
            logger.info(translate("ensure_pyzbar_works", f"pyzbar successfully loaded "))
        except (
            Exception
        ) as e:  #  Do not restrict it to FileNotFoundError, because it can cause other exceptions
            logger.debug(str(e))
            logger.info(translate("ensure_pyzbar_works", f"pyzbar not loaded "))
            show_warning_before_failiure(
                translate("lib_load", """You are missing the {link}\nPlease install it.""").format(
                    link=link(
                        "https://www.microsoft.com/en-US/download/details.aspx?id=40784",
                        "Visual C++ Redistributable Packages for Visual Studio 2013",
                    )
                ),
            )
            sys.exit()
    else:
        # On Linux this shoudn't be a problem, because I include libzar in the package
        pass
