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


from typing import Any, Callable, Generic, Optional

from PyQt6.QtCore import QMetaObject
from typing_extensions import TypeVarTuple, Unpack

Ts = TypeVarTuple("Ts")


class TypedPyQtSignal(Generic[Unpack[Ts]]):
    "ONLY FOR Type hints!!!"

    def connect(self, slot: "Callable[[Unpack[Ts]], Any]|TypedPyQtSignal[Unpack[Ts]]") -> QMetaObject.Connection:  # type: ignore
        pass

    def emit(self, *args: Unpack[Ts]) -> None:
        pass

    def disconnect(self, slot: Optional[Callable[[Unpack[Ts]], Any]] = None) -> None:
        pass


class TypedPyQtSignalNo:
    "ONLY FOR Type hints!!!"

    def connect(self, slot: "Callable[[], Any]|TypedPyQtSignalNo") -> QMetaObject.Connection:  # type: ignore
        pass

    def emit(self) -> None:
        pass

    def disconnect(self, slot: Optional[Callable[[], Any]] = None) -> None:
        pass