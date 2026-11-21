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

"""Read-only H2 2.1 FileEncrypt/XTS password check (no JDBC and no disk output).

Matches H2 2.1.214 FileEncrypt.java / XTS.java. Only decrypts the first
4096-byte MVStore block, to verify that a supplied derived H2 password opens
an encrypted database. This DOES NOT parse Sparrow's wallet tables.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .model import ExchangeError
from .sparrow_h2 import sparrow_h2_file_password


def _aes_block(key: bytes, block: bytes, decrypt: bool = False) -> bytes:
    c = Cipher(algorithms.AES(key), modes.ECB())
    ctx = c.decryptor() if decrypt else c.encryptor()
    return ctx.update(block) + ctx.finalize()


def _xts_decrypt_first_sector(key: bytes, ciphertext: bytes) -> bytes:
    if len(ciphertext) != 4096:
        raise ExchangeError("Invalid H2 first sector length")
    tweak = bytearray(_aes_block(key, bytes(16)))
    plain = bytearray()
    for start in range(0, 4096, 16):
        chunk = bytes(a ^ b for a, b in zip(ciphertext[start : start + 16], tweak, strict=True))
        chunk = _aes_block(key, chunk, decrypt=True)
        plain.extend(a ^ b for a, b in zip(chunk, tweak, strict=True))
        carry = 0
        for j in range(16):
            out = (tweak[j] << 1) + carry
            tweak[j] = out & 255
            carry = out >> 8
        if carry:
            tweak[0] ^= 0x87
    return bytes(plain)


def verify_sparrow_h2_password(path: str | Path, password: str) -> bool:
    """True only when H2's AES block decrypts to an H2 MVStore header.

    Checks the *actual H2 data*, not just an Argon2 output. No secret material
    from the file is returned, written to disk, or included in an exception.
    """
    with Path(path).open("rb") as fp:
        header = fp.read(4096)
        encrypted_sector = fp.read(4096)
    if len(header) < 4096 or len(encrypted_sector) != 4096 or not header.startswith(b"H2encrypt\n"):
        raise ExchangeError("Not a Sparrow encrypted H2 file")
    derived = sparrow_h2_file_password(header, password)
    key = hashlib.pbkdf2_hmac("sha256", derived.encode("utf-16-be"), header[10:18], 10, dklen=16)
    plain = _xts_decrypt_first_sector(key, encrypted_sector)
    if not plain.startswith(b"H:2,"):
        raise ExchangeError("Incorrect Sparrow H2 password or corrupt database header")
    return True
