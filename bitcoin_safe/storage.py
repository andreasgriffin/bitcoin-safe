 
# from https://stackoverflow.com/questions/2490334/simple-way-to-encode-a-string-according-to-a-password
import secrets
from base64 import urlsafe_b64encode as b64e, urlsafe_b64decode as b64d

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import json
from typing import Dict
from threading import Lock

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


    def save(self, message, password, filename): 
        token = self.encrypt.password_encrypt(message.encode(), password) if password else message.encode()

        with open(filename, 'wb') as f:
            f.write(token)
        
            
    def load(self, password, filename) -> str:
        with open(filename, 'rb') as f:
            token = f.read()
        
        # if chr(token[0]) == '{':
        #     print('No password required')
        #     return token.decode()            
        if not password:
            return token.decode()
        else:
            return self.encrypt.password_decrypt(token, password).decode()
            


if __name__ == '__main__':
    # e = Encrypt()
    # message = 'John DoeJohn DoeJohn DoeJohn DoeJohn DoeJohn DoeJohn DoeJohn DoeJohn DoeJohn Doe'
    # password = 'mypass'
    # token = e.password_encrypt(message.encode(), password)
    # print(token)
    # print(e.password_decrypt(token, password).decode())


    s = Storage()
    org_text = 'my message\nsssss'
    s.save(org_text, 'aaa', 'test.txt')
    
    
    new_text = s.load('aaa', 'test.txt')
    
    assert org_text == new_text 
    print(new_text)
    


    print(b64e('my wallet'.encode()))
    
    
    