from __future__ import annotations

import logging
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.services.storage import LocalStorage, build_storage

logger = logging.getLogger(__name__)


def sqlite_database_path(settings: Settings) -> Path | None:
    url = make_url(settings.database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        return None
    path = Path(url.database).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def restore_database_if_needed(settings: Settings) -> bool:
    database_path = sqlite_database_path(settings)
    if (
        database_path is None
        or database_path.exists()
        or not settings.backup_enabled
        or settings.storage_provider != "s3"
    ):
        return False
    # veFaaS only exposes /tmp as writable storage. On the first production
    # boot there may be no database and no cloud backup yet, but Alembic still
    # needs the parent directory to exist before SQLite can create the file.
    database_path.parent.mkdir(parents=True, exist_ok=True)
    storage = build_storage(settings)
    if not storage.object_exists(settings.backup_object_key):
        return False
    storage.download_file(settings.backup_object_key, database_path)
    logger.info("database restored from object storage")
    return True


def backup_database(settings: Settings, storage: LocalStorage) -> bool:
    database_path = sqlite_database_path(settings)
    if database_path is None or not database_path.is_file() or not settings.backup_enabled:
        return False
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=settings.storage_root,
        prefix="database-backup-",
        suffix=".db",
        delete=False,
    ) as handle:
        backup_path = Path(handle.name)
    try:
        with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
        storage.upload_file(settings.backup_object_key, backup_path)
        logger.info("database backup uploaded")
        return True
    finally:
        backup_path.unlink(missing_ok=True)
