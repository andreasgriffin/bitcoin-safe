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


import argparse
import datetime
import getpass
import hashlib
import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from bitcoin_safe.execute_config import ENABLE_THREADING, ENABLE_TIMERS, IS_PRODUCTION

assert IS_PRODUCTION
assert ENABLE_THREADING
assert ENABLE_TIMERS


def get_default_description(latest_tag: str):
    return f"""
### New Features

- 

### Improvements

- 


### 🔋Batteries included🔋
Lots of existing features were not mentioned above, so please check out:

- [Why choose Bitcoin Safe?](https://bitcoin-safe.org/en/features/usps/)
- www.bitcoin-safe.org
- [Readme](https://github.com/andreasgriffin/bitcoin-safe?tab=readme-ov-file#bitcoin-safe) and [Comprehensive Feature List](https://github.com/andreasgriffin/bitcoin-safe?tab=readme-ov-file#comprehensive-feature-list)
- Follow me on [nostr](https://primal.net/p/npub1q67f4d7qdja237us384ryeekxsz88lz5kaawrcynwe4hqsnufr6s27up0e)


####  Verify signature

Import my [public key](https://keys.openpgp.org/vks/v1/by-fingerprint/2759AA7148568ECCB03B76301D82124B440F612D) and verify the signature with:
```bash
gpg --import 2759AA7148568ECCB03B76301D82124B440F612D.asc
gpg --verify Bitcoin-Safe-{latest_tag}-x86_64.AppImage.asc
```

"""


# the following is taken out from the release notes, since the pip package still requires installing system libraries
# #### Install and run on Mac, Linux, or Windows
# using the [python package ](https://pypi.org/project/bitcoin-safe/)
# ```bash
# python3 -m pip install bitcoin-safe
# python3 -m bitcoin_safe
# ```


def run_pytest() -> None:
    """
    Run pytest to execute all unit tests in the project.
    Aborts the script if any tests fail.
    """
    try:
        # Run pytest and capture the output
        result = subprocess.run(["pytest"], check=True, text=True, capture_output=True)
        print("Pytest Output:\n", result.stdout)
    except subprocess.CalledProcessError as e:
        # If pytest fails, print the output and abort the script
        print("Pytest failed with errors:")
        print(e.stdout)
        sys.exit("Stopping script due to failed tests.")


def get_git_tag() -> str:
    """Fetch the tag from the git repository."""
    return subprocess.check_output(["git", "describe", "--tags", "--dirty", "--always"]).decode().strip()


def get_checkout_main():
    try:
        # Retrieve the list of remotes and their URLs
        result = subprocess.run(["git", "checkout", "main"], check=True, text=True, capture_output=True)
        return
    except subprocess.CalledProcessError as e:
        print(f"Failed to checkout main: {e}")
        return None


def get_default_remote():
    try:
        # Retrieve the list of remotes and their URLs
        result = subprocess.run(["git", "remote", "-v"], check=True, text=True, capture_output=True)
        remote_info = result.stdout.splitlines()

        # Parse the first remote name from the output
        default_remote = remote_info[0].split()[0]
        return default_remote
    except subprocess.CalledProcessError as e:
        print(f"Failed to retrieve remote information: {e}")
        return None


def add_and_publish_git_tag(tag):
    try:

        # Add the tag
        subprocess.run(["git", "tag", tag], check=True)

        # Get the default remote name
        remote_name = get_default_remote()
        if remote_name:
            # Push the tag to the default remote
            print(f"Tag '{tag}' pushing to remote '{remote_name}'")
            subprocess.run(["git", "push", remote_name, tag], check=True)
            print(f"Tag '{tag}' successfully pushed to remote '{remote_name}'")
        else:
            print("Could not determine default remote.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to push tag '{tag}': {e}")


