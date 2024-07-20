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
import sys
import threading
from collections import deque
from typing import Any, Callable, NamedTuple, Optional, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from bitcoin_safe.signals import SignalsMin

logger = logging.getLogger(__name__)


class Task(NamedTuple):
    """Structure for task details."""

    do: Callable[..., Any]
    cb_success: Callable[[Any], None]
    cb_done: Callable[[Any], None]
    cb_error: Callable[[Tuple[Any, ...]], None]
    cancel: Optional[Callable[[], None]] = None


class Worker(QObject):
    """Worker object to perform tasks in a separate thread."""

    finished: pyqtSignal = pyqtSignal(object, object, object)  # Result, cb_done, cb_success/error
    error: pyqtSignal = pyqtSignal(object)

    def __init__(self, task: Task) -> None:
        super().__init__()
        self.task: Task = task

    @property
    def thread_name(self):
        return str(self.task.do)

    @pyqtSlot()
    def run_task(self) -> None:
        """Executes the provided task and emits signals based on the outcome."""
        threading.current_thread().name = self.thread_name
        if not self.task:
            logger.debug("No task to run.")
            return

        try:
            logger.debug(f"Task started: {self.task.do}")
            result: Any = self.task.do()
            logger.debug(f"Task finished: {self.task.do}")
            self.finished.emit(result, self.task.cb_done, self.task.cb_success)
        except Exception:
            logger.exception(f"Task raised an exception: {self.task.do}")
            self.error.emit((sys.exc_info(), self.task.cb_error))
        finally:
            if callable(self.task.cancel):
                logger.debug(f"Task cancellation callback called: {self.task.do}")
                self.task.cancel()


class TaskThread(QThread):
    """Manages execution of tasks in separate threads."""

    def __init__(self, parent: QObject, signals_min: SignalsMin) -> None:
        super().__init__(parent)
        self.signals_min = signals_min
        self.worker: Optional[
            Worker
        ] = None  # Type hint adjusted because it will be immediately initialized in add_and_start

    def add_and_start(
        self,
        do: Callable[..., Any],
        on_success: Callable[[Any], None],
        on_done: Callable[[Any], None],
        on_error: Callable[[Tuple[Any, ...]], None],
        cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        logger.debug(f"Starting new thread {do}.")
        task: Task = Task(do, on_success, on_done, on_error, cancel)
        self.worker = Worker(task)
        self.worker.moveToThread(self)
        self.worker.finished.connect(self.on_done)
        self.worker.error.connect(self.on_error)
        self.started.connect(self.worker.run_task)
        self.signals_min.signal_add_threat.emit(self)
        self.start()

    @property
    def thread_name(self):
        if not self.worker:
            return None
        if self.worker.thread_name:
            return self.worker.thread_name

    def on_error(self, error_info):
        if self.worker:
            self.worker.task.cb_error(error_info)
        self.my_quit()

    @pyqtSlot(object, object, object)
    def on_done(self, result: Any, cb_done: Callable[[Any], None], cb_result: Callable[[Any], None]) -> None:
        """Handle task completion."""
        logger.debug(f"Thread done: {self.thread_name}.")
        cb_done(result)
        cb_result(result)
        self.my_quit()

    def stop(self) -> None:
        """Stops the thread and any associated task cancellation if defined."""
        logger.debug("Stopping TaskThread and associated worker.")
        if self.worker and self.worker.task.cancel:
            logger.debug(f"Stopping {self.thread_name}.")
            self.worker.task.cancel()
        self.my_quit()

    def my_quit(self):
        self.quit()
        self.wait()
        self.signals_min.signal_stop_threat.emit(self)


class NoThread:
    "This is great for debugging purposes"

    def __init__(self, *args, **kwargs):
        pass

    def add_and_start(
        self,
        task,
        on_success: Callable = None,
        on_done: Callable = None,
        on_error: Callable = None,
    ):
        result = None
        try:
            if task:
                result = task()
            if on_success:
                on_success(result)
        except Exception:
            if on_error:
                on_error(sys.exc_info())
        if on_done:
            on_done(result)


from threading import Lock


class ThreadingManager:
    def __init__(self, signals_min: SignalsMin) -> None:
        self.signals_min = signals_min
        self.threads: deque[TaskThread] = deque()
        self.lock = Lock()

        self.signals_min.signal_add_threat.connect(self._append)
        self.signals_min.signal_stop_threat.connect(self._remove)

    def _append(self, thread: TaskThread):
        with self.lock:
            self.threads.append(thread)
            logger.debug(
                f"Appended thread {thread.thread_name}, Number of threads = {len(self.threads)} {[thread.thread_name for thread in   self.threads]}"
            )
            assert thread in self.threads

    def _remove(self, thread: TaskThread):
        with self.lock:
            if thread in self.threads:
                self.threads.remove(thread)
                thread.deleteLater()
            logger.debug(
                f"Removed thread {thread.thread_name}, Number of threads = {len(self.threads)} {[thread.thread_name for thread in   self.threads]}"
            )

    def stop_and_wait_all(self, timeout=10):
        # Wait for all threads to finish
        if self.threads:
            logger.warning(f"unfinished Threads {list(self.threads)}")
        for thread in list(self.threads):
            if thread.isRunning():
                thread.stop()
                if not thread.wait(timeout * 1000):
                    logger.warning(f"Thread {thread.thread_name } did not finish timely")
