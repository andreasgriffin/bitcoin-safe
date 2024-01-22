import logging

logger = logging.getLogger(__name__)

import cProfile
import sys
from pstats import Stats

from PySide2.QtWidgets import QApplication

from .gui.qt.util import custom_exception_handler
from .main import MainWindow


def main():

    sys.excepthook = custom_exception_handler
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()


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
