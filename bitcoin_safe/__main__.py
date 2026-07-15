# Bitcoin Safe
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

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass

# all import must be absolute, because this is the entry script for pyinstaller
from bitcoin_safe.logging_setup import setup_logging

setup_logging()

from bitcoin_safe.dynamic_lib_load import ensure_pyzbar_works, set_os_env_ssl_certs  # noqa: E402

set_os_env_ssl_certs()
ensure_pyzbar_works()

import bdkpython as bdk  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from bitcoin_safe.compatibility import check_compatibility  # noqa: E402
from bitcoin_safe.gnome_darkmode import is_gnome_dark_mode, set_dark_palette  # noqa: E402
from bitcoin_safe.gui.qt.main import MainWindow  # noqa: E402
from bitcoin_safe.gui.qt.startup_window_probe import StartupWindowProbe  # noqa: E402
from bitcoin_safe.gui.qt.util import custom_exception_handler  # noqa: E402

logger = logging.getLogger(__name__)
NETWORK_ARG_NAMES = tuple(sorted(network.name.lower() for network in bdk.Network))
NETWORK_ARGS = {network_name: bdk.Network[network_name.upper()] for network_name in NETWORK_ARG_NAMES}


@dataclass
class StartupArgs:
    network: bdk.Network | None
    profile: bool
    trace_startup_windows: bool
    open_files_at_startup: list[str]


def create_parser() -> argparse.ArgumentParser:
    """Create the startup parser."""
    parser = argparse.ArgumentParser(description="Bitcoin Safe", allow_abbrev=False)
    parser.add_argument("--network", help=f"Choose the network: {', '.join(NETWORK_ARG_NAMES)}")
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
    return parser


def sanitize_network_arg(network: str | None) -> bdk.Network | None:
    """Validate the CLI network value."""
    if network is None:
        return None
    if normalized_network := NETWORK_ARGS.get(network.lower()):
        return normalized_network

    logger.warning(
        "Ignoring invalid --network value %r. Accepted values: %s",
        network,
        ", ".join(NETWORK_ARG_NAMES),
    )
    return None


def parse_args(argv: Sequence[str] | None = None) -> StartupArgs:
    """Parse and sanitize startup args."""
    parser = create_parser()
    namespace, unknown_args = parser.parse_known_args(argv)

    if unknown_args:
        logger.warning("Ignoring unknown startup arguments: %s", unknown_args)

    return StartupArgs(
        network=sanitize_network_arg(namespace.network),
        profile=namespace.profile,
        trace_startup_windows=namespace.trace_startup_windows,
        open_files_at_startup=list(namespace.open_files_at_startup),
    )


def main(args: StartupArgs | None = None) -> None:
    """Main."""
    startup_args = args if args is not None else parse_args()

    sys.excepthook = custom_exception_handler
    app = QApplication(sys.argv)

    app.setOrganizationName("Bitcoin Safe")
    app.setApplicationName("Bitcoin Safe")

    check_compatibility()

    if is_gnome_dark_mode():
        set_dark_palette(app)

    window = MainWindow(
        network=startup_args.network,
        open_files_at_startup=startup_args.open_files_at_startup,
    )
    if startup_args.trace_startup_windows:
        app._startup_window_probe = StartupWindowProbe(app=app, expected_main_window=window)  # type: ignore
    window.show()
    app.exec()


# py-spy record -o prof.speedscope.json --format speedscope --rate 20 --native -- python -m bitcoin_safe
# open in https://www.speedscope.app/

if __name__ == "__main__":
    startup_args = parse_args()

    if startup_args.profile:
        import cProfile
        import os
        from pstats import Stats

        with cProfile.Profile() as pr:
            main(startup_args)

        # run in bash "snakeviz .prof_stats &"  to visualize the stats
        with open("profiling_stats.txt", "w") as stream:
            stats = Stats(pr, stream=stream)
            stats.strip_dirs()
            stats.sort_stats("time")
            stats.dump_stats(".prof_stats")
            os.system("snakeviz .prof_stats & ")
            # os.system("pyprof2calltree -i .prof_stats -k & ")
    else:
        main(startup_args)
