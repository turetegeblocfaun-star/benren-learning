from app.core.config import Settings
from app.services.storage.local import LocalStorage, StagedAsset


def build_storage(settings: Settings) -> LocalStorage:
    if settings.storage_provider == "s3":
        from app.services.storage.s3 import S3Storage

        return S3Storage(settings)
    return LocalStorage(settings.storage_root)


__all__ = ["LocalStorage", "StagedAsset", "build_storage"]
