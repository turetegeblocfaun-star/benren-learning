from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import backup as backup_service
from app.services.backup import backup_database, restore_database_if_needed
from app.services.storage.local import LocalStorage


def create_database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE proof (value TEXT NOT NULL)")
        connection.execute("INSERT INTO proof VALUES (?)", (value,))


def read_database(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT value FROM proof").fetchone()
    assert row is not None
    return str(row[0])


def test_sqlite_backup_is_consistent_and_uploadable(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "app.db"
    storage = LocalStorage(tmp_path / "storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{database_path}",
        storage_root=storage.root,
        backup_enabled=True,
    )
    create_database(database_path, "recoverable")

    assert backup_database(settings, storage)

    database_path.unlink()
    storage.download_file(settings.backup_object_key, database_path)
    assert read_database(database_path) == "recoverable"


def test_startup_restore_uses_cloud_backup_when_database_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "data" / "app.db"
    storage = LocalStorage(tmp_path / "storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{database_path}",
        storage_root=storage.root,
        storage_provider="s3",
        s3_bucket="test-bucket",
        backup_enabled=True,
    )
    backup_source = tmp_path / "backup-source.db"
    create_database(backup_source, "restored")
    storage.upload_file(settings.backup_object_key, backup_source)
    monkeypatch.setattr(backup_service, "build_storage", lambda _settings: storage)

    assert restore_database_if_needed(settings)
    assert read_database(database_path) == "restored"


def test_startup_restore_prepares_sqlite_directory_without_existing_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "data" / "app.db"
    storage = LocalStorage(tmp_path / "storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{database_path}",
        storage_root=storage.root,
        storage_provider="s3",
        s3_bucket="test-bucket",
        backup_enabled=True,
    )
    monkeypatch.setattr(backup_service, "build_storage", lambda _settings: storage)

    assert not restore_database_if_needed(settings)
    assert database_path.parent.is_dir()
