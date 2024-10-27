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
from threading import Lock
from types import TracebackType
from typing import Any, Callable, NamedTuple, Optional, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from bitcoin_safe.execute_config import ENABLE_THREADING

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
    error: pyqtSignal = pyqtSignal(object, object)

    def __init__(self, task: Task) -> None:
        super().__init__()
        self.task: Task = task
        self.thread_name = str(self.task.do)

    @pyqtSlot()
    def run_task(self) -> None:
        """Executes the provided task and emits signals based on the outcome."""
        threading.current_thread().name = self.thread_name
        try:
            logger.debug(f"Task started: {self.task.do}")
            result: Any = self.task.do()
            logger.debug(f"Task finished: {self.task.do}")
            self.finished.emit(result, self.task.cb_done, self.task.cb_success)
        except Exception:
            logger.exception(f"Task raised an exception: {self.task.do}")
            self.error.emit(sys.exc_info(), self.task.cb_error)
        finally:
            if callable(self.task.cancel):
                logger.debug(f"Task cancellation callback called: {self.task.do}")
                self.task.cancel()


class TaskThread(QThread):
    """Manages execution of tasks in separate threads."""

    signal_stop_threat = pyqtSignal(str)

    def __init__(self, enable_threading: bool = ENABLE_THREADING) -> None:
        super().__init__()
        self.worker: Optional[Worker] = (
            None  # Type hint adjusted because it will be immediately initialized in add_and_start
        )
        self.enable_threading = enable_threading
        self._thread_name: str | None = None

    @property
    def thread_name(self) -> str | None:
        return self._thread_name

    @thread_name.setter
    def thread_name(self, value: str | None):
        logger.debug(f"setting thread_name of {self} to {value}")
        self._thread_name = value

    def __str__(self) -> str:
        return str(self.thread_name)

    def add_and_start(
        self,
        do: Callable[..., Any],
        on_success: Callable[[Any], None],
        on_done: Callable[[Any], None],
        on_error: Callable[[Tuple[Any, ...]], None],
        cancel: Optional[Callable[[], None]] = None,
    ) -> "TaskThread":

        # if not self.enable_threading:
        #     NoThread().add_and_start(do, on_success, on_done, on_error)
        #     return self

        self.cancelled = False

        task: Task = Task(do, on_success, on_done, on_error, cancel)
        self.worker = Worker(task)
        if self.enable_threading:
            self.worker.moveToThread(self)
        self.worker.finished.connect(self.on_done)
        self.worker.error.connect(self.on_error)
        self.started.connect(self.worker.run_task)

        self.thread_name = self.worker.thread_name
        logger.debug(f"Starting new thread {self.thread_name}")

        self.start()

        return self

    def on_error(
        self,
        error_info: tuple[type[BaseException], BaseException, TracebackType],
        cb_error: Callable[[Any], None],
    ):
        if self.worker:
            cb_error(error_info)
        self.my_quit()

    @pyqtSlot(object, object, object)
    def on_done(self, result: Any, cb_done: Callable[[Any], None], cb_result: Callable[[Any], None]) -> None:
        """Handle task completion."""
        if not self.cancelled:
            logger.debug(f"Thread done: {self.thread_name}.")
            cb_done(result)
            cb_result(result)
        self.my_quit()

    def stop(self) -> None:
        """Stops the thread and any associated task cancellation if defined."""
        logger.debug(f"Stopping {self.thread_name}.")
        if self.worker and self.worker.task.cancel:
            self.cancelled = True
            self.worker.task.cancel()
        self.my_quit()
        logger.debug(f"Stopped {self.thread_name}.")

    def my_quit(self):
        try:
            self.cancelled = True
            self.quit()
            self.wait()
            self.signal_stop_threat.emit(self.thread_name)
        except:
            logger.error(f"An error during the shutdown of {self.thread_name}")


class NoThread:
    "This is great for debugging purposes"

    def __init__(self, *args, **kwargs):
        pass

    def add_and_start(
        self,
        task,
        on_success: Optional[Callable] = None,
        on_done: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
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


class ThreadingManager:
    def __init__(
        self, threading_parent: "ThreadingManager" = None, threading_manager_name=None, **kwargs  # type: ignore
    ) -> None:
        super().__init__(**kwargs)
        self._taskthreads: deque[TaskThread] = deque()
        self.threading_manager_children: deque[ThreadingManager] = deque()
        self.lock = Lock()
        self.threading_parent = threading_parent
        self.threading_manager_name = (
            threading_manager_name if threading_manager_name else self.__class__.__name__
        )

        if threading_parent:
            threading_parent.threading_manager_children.append(self)

    def append_thread(self, thread: TaskThread):
        with self.lock:
            self._taskthreads.append(thread)
            thread.signal_stop_threat.connect(self.remove_thread)
            logger.debug(
                f"Appended thread {thread.thread_name} to {self.threading_manager_name}, Number of threads = {len(self._taskthreads)} {[str(thread) for thread in  self._taskthreads]}"
            )

    def remove_thread(self, thread_name: str | None):
        with self.lock:
            for thread in list(self._taskthreads):
                # if not thread.thread_name:
                #     # remove empty threads
                #     # (unclear why thread_name is set to None when threads are done)
                #     self.taskthreads.remove(thread)
                if thread.thread_name == thread_name:
                    self._taskthreads.remove(thread)
            logger.debug(
                f"Removed thread {thread_name} from {self.threading_manager_name}, Number of threads = {len(self._taskthreads)} {[str(thread) for thread in  self._taskthreads]}"
            )

    def stop_and_wait_all(self):
        while self.threading_manager_children:
            child = self.threading_manager_children.pop()
            child.end_threading_manager()

        # Wait for all threads to finish
        while self._taskthreads:
            taskthread = self._taskthreads.pop()
            logger.debug(f"stop taskthreads {taskthread}")
            taskthread.stop()

    def end_threading_manager(self):
        logger.debug(f"end_threading_manager of {self}")
        self.stop_and_wait_all()

        if self.threading_parent and self in self.threading_parent.threading_manager_children:
            self.threading_parent.threading_manager_children.remove(self)
