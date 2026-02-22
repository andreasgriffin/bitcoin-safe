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

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from bitcoin_safe import pyqt6_restart


class _FakeQProcessEnvironment:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def insert(self, key: str, value: str) -> None:
        self.values[key] = value


class _FakeQProcess:
    last: _FakeQProcess | None = None

    def __init__(self) -> None:
        self.program = ""
        self.arguments: list[str] = []
        self.working_directory = ""
        self.environment: _FakeQProcessEnvironment | None = None
        _FakeQProcess.last = self

    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, arguments: list[str]) -> None:
        self.arguments = list(arguments)

    def setWorkingDirectory(self, working_directory: str) -> None:
        self.working_directory = working_directory

    def setProcessEnvironment(self, environment: _FakeQProcessEnvironment) -> None:
        self.environment = environment

    def startDetached(self) -> bool:
        return False


def test_restart_application_uses_provided_restart_command(monkeypatch) -> None:
    def fail_build_restart_command(params: Iterable[str] | None = None) -> list[str]:
        del params
        raise AssertionError("build_restart_command must not be called when restart_command is provided")

    monkeypatch.setattr(pyqt6_restart, "build_restart_command", fail_build_restart_command)
    monkeypatch.setattr(pyqt6_restart, "QProcess", _FakeQProcess)
    monkeypatch.setattr(pyqt6_restart, "QProcessEnvironment", _FakeQProcessEnvironment)

    pyqt6_restart.restart_application(
        params=["--unused"],
        restart_command=["/custom/restart-binary", "--network", "testnet"],
    )

    assert _FakeQProcess.last is not None
    assert _FakeQProcess.last.program == "/custom/restart-binary"
    assert _FakeQProcess.last.arguments == ["--network", "testnet"]


def test_restart_application_builds_command_when_restart_command_missing(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_build_restart_command(params: Iterable[str] | None = None) -> list[str]:
        calls.append(list(params or []))
        return ["/built/restart-binary", "--flag"]

    monkeypatch.setattr(pyqt6_restart, "build_restart_command", fake_build_restart_command)
    monkeypatch.setattr(pyqt6_restart, "QProcess", _FakeQProcess)
    monkeypatch.setattr(pyqt6_restart, "QProcessEnvironment", _FakeQProcessEnvironment)

    pyqt6_restart.restart_application(params=["--expected"])

    assert calls == [["--expected"]]
    assert _FakeQProcess.last is not None
    assert _FakeQProcess.last.program == "/built/restart-binary"
    assert _FakeQProcess.last.arguments == ["--flag"]


def test_resolve_windows_runtime_executable_prefers_stable_entrypoint_in_meipass(tmp_path: Path) -> None:
    meipass_dir = tmp_path / "_MEI12345"
    meipass_dir.mkdir()
    bootloader_exe = meipass_dir / "Bitcoin-Safe.exe"
    bootloader_exe.write_text("bootloader")

    app_dir = tmp_path / "appdir"
    app_dir.mkdir()
    portable_exe = app_dir / "Bitcoin-Safe-portable.exe"
    portable_exe.write_text("portable")

    resolved_executable = pyqt6_restart.resolve_windows_runtime_executable(
        current_binary=bootloader_exe,
        runtime_entrypoint=portable_exe,
        env={"_MEIPASS": str(meipass_dir)},
        os_name="nt",
    )

    assert resolved_executable == portable_exe


def test_resolve_windows_runtime_executable_keeps_current_binary_without_meipass(tmp_path: Path) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    current_exe = binary_dir / "Bitcoin-Safe.exe"
    current_exe.write_text("current")

    app_dir = tmp_path / "appdir"
    app_dir.mkdir()
    portable_exe = app_dir / "Bitcoin-Safe-portable.exe"
    portable_exe.write_text("portable")

    resolved_executable = pyqt6_restart.resolve_windows_runtime_executable(
        current_binary=current_exe,
        runtime_entrypoint=portable_exe,
        env={},
        os_name="nt",
    )

    assert resolved_executable == current_exe
