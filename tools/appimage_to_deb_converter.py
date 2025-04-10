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
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class Appimage2debConverter:
    def __init__(
        self,
        appimage,
        package_name,
        version="1.0.0",
        maintainer="Your Name <you@example.com>",
        architecture="amd64",
        description="Converted AppImage package",
        homepage="https://example.com",
        output_deb=None,
        depends="",
        desktop_name=None,
        desktop_icon_name="",
        desktop_categories="Utility",
    ):
        self.appimage = Path(appimage).resolve()
        if not self.appimage.is_file():
            raise FileNotFoundError(f"AppImage file '{self.appimage}' not found.")
        self.package_name = package_name
        self.version = version
        self.maintainer = maintainer
        self.architecture = architecture
        self.description = description
        self.homepage = homepage
        self.depends = depends
        # If no output filename is provided, use the AppImage base name with a .deb extension.
        self.output_deb = (
            Path(output_deb).resolve() if output_deb else self.appimage.with_suffix(".deb").resolve()
        )
        # Desktop entry defaults:
        self.desktop_name = desktop_name if desktop_name is not None else package_name
        self.desktop_icon_name = desktop_icon_name
        self.desktop_categories = desktop_categories

    def _extract_appimage(self, extract_dir: Path) -> Path:
        # Ensure the AppImage is executable.
        if not os.access(str(self.appimage), os.X_OK):
            self.appimage.chmod(0o755)
        # Extract the AppImage contents using its built-in extractor.
        result = subprocess.run([str(self.appimage), "--appimage-extract"], cwd=str(extract_dir))
        if result.returncode != 0:
            raise Exception("Failed to extract the AppImage.")
        extracted_folder = extract_dir / "squashfs-root"
        if not extracted_folder.exists():
            raise Exception("Extraction failed: 'squashfs-root' not found.")

        # Set timestamps using the find command and touch.
        # Prepare environment with TZ set to UTC
        env = os.environ.copy()
        env["TZ"] = "UTC"
        find_command = [
            "find",
            str(extracted_folder),
            "-exec",
            "touch",
            "-h",
            "-d",
            "2000-11-11T11:11:11+00:00",
            "{}",
            "+",
        ]
        subprocess.run(find_command, check=True)

        return extracted_folder

    def _create_deb_structure(self, package_root: Path, extracted_folder: Path) -> None:
        # Create required directories for the Debian package.
        debian_dir = package_root / "DEBIAN"
        target_dir = package_root / "opt" / self.package_name
        debian_dir.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        # Copy the extracted AppImage contents into /opt/<package_name>.
        shutil.copytree(str(extracted_folder), str(target_dir), dirs_exist_ok=True, symlinks=True)

    def _create_control_file(self, debian_dir: Path) -> None:
        # Build the control file content line by line.
        lines = [
            f"Package: {self.package_name}",
            f"Version: {self.version}",
            "Section: base",
            "Priority: optional",
            f"Architecture: {self.architecture}",
            f"Maintainer: {self.maintainer}",
            f"Homepage: {self.homepage}",
            f"Depends: {self.depends}",
            f"Description: {self.description}",
        ]
        control_content = "\n".join(lines) + "\n"
        (debian_dir / "control").write_text(control_content)

    def _create_preinst_script(self, debian_dir: Path) -> None:
        """
        Creates a pre-installation script that purges /opt/{package_name}.
        """
        preinst_path = debian_dir / "preinst"
        preinst_content = "#!/bin/sh\n" "set -e\n" f"rm -rf /opt/{self.package_name}\n" "exit 0\n"
        preinst_path.write_text(preinst_content)
        # Mark the script as executable.
        os.chmod(preinst_path, 0o755)

    def _create_postrm_script(self, debian_dir: Path) -> None:
        """
        Creates a post-removal script that removes all files in /opt/{package_name}.
        """
        postrm_path = debian_dir / "postrm"
        postrm_content = "#!/bin/sh\n" "set -e\n" f"rm -rf /opt/{self.package_name}\n" "exit 0\n"
        postrm_path.write_text(postrm_content)
        os.chmod(postrm_path, 0o755)

    def _create_desktop_file(self, package_root: Path) -> None:
        # Create the directory for desktop entries.
        applications_dir = package_root / "usr" / "share" / "applications"
        applications_dir.mkdir(parents=True, exist_ok=True)
        desktop_file_path = applications_dir / f"{self.package_name}.desktop"

        # Determine the Exec command:
        # If /opt/<package-name>/AppRun exists, use it; otherwise, fallback to /opt/<package-name>/<package-name>
        target_dir = package_root / "opt" / self.package_name
        if (target_dir / "AppRun").exists():
            desktop_exec = f"/opt/{self.package_name}/AppRun"
        else:
            desktop_exec = f"/opt/{self.package_name}/{self.package_name}"

        lines = [
            "[Desktop Entry]",
            f"Version={self.version}",
            "Type=Application",
            f"Name={self.desktop_name}",
            f"Comment={self.description}",
            f"Exec={desktop_exec}",
        ]
        if self.desktop_icon_name:
            lines.append(f"Icon=/opt/{self.package_name}/{self.desktop_icon_name}")
        lines.extend(["Terminal=false", f"Categories={self.desktop_categories}"])
        desktop_content = "\n".join(lines) + "\n"
        desktop_file_path.write_text(desktop_content)

    def _build_deb(self, package_root: Path) -> None:
        result = subprocess.run(["dpkg-deb", "--build", str(package_root), str(self.output_deb)])
        if result.returncode != 0:
            raise Exception("Failed to build the deb package.")

    def convert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            print("Extracting AppImage...")
            extracted_folder = self._extract_appimage(temp_dir_path)
            print("Extraction complete.")

            package_root = temp_dir_path / "deb_package"
            package_root.mkdir(parents=True, exist_ok=True)

            print("Creating deb package structure...")
            self._create_deb_structure(package_root, extracted_folder)

            debian_dir = package_root / "DEBIAN"
            self._create_control_file(debian_dir)

            print("Creating preinst script...")
            self._create_preinst_script(debian_dir)

            print("Creating postrm script...")
            self._create_postrm_script(debian_dir)

            print("Creating desktop entry...")
            self._create_desktop_file(package_root)

            print("Building deb package...")
            self._build_deb(package_root)
            print(f"Deb package created at {self.output_deb}")


