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

from bitcoin_safe.config import UserConfig


def test_app_lock_password_roundtrip() -> None:
    config = UserConfig()
    config.set_app_lock_password("top-secret")

    assert config.has_app_lock_password()
    assert config.verify_app_lock_password("top-secret")
    assert not config.verify_app_lock_password("wrong")

    loaded = UserConfig.from_dump(config.dump())
    assert loaded.has_app_lock_password()
    assert loaded.verify_app_lock_password("top-secret")
    assert not loaded.verify_app_lock_password("wrong")

    assert loaded.app_lock_password_hash is not None
    assert loaded.app_lock_password_hash != ""


def test_app_lock_password_uses_random_salt() -> None:
    config_a = UserConfig()
    config_b = UserConfig()

    config_a.set_app_lock_password("top-secret")
    config_b.set_app_lock_password("top-secret")

    assert config_a.app_lock_password_hash
    assert config_b.app_lock_password_hash
    assert config_a.app_lock_password_hash != config_b.app_lock_password_hash
    assert config_a.verify_app_lock_password("top-secret")
    assert config_b.verify_app_lock_password("top-secret")


def test_app_lock_password_clear() -> None:
    config = UserConfig()
    config.set_app_lock_password("top-secret")

    config.set_app_lock_password(None)

    assert not config.has_app_lock_password()
    assert not config.verify_app_lock_password("top-secret")
