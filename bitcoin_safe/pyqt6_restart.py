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

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import (
    QCoreApplication,
    QProcess,
    QProcessEnvironment,
    Qt,
)

logger = logging.getLogger(__name__)


def build_restart_command(params: Iterable[str] | None = None) -> list[str]:
    # Adapt as needed: full command line for your app.
    #
    # ``sys.argv[0]`` may not be meaningful once the app is packaged with
    # PyInstaller (``sys.frozen`` is True) because there is no Python entry
    # script to execute. In that scenario, relaunch the bundled executable
    # directly instead of trying to hand PyInstaller a script path that does
    # not exist on disk.
    argv = list(params if params is not None else sys.argv[1:])
    logger.debug("Building restart command params=%s sys_argv=%s", argv, sys.argv)

    if getattr(sys, "frozen", False):
        # ``sys.executable`` points at the unpacked bootloader when running a
        # PyInstaller one-file build. Relaunching that temporary copy leaves the
        # original on-disk ``portable.exe`` locked (and triggers warnings when
        # the temp directory cannot be cleaned). Prefer the original launcher
        # path carried in ``sys.argv[0]`` so the user-visible executable restarts
        # instead of the unpacked helper. Fall back to the bootloader path when
        # the original path is unavailable (e.g., when invoked from a temporary
        # location during development).
        if os.name == "nt":
            meipass = getattr(sys, "_MEIPASS", None)
            exe_dir = Path(sys.executable).resolve().parent
            portable_exe = Path(sys.argv[0]).resolve()
            logger.debug(
                "PyInstaller frozen build detected meipass=%s exe_dir=%s portable_exe=%s portable_exists=%s",
                meipass,
                exe_dir,
                portable_exe,
                portable_exe.exists(),
            )
            if meipass and portable_exe.exists() and Path(meipass).resolve() != exe_dir:
                logger.info(
                    "Using portable executable for restart portable_exe=%s bootloader_exe=%s argv=%s",
                    portable_exe,
                    sys.executable,
                    argv,
                )
                return [str(portable_exe), *argv]

        logger.info(
            "Falling back to frozen executable for restart executable=%s argv=%s",
            sys.executable,
            argv,
        )
        return [sys.executable, *argv]

    cmd = [sys.executable, sys.argv[0]]
    cmd.extend(argv)
    logger.info("Restart command for non-frozen build cmd=%s", cmd)
    return cmd


