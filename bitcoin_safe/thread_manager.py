import logging

logger = logging.getLogger(__name__)


from PySide2.QtCore import QRunnable, QThreadPool, Signal, QObject
from PySide2.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget, QLabel
from .gui.qt.util import Message
from PySide2.QtCore import QRunnable, QThreadPool, QObject, Signal, QTimer


class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker thread.
    """

    signal = Signal(str)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, f, name="job"):
        super().__init__()
        self.signals = WorkerSignals()
        self.f = f
        self.name = name

    def run(self):
        try:
            result = self.f()
        except Exception as e:
            self.signals.error.emit(repr(e))
            raise
        logger.debug(f"Finished backgorund job {self.name}")
        self.signals.signal.emit(result)


class ThreadManager:
    def __init__(self) -> None:
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(1)

    def _start_in_background_thread(self, my_function, on_finished=None, name="job"):
        worker = Worker(my_function, name=name)
        worker.signals.signal.connect(on_finished)
        worker.signals.error.connect(lambda s: Message(s).show_error())
        future = self.threadpool.start(worker)
        logger.debug(f"future {future} started.")

        return future

    def start_in_background_thread(self, my_function, on_finished=None, name="job"):
        QTimer.singleShot(
            0,
            lambda: self._start_in_background_thread(
                my_function=my_function, on_finished=on_finished, name=name
            ),
        )
