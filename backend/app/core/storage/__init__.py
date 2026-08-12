"""File storage abstraction: local FS now, S3 (Phase 4) behind one interface."""

from app.core.storage.base import FileStorage, StoredObject
from app.core.storage.factory import get_storage
from app.core.storage.service import StorageService

__all__ = ["FileStorage", "StorageService", "StoredObject", "get_storage"]
