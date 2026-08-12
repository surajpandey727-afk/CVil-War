"""AWS KMS secrets provider — deferred to Phase 4 (interface stub)."""

from __future__ import annotations

from app.core.secrets.base import EncryptedBlob, SecretsProvider

_DEFERRED = "KMS secrets provider is deferred to Phase 4"


class KmsSecretsProvider(SecretsProvider):
    """Placeholder so the factory can select ``provider=kms`` once AWS lands."""

    @property
    def current_kek_id(self) -> str:
        raise NotImplementedError(_DEFERRED)

    async def encrypt(self, plaintext: bytes, *, context: dict[str, str]) -> EncryptedBlob:
        raise NotImplementedError(_DEFERRED)

    async def decrypt(self, blob: EncryptedBlob, *, context: dict[str, str]) -> bytes:
        raise NotImplementedError(_DEFERRED)

    async def rotate(self, blob: EncryptedBlob, *, context: dict[str, str]) -> EncryptedBlob:
        raise NotImplementedError(_DEFERRED)
