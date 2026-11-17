#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
#

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from .release_archive import extract_verified


@pytest.mark.parametrize("name, member_type", [("../escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)])
def test_rejects_unsafe_tar_members(tmp_path: Path, name: str, member_type: bytes) -> None:
    archive = tmp_path / "test.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo(name)
        member.type = member_type
        member.linkname = "../escape" if member_type == tarfile.SYMTYPE else ""
        member.size = 1 if member_type == tarfile.REGTYPE else 0
        output.addfile(member, io.BytesIO(b"x") if member.size else None)
    with pytest.raises(ValueError):
        extract_verified(archive, tmp_path / "out")
    assert not (tmp_path / "escape").exists()
