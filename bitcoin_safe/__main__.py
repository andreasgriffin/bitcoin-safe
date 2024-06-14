import sys

from .dynamic_lib_load import ensure_pyzbar_works

# this setsup the logging
from .logging_setup import setup_logging  # type: ignore

ensure_pyzbar_works()

import argparse
import sys

from PyQt6.QtWidgets import QApplication

from .gui.qt.main import MainWindow
from .gui.qt.util import custom_exception_handler


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(description="Bitcoin Safe")
    parser.add_argument("--network", help="Choose the network: bitcoin, regtest, testnet, signet ")
    parser.add_argument(
        "--profile", action="store_true", help="Enable profiling. VIsualize with snakeviz .prof_stats"
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    sys.excepthook = custom_exception_handler
    app = QApplication(sys.argv)
    window = MainWindow(**vars(args))
    window.show()
    app.exec()


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