def restart_application(
    params: Iterable[str] | None = None,
) -> None:
    env = os.environ.copy()
    base_cmd = build_restart_command(params)
    logger.debug(
        "Restarting application base_cmd=%s cwd=%s frozen=%s os_name=%s sys_executable=%s sys_argv=%s _MEIPASS=%s _MEIPASS2=%s PATH_head=%s PYTHONPATH=%s",
        base_cmd,
        Path.cwd(),
        getattr(sys, "frozen", False),
        os.name,
        sys.executable,
        sys.argv,
        getattr(sys, "_MEIPASS", None),
        os.environ.get("_MEIPASS2"),
        os.environ.get("PATH", "").split(os.pathsep)[:4],
        os.environ.get("PYTHONPATH"),
    )

    if os.name == "nt":
        frozen = getattr(sys, "frozen", False)

        if frozen:

            def _normalize_path(value: str) -> str:
                return value.replace("/", os.sep).replace("\\", os.sep).lower()

            def _strip_mei_env(env: dict[str, str]) -> dict[str, str]:
                """Remove PyInstaller extraction references so the child picks a fresh _MEI.

                When the parent process was launched from a PyInstaller one-file
                build, its environment contains absolute paths into the temporary
                ``_MEI`` extraction directory. If we forward those unchanged, the
                relaunched process may look for bundled DLLs in the stale
                directory that the bootloader has already cleaned up, producing
                ``FileNotFoundError`` on startup. Clearing these variables lets
                the child rebuild its own extraction directory.
                """

                norm_entries = {k: _normalize_path(v) for k, v in env.items() if isinstance(v, str)}

                for key in list(env.keys()):
                    if key == "PATH":
                        continue

                    should_drop = False
                    if key.upper().find("MEI") != -1 or key.startswith("_PYI"):
                        should_drop = True

                    if key in {"_MEIPASS", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR"}:
                        should_drop = True

                    norm_value = norm_entries.get(key)
                    if norm_value and f"{os.sep}_mei" in norm_value:
                        should_drop = True

                    if should_drop:
                        logger.debug("Dropping stale env var %s=%s", key, env.pop(key))

                if "PATH" in env:
                    env["PATH"] = os.pathsep.join(
                        entry
                        for entry in env["PATH"].split(os.pathsep)
                        if f"{os.sep}_mei" not in _normalize_path(entry)
                    )

                return env

            # In PyInstaller one-file mode, the embedded files (like ``cv2.pyd``)
            # live in a temporary ``_MEIPASS`` directory. When we relaunch from
            # the running bundle we must forward that extraction path to the
            # child process, otherwise imports that rely on those bundled
            # binaries may fail (e.g. ``ModuleNotFoundError: No module named
            # 'cv2'``). Only adjust the environment when ``_MEIPASS`` points to
            # a different location than the executable directory, which is the
            # signature of PyInstaller's single-file layout on Windows.
            meipass = getattr(sys, "_MEIPASS", None)
            logger.debug(
                "Windows frozen restart detected meipass=%s sys_executable=%s sys_argv0=%s",
                meipass,
                sys.executable,
                sys.argv[0],
            )
            # Packaged with PyInstaller: ``sys.executable`` already points at
            # the bundled GUI executable, so we can relaunch it directly
            # without the helper script that expects an importable Python
            # runtime.
            subprocess.Popen(
                base_cmd,
                cwd=Path.cwd(),
                env=_strip_mei_env(env),
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                "Spawned Windows frozen restart process cmd=%s env_keys=%s",
                base_cmd,
                sorted(env.keys()),
            )

            QCoreApplication.quit()
            return

        # ---- Windows: use helper with BREAKAWAY_FROM_JOB ----

        # ``sys.argv[0]`` may point at a debugger stub (e.g. debugpy, pdb)
        # rather than the actual application script when running under a
        # debugger. Resolve the helper relative to this module to avoid using
        # the debugger's location, which prevented restarts while debugging on
        # Windows.
        helper = Path(__file__).with_name("restart_helper.py")
        logger.debug("Using Windows restart helper helper=%s base_cmd=%s", helper, base_cmd)

        python_exe = Path(sys.executable)
        pythonw_exe = python_exe.with_name("pythonw.exe")
        launcher = pythonw_exe if pythonw_exe.exists() else python_exe

        # Ensure the restarted application also uses ``pythonw.exe`` when available
        # so no console window is created for the relaunched process.
        if pythonw_exe.exists():
            base_cmd[0] = str(pythonw_exe)

        full_cmd = [str(launcher), str(helper), *base_cmd]
        logger.info(
            "Launching Windows restart via helper launcher=%s full_cmd=%s cwd=%s",
            launcher,
            full_cmd,
            Path.cwd(),
        )

        startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESTDHANDLES", 0)

        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

        subprocess.Popen(
            full_cmd,
            cwd=Path.cwd(),
            env=env,
            startupinfo=startupinfo,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(
            "Spawned Windows helper restart process cmd=%s env_keys=%s",
            full_cmd,
            sorted(env.keys()),
        )

        QCoreApplication.quit()
        return

    # ---- Non-Windows: regular Qt-detached restart ----
    program = base_cmd[0]
    arguments = base_cmd[1:]
    logger.info(
        "Launching non-Windows restart program=%s arguments=%s cwd=%s",
        program,
        arguments,
        Path.cwd(),
    )

    process = QProcess()
    process.setProgram(program)
    process.setArguments(arguments)
    process.setWorkingDirectory(str(Path.cwd()))

    qenv = QProcessEnvironment()
    for key, value in env.items():
        qenv.insert(key, value)
    process.setProcessEnvironment(qenv)

    if process.startDetached():
        QCoreApplication.exit(0)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QApplication,
        QLabel,
        QLineEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    @dataclass
    class RestartOptions:
        """Parameters that influence how the app restarts."""

        home_dir: str | None = None
        network: str = "default"
        log_level: str | None = None

        def to_params(self) -> list[str]:
            """Convert the options into command-line switches.

            The resulting list matches the Java client's ``Args.toParams`` output
            so the restarted process behaves identically regardless of platform.
            """

            params: list[str] = []
            if self.home_dir:
                params.extend(["-d", self.home_dir])
            if self.network:
                params.extend(["-n", self.network])
            if self.log_level:
                params.extend(["-l", self.log_level])
            return params

    def parse_restart_args(argv: Sequence[str] | None = None) -> RestartOptions:
        """Parse the current process arguments into :class:`RestartOptions`.

        Only the flags used by the Java restart flow are supported; all other
        arguments are intentionally ignored to keep behavior consistent with the
        desktop client.
        """

        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("-d", "--dir", dest="home_dir")
        parser.add_argument("-n", "--network")
        parser.add_argument("-l", "--level", dest="log_level")

        # ``parse_known_args`` ensures unknown flags don't raise, matching the
        # JCommander configuration in ``AppController.getRestartArgs``.
        args, _ = parser.parse_known_args(argv)
        return RestartOptions(args.home_dir, args.network, args.log_level)

    def _build_description(opts: RestartOptions) -> str:
        parts = [f"Executable: {Path(sys.argv[0]).resolve()}"]
        if opts.home_dir:
            parts.append(f"Home directory: {opts.home_dir}")
        if opts.network:
            parts.append(f"Network: {opts.network}")
        if opts.log_level:
            parts.append(f"Log level: {opts.log_level}")
        if not opts.home_dir and not opts.network and not opts.log_level:
            parts.append("No restart flags detected")
        return "\n".join(parts)

    def main() -> int:
        app = QApplication(sys.argv)

        opts = parse_restart_args()
        description = QLabel(_build_description(opts))
        description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        status = QLabel("Press restart to relaunch with a toggled network flag.")

        extra_args_input = QLineEdit()
        extra_args_input.setPlaceholderText("Optional extra args (space separated)")

        button = QPushButton("Restart")

        def do_restart() -> None:
            status.setText("Restarting...")
            restart_application(
                params=extra_args_input.text().strip().split(" "),
            )

        button.clicked.connect(do_restart)

        layout = QVBoxLayout()
        layout.addWidget(description)
        layout.addWidget(extra_args_input)
        layout.addWidget(status)
        layout.addWidget(button)

        window = QWidget()
        window.setWindowTitle("PyQt Restart Demo")
        window.setLayout(layout)
        window.resize(420, 200)
        window.show()

        return app.exec()

    if __name__ == "__main__":
        raise SystemExit(main())
