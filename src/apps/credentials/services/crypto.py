import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class CredentialCryptoError(RuntimeError):
    """Raised when credential encryption/decryption fails."""


class CredentialCrypto:
    def __init__(self, raw_key: str | None = None) -> None:
        source_key = raw_key or settings.ENCRYPTION_KEY
        if not source_key:
            raise CredentialCryptoError("ENCRYPTION_KEY is required for credential encryption.")

        self._fernet = Fernet(self._normalize_key(source_key))

    @staticmethod
    def _normalize_key(raw_key: str) -> bytes:
        digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    def encrypt(self, plain_text: str) -> str:
        if plain_text == "":
            return ""

        token = self._fernet.encrypt(plain_text.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, cipher_text: str) -> str:
        if cipher_text == "":
            return ""

        try:
            decrypted = self._fernet.decrypt(cipher_text.encode("utf-8"))
        except InvalidToken as exc:  # pragma: no cover
            raise CredentialCryptoError("Unable to decrypt stored credential value.") from exc

        return decrypted.decode("utf-8")
