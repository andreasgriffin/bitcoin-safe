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


import logging
from abc import abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

logger = logging.getLogger(__name__)


import enum
import json
import os

# from https://stackoverflow.com/questions/2490334/simple-way-to-encode-a-string-according-to-a-password
import secrets
from base64 import urlsafe_b64decode as b64d
from base64 import urlsafe_b64encode as b64e
from typing import Callable, Dict, Iterable, Type

import bdkpython as bdk
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from packaging import version


def varnames(method: Callable) -> Iterable[str]:
    return method.__code__.co_varnames[: method.__code__.co_argcount]


def filtered_dict(d: Dict, allowed_keys: Iterable[str]) -> Dict:
    return {k: v for k, v in d.items() if k in allowed_keys}


def filtered_for_init(d: Dict, cls: Type) -> Dict:
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
        decoded = b64d(token)
        salt, iter, token = decoded[:16], decoded[16:20], b64e(decoded[20:])
        iterations = int.from_bytes(iter, "big")
        if iterations > 1e6:
            raise Exception("Error in decrypting")
        key = self._derive_key(password.encode(), salt, iterations)
        return Fernet(key).decrypt(token)


class Storage:
    def __init__(self) -> None:
        self.encrypt = Encrypt()

    def save(self, message: str, filename: str, password: Optional[str] = None) -> None:
        token = self.encrypt.password_encrypt(message.encode(), password) if password else message.encode()

        with open(filename, "wb") as f:
            f.write(token)

    @classmethod
    def has_password(cls, filename: str) -> bool:
        with open(filename, "rb") as f:
            token = f.read()

        if token.decode()[0] == "{":
            return False

        return True

    def load(self, filename: str, password: Optional[str] = None) -> str:
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
        def deserializer(dct) -> Dict:
            cls_string = dct.get("__class__")  # e.g. KeyStore
            if cls_string:
                if cls_string in known_classes:
                    obj_cls = known_classes[cls_string]
                    if hasattr(obj_cls, "from_dump"):  # is there KeyStore.from_dump ?
                        if class_kwargs.get(cls_string):  #  apply additional arguments to the class from_dump
                            dct.update(class_kwargs.get(cls_string))
                        return obj_cls.from_dump(
                            dct, class_kwargs=class_kwargs
                        )  # do: KeyStore.from_dump(**dct)
                    else:
                        raise Exception(f"{obj_cls} doesnt have a from_dump classmethod.")
                else:
                    raise Exception(
                        f"""{cls_string} not in known_classes {known_classes}."""
                        """Did you add the following to the child class?
                                            VERSION = "0.0.1"
                                            known_classes = {
                                                **BaseSaveableClass.known_classes,
                                            }"""
                        f"""And did you add
                                       "cls_string":{cls_string}
                                       to the parent BaseSaveableClass ?
    """
                    )
            elif dct.get("__enum__"):
                obj_cls = known_classes.get(dct["name"])
                if obj_cls:
                    return getattr(obj_cls, dct["value"])
                else:
                    raise Exception(f"Could not do from_dump(**{dct})")

            # For normal cases, json.loads will handle default JSON data types
            # No need to use json.Decoder here, just return the dictionary as-is
            return dct

        return deserializer

    @classmethod
    def general_serializer(cls, obj):
        if isinstance(obj, enum.Enum):
            return {"__enum__": True, "name": obj.__class__.__name__, "value": obj.name}
        if isinstance(obj, BaseSaveableClass):
            return obj.dump()
        # Fall back to the default JSON serializer
        return json.JSONEncoder().default(obj)


class BaseSaveableClass:
    known_classes: Dict[str, Any] = {"Network": bdk.Network}
    VERSION = "0.0.0"

    @abstractmethod
    def dump(self) -> Dict:
        "Returns the dict"
        d = {}
        d["__class__"] = self.__class__.__name__
        d["VERSION"] = self.VERSION
        return d

    @classmethod
    @abstractmethod
    def from_dump_migration(cls, dct):
        "this class should be overwritten in child classes"
        return dct

    @classmethod
    def _from_dump(cls, dct, class_kwargs=None):
        assert dct.get("__class__") == cls.__name__
        del dct["__class__"]

        if version.parse(cls.VERSION) > version.parse(str(dct.get("VERSION", 0))):
            dct = cls.from_dump_migration(dct)

        if "VERSION" in dct:
            del dct["VERSION"]

    @classmethod
    @abstractmethod
    def from_dump(cls, dct, class_kwargs=None):
        raise NotImplementedError()

    def clone(self, class_kwargs=None):
        return self.from_dump(self.dump(), class_kwargs=class_kwargs)

    def save(self, filename: Union[Path, str], password: Optional[str] = None):
        "Saves the json dumps to a file"
        directory = os.path.dirname(str(filename))
        # Create the directories
        if directory:
            os.makedirs(directory, exist_ok=True)

        storage = Storage()
        storage.save(
            self.dumps(indent=None if password else 4),
            str(filename),
            password=password,
        )

    def __str__(self) -> str:
        return self.dumps()

    def dumps(self, indent=None) -> str:
        "Returns the json representation (recursively)"
        return json.dumps(
            self,
            default=ClassSerializer.general_serializer,
            indent=indent,
            sort_keys=True,
        )

    @staticmethod
    def _flatten_known_classes(known_classes: Dict[str, Any]) -> Dict[str, Any]:
        "Recursively extends the dict to includes all known_classes of known_classes"
        known_classes = known_classes.copy()
        for known_class in list(known_classes.values()):
            if issubclass(known_class, BaseSaveableClass):
                known_classes.update(BaseSaveableClass._flatten_known_classes(known_class.known_classes))
        return known_classes

    @classmethod
    def get_known_classes(cls) -> Dict[str, Any]:
        "Gets a flattened list of known classes that a json deserializer needs to interpet all objects"
        return BaseSaveableClass._flatten_known_classes({cls.__name__: cls})

    @classmethod
    def _from_file(cls, filename: str, password: Optional[str] = None, class_kwargs=None):
        """Loads the class from a file. This offers the option of add class_kwargs args

        Args:
            filename (str): _description_
            password (Optional[str], optional): _description_. Defaults to None.
            class_kwargs (_type_, optional):  example:  class_kwargs= {'Wallet':{'config':config}}. Defaults to None.

        Returns:
            _type_: _description_
        """
        class_kwargs = class_kwargs if class_kwargs else {}
        storage = Storage()

        json_string = storage.load(filename, password=password)

        instance = json.loads(
            json_string,
            object_hook=ClassSerializer.general_deserializer(cls.get_known_classes(), class_kwargs),
        )
        return instance


class SaveAllClass(BaseSaveableClass):
    def dump(self):
        d = super().dump()
        d.update(self.__dict__.copy())
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs=None):
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))
