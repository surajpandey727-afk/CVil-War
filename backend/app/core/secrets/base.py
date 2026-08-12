"""Secrets provider interface and the encrypted-blob envelope model."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class EncryptedBlob(BaseModel):
    """An envelope-encrypted secret.

    ``ciphertext`` is the plaintext encrypted under a per-secret data key (DEK); the DEK
    itself is wrapped by the key-encryption key (KEK) identified by ``kek_id``.
    """

    kek_id: str
    wrapped_dek: str
    ciphertext: str
    scheme: str = "envelope-fernet-v1"


class SecretsProvider(ABC):
    """Encrypts/decrypts small secrets (LLM keys, session cookies) at rest.

    ``context`` is a set of key/value pairs (e.g. ``{user_id, kind, provider}``) bound to
    the ciphertext as additional authenticated data where the backend supports it (KMS);
    the local Fernet backend accepts it for interface parity.
    """

    @abstractmethod
    async def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> EncryptedBlob: ...

    @abstractmethod
    async def decrypt(self, blob: EncryptedBlob, *, context: dict[str, str]) -> bytes: ...

    @abstractmethod
    async def rotate(self, blob: EncryptedBlob, *, context: dict[str, str]) -> EncryptedBlob: ...

    @property
    @abstractmethod
    def current_kek_id(self) -> str: ...
