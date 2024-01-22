import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


import copy
import enum
import json
import os

# from https://stackoverflow.com/questions/2490334/simple-way-to-encode-a-string-according-to-a-password
import secrets
from base64 import urlsafe_b64decode as b64d
from base64 import urlsafe_b64encode as b64e

import bdkpython as bdk
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from packaging import version


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

    def save(self, message: str, filename: str, password: Optional[str] = None):
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
    def general_deserializer(cls, globals, class_kwargs):
        def deserializer(dct):
            cls_string = dct.get("__class__")  # e.g. KeyStore
            if cls_string and cls_string in globals:
                obj_cls = globals[cls_string]
                if hasattr(obj_cls, "deserialize"):  # is there KeyStore.deserialize ?
                    if class_kwargs.get(cls_string):  #  apply additional arguments to the class deserialize
                        dct.update(class_kwargs.get(cls_string))
                    return obj_cls.deserialize(
                        dct, class_kwargs=class_kwargs
                    )  # do: KeyStore.deserialize(**dct)
            elif dct.get("__enum__"):
                obj_cls = globals.get(dct["name"])
                if not obj_cls and hasattr(bdk, dct["name"]):
                    # if the class name is not imported directly, then try bdk
                    obj_cls = getattr(bdk, dct["name"])
                if obj_cls:
                    return getattr(obj_cls, dct["value"])
            # For normal cases, json.loads will handle default JSON data types
            # No need to use json.Decoder here, just return the dictionary as-is
            return dct

        return deserializer

    @classmethod
    def general_serializer(cls, obj):
        if isinstance(obj, enum.Enum):
            return {"__enum__": True, "name": obj.__class__.__name__, "value": obj.name}
        if hasattr(obj, "serialize"):
            return obj.serialize()
        # Fall back to the default JSON serializer
        return json.JSONEncoder().default(obj)


class BaseSaveableClass:
    global_variables: Dict[str, Any] = {}
    VERSION = "0.0.0"

    def serialize(self):
        d = {}
        d["__class__"] = self.__class__.__name__
        d["VERSION"] = self.VERSION
        return d

    @classmethod
    def deserialize_migration(cls, dct):
        "this class should be oveerwritten in child classes"
        return dct

    @classmethod
    def deserialize(cls, dct, class_kwargs=None):
        assert dct.get("__class__") == cls.__name__
        del dct["__class__"]

        if version.parse(cls.VERSION) > version.parse(str(dct.get("VERSION", 0))):
            dct = cls.deserialize_migration(dct)

        if "VERSION" in dct:
            del dct["VERSION"]

    def clone(self, class_kwargs=None):
        return self.deserialize(self.serialize(), class_kwargs=class_kwargs)

    def save(self, filename: str, password: Optional[str] = None):

        directory = os.path.dirname(filename)
        # Create the directories
        if directory:
            os.makedirs(directory, exist_ok=True)

        not bool(password)
        storage = Storage()
        storage.save(
            self.dumps(password=password),
            filename,
            password=password,
        )

    def dump_dict(self, password: Optional[str] = None):
        return json.loads(self.dumps(password=password))

    def dumps(self, password: Optional[str] = None):
        human_readable = not bool(password)
        return json.dumps(
            self,
            default=ClassSerializer.general_serializer,
            indent=4 if human_readable else None,
            sort_keys=bool(human_readable),
        )

    @classmethod
    def _load(cls, filename: str, password: Optional[str] = None, class_kwargs=None):
        "class_kwargs example:  class_kwargs= {'Wallet':{'config':config}}"
        class_kwargs = class_kwargs if class_kwargs else {}
        storage = Storage()

        json_string = storage.load(filename, password=password)
        return json.loads(
            json_string,
            object_hook=ClassSerializer.general_deserializer(cls.global_variables, class_kwargs),
        )


class SaveAllClass(BaseSaveableClass):
    def serialize(self):
        d = super().serialize()
        d.update(copy.deepcopy(self.__dict__))
        return d

    @classmethod
    def deserialize(cls, dct, class_kwargs=None):
        super().deserialize(dct, class_kwargs=class_kwargs)
        return cls(**dct)
