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
import logging

from bitcoin_safe.signature_manager import FilenameInfo

logger = logging.getLogger(__name__)


def test_name_splitting_sparrow():
    """Test name splitting sparrow."""
    filename = "Sparrow-2.0.0-aarch64.dmg"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Sparrow', extension='dmg', version='2.0.0', architecture='aarch64', extra_info=None)"
    )

    filename = "Sparrow-2.0.0.msi"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Sparrow', extension='msi', version='2.0.0', architecture=None, extra_info=None)"
    )

    filename = "Sparrow-2.0.0.zip"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Sparrow', extension='zip', version='2.0.0', architecture=None, extra_info=None)"
    )

    filename = "sparrow_2.0.0-1_amd64.deb"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow', extension='deb', version='2.0.0', architecture='amd64', extra_info='1')"
    )

    filename = "sparrow-2.0.0-1.x86_64.rpm"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow', extension='rpm', version='2.0.0', architecture='x86_64', extra_info='1')"
    )

    filename = "sparrow-2.0.0-x86_64.tar.gz"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow', extension='gz', version='2.0.0', architecture='x86_64', extra_info='tar')"
    )

    filename = "sparrow_2.0.0-1_arm64.deb"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow', extension='deb', version='2.0.0', architecture='arm64', extra_info='1')"
    )

    filename = "sparrow-2.0.0-1.aarch64.rpm"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow', extension='rpm', version='2.0.0', architecture='aarch64', extra_info='1')"
    )

    filename = "sparrow-2.0.0-aarch64.tar.gz"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow', extension='gz', version='2.0.0', architecture='aarch64', extra_info='tar')"
    )

    filename = "sparrow-2.0.0-manifest.txt.asc"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow', extension='asc', version='2.0.0', architecture=None, extra_info='manifest.txt')"
    )

    filename = "sparrow-2.0.0-manifest.txt"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow', extension='txt', version='2.0.0', architecture=None, extra_info='manifest')"
    )

    filename = "sparrow-server-2.0.0-1.x86_64.rpm"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='sparrow-server', extension='rpm', version='2.0.0', architecture='x86_64', extra_info='1')"
    )


def test_name_bitcoin_safe():
    """Test name bitcoin safe."""
    filename = "Bitcoin-Safe-1.0.0b4-portable.exe"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Bitcoin-Safe', extension='exe', version='1.0.0b4', architecture=None, extra_info='portable')"
    )

    filename = "Bitcoin-Safe-1.0.0b4-setup.exe"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Bitcoin-Safe', extension='exe', version='1.0.0b4', architecture=None, extra_info='setup')"
    )

    for arch in ["arm64", "x86_64"]:
        filename = f"Bitcoin-Safe-1.0.0b4_{arch}-setup.exe"
        info = FilenameInfo.from_filename(filename)
        assert info.app_name == "Bitcoin-Safe"
        assert info.version == "1.0.0b4"
        assert info.architecture == arch
        assert info.extra_info == "setup"

    filename = "Bitcoin-Safe-1.0.3-x86_64.AppImage"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Bitcoin-Safe', extension='AppImage', version='1.0.3', architecture='x86_64', extra_info=None)"
    )

    filename = "Bitcoin-Safe_11.022.333beta3-x86_64_extra_info.AppImage"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Bitcoin-Safe', extension='AppImage', version='11.022.333beta3', architecture='x86_64', extra_info='extra_info')"
    )

    filename = "Bitcoin-Safe_11.022.333beta3-x86_64.AppImage"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Bitcoin-Safe', extension='AppImage', version='11.022.333beta3', architecture='x86_64', extra_info=None)"
    )

    filename = "Bitcoin-Safe-1.0.3.dmg"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='Bitcoin-Safe', extension='dmg', version='1.0.3', architecture=None, extra_info=None)"
    )


def test_name_splitting_linux_packages():
    """Test name splitting linux packages."""
    filename = "libreoffice-qt6-7.6.7.2-r0.apk"
    info = FilenameInfo.from_filename(filename)
    assert (
        str(info)
        == "FilenameInfo(app_name='libreoffice-qt6', extension='apk', version='7.6.7.2', architecture=None, extra_info='r0')"
    )