def create_pypi_wheel(dist_dir="dist") -> Tuple[str, str]:
    """_summary_

    Returns:
        Tuple[str, str]: (whl_file, hash_value)
    """

    def run_poetry_build():
        # Run `poetry build`
        subprocess.run(["poetry", "build"], check=True)

    def get_whl_file():
        # Locate the .whl file in the dist directory
        for filename in os.listdir(dist_dir):
            if filename.endswith(".whl"):
                return os.path.join(dist_dir, filename)
        return None

    def calculate_sha256(file_path):
        # Calculate the SHA-256 hash of the file
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(partial(f.read, 4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    run_poetry_build()

    whl_file = get_whl_file()
    if not whl_file:
        raise Exception("No .whl file found in the dist directory.")

    hash_value = calculate_sha256(whl_file)
    pip_install_command = f"pip install {Path(dist_dir)/whl_file} --hash=sha256:{hash_value}"
    print(pip_install_command)
    return whl_file, hash_value


def publish_pypi_wheel(dist_dir="dist"):
    whl_file, hash_value = create_pypi_wheel(dist_dir=dist_dir)
    subprocess.run(["poetry", "publish"], check=True)


def create_github_release(
    token: str,
    owner: str,
    repo: str,
    tag_name: str,
    release_name: str,
    body: str,
    draft: bool = False,
    prerelease: bool = False,
) -> Dict[str, Any]:
    """Create a release on GitHub using the GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {
        "tag_name": tag_name,
        "name": release_name,
        "body": body,
        "draft": draft,
        "prerelease": prerelease,
    }
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    return response.json()


def upload_release_asset(
    token: str, owner: str, repo: str, release_id: int, asset_path: Path
) -> Dict[str, Any]:
    """Upload an asset to an existing GitHub release."""
    headers = {"Authorization": f"token {token}", "Content-Type": "application/octet-stream"}
    params = {"name": asset_path.name}
    url = f"https://uploads.github.com/repos/{owner}/{repo}/releases/{release_id}/assets"
    with asset_path.open("rb") as asset_file:
        response = requests.post(url, headers=headers, params=params, data=asset_file)
    return response.json()


def list_directory_files(directory: Path) -> List[Tuple[Path, int, str]]:
    """List all files in a directory with their sizes and modification dates."""
    files = []
    for filepath in directory.iterdir():
        if filepath.is_file():
            size = filepath.stat().st_size
            modified_time = datetime.datetime.fromtimestamp(filepath.stat().st_mtime)
            files.append((filepath, size, modified_time.strftime("%Y-%m-%d %H:%M:%S")))
    return files


def get_input_with_default(prompt: str, default: str = "") -> str:
    """
    Get user input with the option to use a default value by pressing enter.
    If no default is provided, just press enter to provide an empty string.

    Args:
    prompt (str): The prompt to display to the user.
    default (Optional[str]): The default value that can be accepted by pressing enter.

    Returns:
    str: The user input or the default value if the user inputs nothing.
    """
    # Adjust the prompt based on whether a default value is provided
    user_input = input(f"{prompt} (default: {default}): ")
    # Return the user input or the default if the input is empty and a default is specified
    return user_input if user_input else default


RELEASE_INSTRUCTIONS = """
1. Manually create a git tag
2. Build all artifacts
3. Sign all artifacts (build.py --sign)
4. release.py (will also create and publish a pypi package)
5. Manually update the description of the release and click publish
"""


def parse_args() -> argparse.Namespace:

    parser = argparse.ArgumentParser(description="Release Bitcoin Safe")
    parser.add_argument("--more_help", action="store_true", help=RELEASE_INSTRUCTIONS)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.more_help:
        print(RELEASE_INSTRUCTIONS)
        return

    get_checkout_main()

    print("Running tests before proceeding...")
    run_pytest()

    owner = "andreasgriffin"
    repo = "bitcoin-safe"

    from bitcoin_safe import __version__

    git_tag: Optional[str] = get_git_tag()

    if get_input_with_default(f"Is this version {__version__} correct? (y/n): ", "y").lower() != "y":
        return

    if git_tag != __version__:
        print(f"Error: Git tag {git_tag} != {__version__}")
        return
        # add_and_publish_git_tag(__version__)

    directory = Path("dist")
    files = list_directory_files(directory)
    print("Files to be uploaded:")
    for file_path, size, modified_time in files:
        print(f"  {file_path.name} - {size} bytes, last modified: {modified_time}")

    if not get_input_with_default("Are these the correct files to upload? (y/n): ", "y").lower() == "y":
        print("Asset upload aborted.")
        return

    release_name = get_input_with_default("Enter the release name", f"{__version__}")
    body = get_default_description(latest_tag=__version__)
    draft = get_input_with_default("Is this a draft release?", "y").lower() == "y"
    prerelease = get_input_with_default("Is this a prerelease?", "n").lower() == "y"
    token = getpass.getpass("Enter your GitHub token: ")
    release_result = create_github_release(
        token, owner, repo, __version__, release_name, body, draft, prerelease
    )
    print("Release created successfully:", json.dumps(release_result, indent=2))

    for file_path, _, _ in files:
        if __version__ not in file_path.name:
            continue
        upload_release_asset(token, owner, repo, release_result["id"], file_path)
        print(f"Asset {file_path.name} uploaded successfully.")

    if get_input_with_default("Publish pypi package? (y/n): ", "y").lower() == "y":
        publish_pypi_wheel(dist_dir=str(directory))

    print("Update features in \n    https://github.com/thebitcoinhole/software-wallets")


if __name__ == "__main__":
    main()