# Command-line interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert an AppImage to a deb package using Appimage2debConverter."
    )
    parser.add_argument("appimage", help="Path to the AppImage file.")
    parser.add_argument("--package-name", required=True, help="Name of the package.")
    parser.add_argument("--version", default="1.0.0", help="Package version.")
    parser.add_argument("--maintainer", default="Your Name <you@example.com>", help="Package maintainer.")
    parser.add_argument("--architecture", default="amd64", help="Target architecture (e.g., amd64).")
    parser.add_argument("--description", default="Converted AppImage package", help="Package description.")
    parser.add_argument("--homepage", default="https://example.com", help="Project homepage URL.")
    parser.add_argument(
        "--output-filename",
        help="Output deb file name. If not specified, it is derived from the AppImage filename.",
    )
    parser.add_argument(
        "--depends", default="", help="Comma-separated list of package dependencies (default is empty)."
    )
    parser.add_argument(
        "--desktop-name", default=None, help="Name for the desktop entry (defaults to package name)."
    )
    parser.add_argument(
        "--desktop-icon", default="", help="Path to an icon file for the desktop entry (optional)."
    )
    parser.add_argument("--desktop-categories", default="Utility", help="Categories for the desktop entry.")
    args = parser.parse_args()

    converter = Appimage2debConverter(
        appimage=args.appimage,
        package_name=args.package_name,
        version=args.version,
        maintainer=args.maintainer,
        architecture=args.architecture,
        description=args.description,
        homepage=args.homepage,
        output_deb=args.output_filename,
        depends=args.depends,
        desktop_name=args.desktop_name,
        desktop_icon_name=args.desktop_icon,
        desktop_categories=args.desktop_categories,
    )
    converter.convert()
