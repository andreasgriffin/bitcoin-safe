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

# Original Version from:
# Electrum - lightweight Bitcoin client
# Copyright (C) 2011 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
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

import os
import platform
import shlex
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

# do not import logging, because has this a dependency for setup_logging


def linux_env():
    # Create a copy of the current environment variables.
    """Linux env."""
    env = os.environ.copy()

    # Set LD_LIBRARY_PATH to prefer system libraries.
    paths = ["/usr/lib", "/usr/lib/x86_64-linux-gnu"]
    if _ldpath := env.get("LD_LIBRARY_PATH"):
        paths += _ldpath
    env["LD_LIBRARY_PATH"] = ":".join(paths)
    return env


def subprocess_empty_env(cmd: list[str]) -> bool:
    """Run the given command in a cleaned environment (dropping AppImage/PyInstaller
    libs).

    Returns True if the process ran successfully (exit code 0), False otherwise.
    """
    # Copy the current env and remove variables that point to bundled libs
    env = os.environ.copy()
    for var in ("LD_LIBRARY_PATH", "APPDIR", "PYINSTALLER_APPDIR"):
        env.pop(var, None)

    try:
        subprocess.run(cmd, check=True, env=env)
        return True
    except Exception:
        return False


def webopen(url: str) -> bool:
    """Cross-platform URL opener with honest success/fail.

    - On Linux: tries system helpers (xdg-open, gio, gvfs-open) in a clean env;
      falls back to webbrowser.open() if none succeed.
    - On others: uses webbrowser.open() directly.

    Returns True if any launcher was successfully invoked, False otherwise.
    """
    if sys.platform.lower().startswith("linux"):
        helpers = [
            "/usr/bin/xdg-open",  # absolute path first
            "xdg-open",
            "gio",
            "gvfs-open",
        ]
        for helper in helpers:
            # resolve helper to an executable path
            path = helper if os.path.isabs(helper) else shutil.which(helper)
            if not path:
                continue
            if subprocess_empty_env([path, url]):
                return True
        # fallback to stdlib
        return webbrowser.open(url)

    # if sys.platform == "darwin":
    #     if subprocess_empty_env(["open", url]):
    #         return True
    #     return webbrowser.open(url)

    # other platforms
    return webbrowser.open(url)


def open_mailto_link(mailto_link: str) -> None:
    "Attempt opening the mailto link with the OS's default email client"
    if sys.platform.startswith("linux"):
        # Linux: Use xdg-open to handle the mailto link
        subprocess.run(["xdg-open", mailto_link], check=True, env=linux_env())
    elif sys.platform.startswith("darwin"):
        # macOS: Use open command to handle the mailto link
        subprocess.run(["open", mailto_link], check=True)
    elif sys.platform == "win32":
        # Windows: Use shell execute to handle the mailto link without invoking a shell
        os.startfile(mailto_link)


def xdg_open_file(filename: Path, is_text_file=False):
    """Xdg open file."""
    system_name = platform.system()
    if sys.platform == "win32":
        if is_text_file:
            subprocess.run(["notepad", str(filename)], check=False)
        else:
            os.startfile(str(filename))
    elif system_name == "Darwin":  # macOS
        subprocess.call(shlex.split(f'open "{filename}"'))
    elif system_name == "Linux":  # Linux
        subprocess.call(shlex.split(f'xdg-open "{filename}"'), env=linux_env())


def show_file_in_explorer(filename: Path) -> None:
    """Show file in explorer."""
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", filename])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", filename])
        else:  # Linux
            desktop_session = os.environ.get("XDG_CURRENT_DESKTOP")
            if desktop_session and "KDE" in desktop_session:
                # Attempt to use Dolphin to select the file
                subprocess.Popen(["dolphin", "--select", filename], env=linux_env())
            else:
                # Fallback for other environments or if the detection is uncertain
                subprocess.Popen(["xdg-open", filename.parent], env=linux_env())
    except Exception as e:
        print(f"Error opening file: {e}")
