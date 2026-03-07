import argparse
import sys

# all import must be absolute, because this is the entry script for pyinstaller
# Bitcoin Safe
# Copyright (C) 2023-2026 Andreas Griffin
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
from bitcoin_safe.logging_setup import setup_logging

setup_logging()

from bitcoin_safe.dynamic_lib_load import ensure_pyzbar_works, set_os_env_ssl_certs  # noqa: E402

set_os_env_ssl_certs()
ensure_pyzbar_works()


from PyQt6.QtWidgets import QApplication  # noqa: E402

from bitcoin_safe.compatibility import check_compatibility  # noqa: E402
from bitcoin_safe.gnome_darkmode import is_gnome_dark_mode, set_dark_palette  # noqa: E402
from bitcoin_safe.gui.qt.main import MainWindow  # noqa: E402
from bitcoin_safe.gui.qt.startup_window_probe import StartupWindowProbe  # noqa: E402
from bitcoin_safe.gui.qt.util import custom_exception_handler  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse args."""
    parser = argparse.ArgumentParser(description="Bitcoin Safe")
    parser.add_argument("--network", help="Choose the network: bitcoin, regtest, testnet, signet ")
    parser.add_argument(
        "--profile", action="store_true", help="Enable profiling. VIsualize with snakeviz .prof_stats"
    )
    parser.add_argument(
        "--trace-startup-windows",
        action="store_true",
        help="Log transient startup windows for debugging UI flashing",
    )
    parser.add_argument(
        "open_files_at_startup",
        metavar="FILE",
        type=str,
        nargs="*",
        help="File to process, can be of type tx, psbt, wallet files.",
    )

    return parser.parse_args()


def main() -> None:
    """Main."""
    args = parse_args()

    sys.excepthook = custom_exception_handler
    app = QApplication(sys.argv)

    app.setOrganizationName("Bitcoin Safe")
    app.setApplicationName("Bitcoin Safe")

    check_compatibility()

    if is_gnome_dark_mode():
        set_dark_palette(app)

    window = MainWindow(**vars(args))
    if args.trace_startup_windows:
        app._startup_window_probe = StartupWindowProbe(app=app, expected_main_window=window)  # type: ignore
    window.show()
    app.exec()


# py-spy record -o prof.speedscope.json --format speedscope --rate 20 --native -- python -m bitcoin_safe
# open in https://www.speedscope.app/

if __name__ == "__main__":
    args = parse_args()

    if args.profile:
        import cProfile
        import os
        from pstats import Stats

        with cProfile.Profile() as pr:
            main()

        # run in bash "snakeviz .prof_stats &"  to visualize the stats
        with open("profiling_stats.txt", "w") as stream:
            stats = Stats(pr, stream=stream)
            stats.strip_dirs()
            stats.sort_stats("time")
            stats.dump_stats(".prof_stats")
            os.system("snakeviz .prof_stats & ")
            # os.system("pyprof2calltree -i .prof_stats -k & ")
    else:
        main()
