
    
import cProfile
from pstats import Stats, SortKey


from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *

from .main import MainWindow
import sys
    
    
def main():
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec_()


if __name__ == '__main__':
    from .util import DEVELOPMENT_PREFILLS
    do_profiling =  DEVELOPMENT_PREFILLS
    if do_profiling:
        with cProfile.Profile() as pr:
            main()

        with open('profiling_stats.txt', 'w') as stream:
            stats = Stats(pr, stream=stream)
            stats.strip_dirs()
            stats.sort_stats('time')
            stats.dump_stats('.prof_stats')
            stats.print_stats()
    else:
        main()
