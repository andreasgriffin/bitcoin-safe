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

import enum
import json
import logging
import os

# from https://stackoverflow.com/questions/2490334/simple-way-to-encode-a-string-according-to-a-password
import secrets
from abc import abstractmethod
from base64 import urlsafe_b64decode as b64d
from base64 import urlsafe_b64encode as b64e
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

import bdkpython as bdk
from bitcoin_safe_lib.util import time_logger
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing_extensions import Self

from .util import fast_version

T = TypeVar("T")

logger = logging.getLogger(__name__)


def varnames(method: Callable) -> Iterable[str]:
    """Varnames."""
    return method.__code__.co_varnames[: method.__code__.co_argcount]


def filtered_dict(d: dict, allowed_keys: Iterable[str]) -> dict:
    """Filtered dict."""
    return {k: v for k, v in d.items() if k in allowed_keys}


def filtered_for_init(d: dict, cls: type[T]) -> dict:
    """Filtered for init."""
    return filtered_dict(d, varnames(cls.__init__))


class Encrypt:
    def _derive_key(self, password: bytes, salt: bytes, iterations: int) -> bytes:
        """Derive a secret key from a given password and salt."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA512(),
            length=32,
            salt=salt,
            iterations=iterations,
            backend=default_backend(),
        )
        return b64e(kdf.derive(password))

    def password_encrypt(self, message: bytes, password: str, iterations: int = 100_000) -> bytes:
        """Password encrypt."""
        salt = secrets.token_bytes(16)
        key = self._derive_key(password.encode(), salt, iterations)
        return b64e(
            b"%b%b%b"
            % (
                salt,
                iterations.to_bytes(4, "big"),
                b64d(Fernet(key).encrypt(message)),
            )
        )

    def password_decrypt(self, token: bytes, password: str) -> bytes:
        """Password decrypt."""
        decoded = b64d(token)
        salt, iter, token = decoded[:16], decoded[16:20], b64e(decoded[20:])
        iterations = int.from_bytes(iter, "big")
        if iterations > 1e6:
            raise Exception("Error in decrypting")
        key = self._derive_key(password.encode(), salt, iterations)
        return Fernet(key).decrypt(token)


class Storage:
    def __init__(self) -> None:
        """Initialize instance."""
        self.encrypt = Encrypt()

    def save(self, message: str, filename: str, password: str | None = None) -> None:
        """Save."""
        token = self.encrypt.password_encrypt(message.encode(), password) if password else message.encode()

        with open(filename, "wb") as f:
            f.write(token)

    @classmethod
    def has_password(cls, filename: str) -> bool:
        """Has password."""
        with open(filename, "rb") as f:
            token = f.read()

        # WHITESPACE contains all standard ASCII whitespace bytes:
        #  - space        (0x20)
        #  - tab          (\t)
        #  - newline      (\n)
        #  - carriage rtn (\r)
        #  - form feed    (\f)
        #  - vertical tab (\v)
        strip_char = b" \t\n\r\f\v"
        try:
            if token.lstrip(strip_char).startswith(b"{") and token.rstrip(strip_char).endswith(b"}"):
                return False
        except Exception as e:
            logger.exception(str(e))
            return True

        return True

    def load(self, filename: str, password: str | None = None) -> str:
        """Load."""
        with open(filename, "rb") as f:
            token = f.read()

        if not password:
            logger.debug(f"Opening {filename} without password")
            return token.decode()
        else:
            logger.debug(f"Decrypting {filename}")
            return self.encrypt.password_decrypt(token, password).decode()


class ClassSerializer:
    @classmethod
    def general_deserializer(cls, known_classes, class_kwargs) -> Callable:
        """General deserializer."""

        def deserializer(dct: dict) -> dict:
            """Deserializer."""
            cls_string = dct.get("__class__")  # e.g. KeyStore
            if cls_string:
                if cls_string in known_classes:
                    obj_cls = known_classes.get(cls_string)
                    if hasattr(obj_cls, "from_dump"):  # is there KeyStore.from_dump ?
                        if class_kwargs.get(cls_string):  #  apply additional arguments to the class from_dump
                            dct.update(class_kwargs.get(cls_string))
                        return obj_cls.from_dump(
                            dct, class_kwargs=class_kwargs
                        )  # do: KeyStore.from_dump(**dct)
                    else:
                        raise Exception(f"{obj_cls} doesnt have a from_dump classmethod.")
                else:
                    dct.clear()
                    logger.error(
                        f"{cls_string} not in known_classes {known_classes}. "
                        f"The {cls_string} data will be dropped."
                    )
                    logger.debug(
                        f"""{cls_string} not in known_classes {known_classes}."""
                        """Did you add the following to the child class?
                                            VERSION = "0.0.1"
                                            known_classes = {
                                                **BaseSaveableClass.known_classes,
                                            }"""
                        f"""And did you add
                                       "cls_string":{cls_string}
                                       to the parent BaseSaveableClass ?"""
                    )
            elif dct.get("__enum__"):
                obj_cls = known_classes.get(dct["name"])
                if obj_cls and hasattr(obj_cls, dct["value"]):
                    return getattr(obj_cls, dct["value"])
                else:
                    logger.exception(f"Could not deserialize {obj_cls}({dct.get('value')}).")

            # For normal cases, json.loads will handle default JSON data types
            # No need to use json.Decoder here, just return the dictionary as-is
            return dct

        return deserializer

    @classmethod
    def general_serializer(cls, obj):
        """General serializer."""
        if isinstance(obj, enum.Enum):
            return {"__enum__": True, "name": obj.__class__.__name__, "value": obj.name}
        if isinstance(obj, BaseSaveableClass):
            return obj.dump()
        # Fall back to the default JSON serializer
        return json.JSONEncoder().default(obj)


class BaseSaveableClass:
    known_classes: dict[str, Any] = {"Network": bdk.Network}
    VERSION = "0.0.0"
    _version_from_dump: str | None = None

    @staticmethod
    def cls_kwargs(*args, **kwargs):
        return {}

    @abstractmethod
    def dump(self) -> dict:
        "Returns the dict"
        d = {}
        d["__class__"] = self.__class__.__name__
        d["VERSION"] = self.VERSION
        return d

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]):
        """From dump migration."""
        cls._version_from_dump = dct["VERSION"]

        # now the version is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    @classmethod
    def from_dump_downgrade_migration(cls, dct: dict[str, Any]):
        "this class can be overwritten in child classes"
        return dct

    @classmethod
    def _from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        """From dump."""
        assert dct.get("__class__") == cls.__name__
        del dct["__class__"]

        if fast_version(cls.VERSION) < fast_version(str(dct.get("VERSION", 0))):
            dct = cls.from_dump_downgrade_migration(dct)

        if fast_version(cls.VERSION) > fast_version(str(dct.get("VERSION", 0))):
            dct = cls.from_dump_migration(dct)

        if "VERSION" in dct:
            del dct["VERSION"]

        if class_kwargs:
            dct.update(class_kwargs)

    @classmethod
    @abstractmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None) -> Self:
        """From dump."""
        raise NotImplementedError()

    def clone(self, class_kwargs: dict | None = None) -> Self:
        """Clone."""
        return self._from_dumps(self.dumps(), class_kwargs=class_kwargs)

    @time_logger
    def save(self, filename: Path | str, password: str | None = None):
        "Saves the json dumps to a file"
        directory = os.path.dirname(str(filename))
        # Create the directories
        if directory:
            os.makedirs(directory, exist_ok=True)

        storage = Storage()
        storage.save(
            self.dumps(),
            str(filename),
            password=password,
        )

    # def __str__(self) -> str:
    #     return self.dumps()

    def dumps(self, indent=None) -> str:
        "Returns the json representation (recursively)"
        return json.dumps(
            self,
            default=ClassSerializer.general_serializer,
            indent=indent,
            sort_keys=True,
        )

    @staticmethod
    def _flatten_known_classes(known_classes: dict[str, Any]) -> dict[str, Any]:
        "Recursively extends the dict to includes all known_classes of known_classes"
        known_classes = known_classes.copy()
        for known_class in list(known_classes.values()):
            if issubclass(known_class, BaseSaveableClass):
                known_classes.update(BaseSaveableClass._flatten_known_classes(known_class.known_classes))
        return known_classes

    @classmethod
    def get_known_classes(cls) -> dict[str, Any]:
        "Gets a flattened list of known classes that a json deserializer needs to interpet all objects"
        return BaseSaveableClass._flatten_known_classes({cls.__name__: cls})

    @classmethod
    @time_logger
    def _from_dumps(cls, json_string: str, class_kwargs: dict | None = None):
        return json.loads(
            json_string,
            object_hook=ClassSerializer.general_deserializer(
                cls.get_known_classes(), class_kwargs=class_kwargs if class_kwargs else {}
            ),
        )

    @classmethod
    @time_logger
    def _from_file(cls, filename: str, password: str | None = None, class_kwargs: dict | None = None):
        """Loads the class from a file. This offers the option of add class_kwargs args.

        Args:
            filename (str): _description_
            password (Optional[str], optional): _description_. Defaults to None.
            class_kwargs (_type_, optional):
                example:
                    class_kwargs= {'Wallet':{'config':config}}.
                Defaults to None.

        Returns:
            _type_: _description_
        """
        storage = Storage()
        json_string = cls.file_migration(storage.load(filename, password=password))
        return cls._from_dumps(json_string=json_string, class_kwargs=class_kwargs)

    @classmethod
    def file_migration(cls, file_content: str):
        "this class can be overwritten in child classes"
        return file_content


class SaveAllClass(BaseSaveableClass):
    def dump(self):
        """Dump."""
        d = super().dump()
        d.update(self.__dict__.copy())
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))
