from .logging_setup import setup_logging

setup_logging()


import argparse
import cProfile
import sys
from pstats import Stats

from PyQt6.QtWidgets import QApplication

from .gui.qt.main import MainWindow
from .gui.qt.util import custom_exception_handler


def main():

    parser = argparse.ArgumentParser(description="Bitcoin Safe")
    parser.add_argument("--network", help="Choose the network: bitcoin, regtest, testnet, signet ")

    args = parser.parse_args()

    sys.excepthook = custom_exception_handler
    app = QApplication(sys.argv)
    window = MainWindow(**vars(args))
    window.show()
    app.exec()


if __name__ == "__main__":
    from .util import DEVELOPMENT_PREFILLS

    do_profiling = DEVELOPMENT_PREFILLS
    if do_profiling:
        with cProfile.Profile() as pr:
            main()

        # run in bash "snakeviz .prof_stats &"  to visualize the stats
        with open("profiling_stats.txt", "w") as stream:
            stats = Stats(pr, stream=stream)
            stats.strip_dirs()
            stats.sort_stats("time")
            stats.dump_stats(".prof_stats")
            stats.print_stats()
    else:
        main()
