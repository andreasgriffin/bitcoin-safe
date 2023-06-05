import logging
logger = logging.getLogger(__name__)

 
# from https://stackoverflow.com/questions/2490334/simple-way-to-encode-a-string-according-to-a-password
import secrets
from base64 import urlsafe_b64encode as b64e, urlsafe_b64decode as b64d

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import json
from typing import Dict
import enum, os
import bdkpython as bdk

class Encrypt(): 
    def _derive_key(self, password: bytes, salt: bytes, iterations: int) -> bytes:
        """Derive a secret key from a given password and salt"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA512(), length=32, salt=salt,
            iterations=iterations, backend=default_backend())
        return b64e(kdf.derive(password))

    def password_encrypt(self, message: bytes, password: str, iterations: int = 100_000) -> bytes:
        salt = secrets.token_bytes(16)
        key = self._derive_key(password.encode(), salt, iterations)
        return b64e(
            b'%b%b%b' % (
                salt,
                iterations.to_bytes(4, 'big'),
                b64d(Fernet(key).encrypt(message)),
            )
        )

    def password_decrypt(self, token: bytes, password: str) -> bytes:
        decoded = b64d(token)
        salt, iter, token = decoded[:16], decoded[16:20], b64e(decoded[20:])
        iterations = int.from_bytes(iter, 'big')
        if iterations > 1e6:
            raise Exception('Error in decrypting')
        key = self._derive_key(password.encode(), salt, iterations)
        return Fernet(key).decrypt(token)




class Storage():
    def __init__(self) -> None:
        self.encrypt = Encrypt()


    def save(self, message, filename, password=None): 
        token = self.encrypt.password_encrypt(message.encode(), password) if password else message.encode()

        with open(filename, 'wb') as f:
            f.write(token)
    
    @classmethod
    def has_password(cls, filename) -> bool:
        with open(filename, 'rb') as f:
            token = f.read()
        
        if token.decode()[0] == '{':
            return False
        
        return True
            
            
    def load(self, filename,  password=None) -> str:
        with open(filename, 'rb') as f:
            token = f.read()
        
    
        if not password:
            logger.debug(f'Opening {filename} without password')
            return token.decode()
        else:
            logger.debug(f'Decrypting {filename}')
            return self.encrypt.password_decrypt(token, password).decode()
            




class ClassSerializer:

    @classmethod
    def general_deserializer(cls, globals):

        def deserializer(dct):
            cls_string = dct.get("__class__")  # e.g. KeyStore
            if cls_string and cls_string in globals:
                obj_cls = globals[cls_string]
                if hasattr(obj_cls, 'deserialize'):  # is there KeyStore.deserialize ? 
                    return obj_cls.deserialize(dct)  # do: KeyStore.deserialize(**dct)
            if dct.get("__enum__"):
                obj_cls = globals.get(dct["name"])                
                if not obj_cls:
                    obj_cls = getattr(bdk, dct["name"])  # if the class name is not imported directly, then try bdk
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
        if hasattr(obj, 'serialize'):
            return obj.serialize()
        # Fall back to the default JSON serializer
        return json.JSONEncoder().default(obj)                            



class BaseSaveableClass:
    global_variables = None

    def serialize(self):
        d = {}
        d["__class__"] = self.__class__.__name__
        return d
        
    @classmethod
    def deserialize(cls, dct):
        assert dct.get("__class__") == cls.__name__
        del dct["__class__"]
            
            
    def save(self, filename, password=None):

        directory = os.path.dirname(filename)
        # Create the directories
        if directory:
            os.makedirs(directory, exist_ok=True)
        


        human_readable = not bool(password)                           
        storage = Storage()
        storage.save(json.dumps(self, default=ClassSerializer.general_serializer, 
                                indent=4 if human_readable else None,
                                sort_keys=bool(human_readable),                                
                                ), filename, password=password)
        
    
    @classmethod
    def load(cls, filename, password=None):     
        storage = Storage()
        
        json_string = storage.load(filename, password=password)
        return json.loads(json_string, object_hook=ClassSerializer.general_deserializer(cls.global_variables))
            