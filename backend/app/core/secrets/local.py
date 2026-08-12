"""Local-dev secrets provider: Fernet/MultiFernet envelope encryption.

Each secret gets a fresh data key (DEK); the plaintext is encrypted with the DEK, and
the DEK is wrapped by the app's KEK (``MultiFernet``, so KEK rotation is supported by
prepending a new key). Production uses AWS KMS instead (Phase 4).
"""

from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, MultiFernet

from app.core.secrets.base import EncryptedBlob, SecretsProvider


def _kek_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class LocalSecretsProvider(SecretsProvider):
    """Envelope encryption with app-held Fernet keys (first key is the current KEK)."""

    def __init__(self, app_keys: list[str]) -> None:
        if not app_keys:
            raise ValueError("LocalSecretsProvider requires at least one key (SECRETS__APP_KEYS)")
        self._kek = MultiFernet([Fernet(k) for k in app_keys])
        self._current_kek_id = _kek_id(app_keys[0])

    @property
    def current_kek_id(self) -> str:
        return self._current_kek_id

    async def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> EncryptedBlob:
        _ = context  # bound as AAD only by the KMS backend; accepted here for parity
        dek = Fernet.generate_key()
        ciphertext = Fernet(dek).encrypt(plaintext)
        wrapped = self._kek.encrypt(dek)
        return EncryptedBlob(
            kek_id=self._current_kek_id,
            wrapped_dek=wrapped.decode(),
            ciphertext=ciphertext.decode(),
        )

    async def decrypt(self, blob: EncryptedBlob, *, context: dict[str, str]) -> bytes:
        _ = context
        dek = self._kek.decrypt(blob.wrapped_dek.encode())
        return Fernet(dek).decrypt(blob.ciphertext.encode())

    async def rotate(self, blob: EncryptedBlob, *, context: dict[str, str]) -> EncryptedBlob:
        plaintext = await self.decrypt(blob, context=context)
        return await self.encrypt(plaintext, context=context)
