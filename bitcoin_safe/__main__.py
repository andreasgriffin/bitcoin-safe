import argparse
import sys

# all import must be absolute, because this is the entry script for pyinstaller
from bitcoin_safe.logging_setup import setup_logging

setup_logging()

from bitcoin_safe.dynamic_lib_load import ensure_pyzbar_works, set_os_env_ssl_certs  # noqa: E402

set_os_env_ssl_certs()
ensure_pyzbar_works()


import logging  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

from bitcoin_safe.compatibility import check_compatibility  # noqa: E402
from bitcoin_safe.gnome_darkmode import is_gnome_dark_mode, set_dark_palette  # noqa: E402
from bitcoin_safe.gui.qt.main import MainWindow  # noqa: E402
from bitcoin_safe.gui.qt.util import custom_exception_handler  # noqa: E402

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse args."""
    parser = argparse.ArgumentParser(description="Bitcoin Safe")
    parser.add_argument("--network", help="Choose the network: bitcoin, regtest, testnet, signet ")
    parser.add_argument(
        "--profile", action="store_true", help="Enable profiling. VIsualize with snakeviz .prof_stats"
    )
    parser.add_argument("--log_tread_spawning", action="store_true", help="Logs the spawning of threads")
    parser.add_argument(
        "open_files_at_startup",
        metavar="FILE",
        type=str,
        nargs="*",
        help="File to process, can be of type tx, psbt, wallet files.",
    )

    return parser.parse_args()


def log_tread_spawning():
    import threading
    import traceback

    _original_init = threading.Thread.__init__

    def traced_init(self, *args, **kwargs):
        logger.debug(f"\n[THREAD CREATED] name={kwargs.get('name', None) or self.name}")
        logger.debug("".join(traceback.format_stack(limit=50)))
        _original_init(self, *args, **kwargs)

    threading.Thread.__init__ = traced_init  # type: ignore


def main() -> None:
    """Main."""
    args = parse_args()

    if args.log_tread_spawning:
        log_tread_spawning()

    sys.excepthook = custom_exception_handler
    app = QApplication(sys.argv)

    app.setOrganizationName("Bitcoin Safe")
    app.setApplicationName("Bitcoin Safe")

    check_compatibility()

    if is_gnome_dark_mode():
        set_dark_palette(app)

    window = MainWindow(**vars(args))
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
