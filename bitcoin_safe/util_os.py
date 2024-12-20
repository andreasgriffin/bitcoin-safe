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


import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

# do not import logging, because has this a dependency for setup_logging


def open_mailto_link(mailto_link: str) -> None:
    "Attempt opening the mailto link with the OS's default email client"
    if sys.platform.startswith("linux"):
        # Linux: Use xdg-open to handle the mailto link
        subprocess.run(["xdg-open", mailto_link], check=True)
    elif sys.platform.startswith("darwin"):
        # macOS: Use open command to handle the mailto link
        subprocess.run(["open", mailto_link], check=True)
    elif sys.platform.startswith("win32"):
        # Windows: Use start command to handle the mailto link
        subprocess.run(["cmd", "/c", "start", "", mailto_link], check=True, shell=True)


def xdg_open_file(filename: Path, is_text_file=False):
    system_name = platform.system()
    if system_name == "Windows":
        if is_text_file:
            subprocess.call(shlex.split(f'start notepad "{filename}"'), shell=True)
        else:
            subprocess.call(shlex.split(f'start "" /max "{filename}"'), shell=True)
    elif system_name == "Darwin":  # macOS
        subprocess.call(shlex.split(f'open "{filename}"'))
    elif system_name == "Linux":  # Linux
        subprocess.call(shlex.split(f'xdg-open "{filename}"'))


def show_file_in_explorer(filename: Path) -> None:
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", filename])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", filename])
        else:  # Linux
            desktop_session = os.environ.get("XDG_CURRENT_DESKTOP")
            if desktop_session and "KDE" in desktop_session:
                # Attempt to use Dolphin to select the file
                subprocess.Popen(["dolphin", "--select", filename])
            else:
                # Fallback for other environments or if the detection is uncertain
                subprocess.Popen(["xdg-open", filename.parent])
    except Exception as e:
        print(f"Error opening file: {e}")
