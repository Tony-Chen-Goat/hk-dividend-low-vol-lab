from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.cloud_persistence import (
    CloudPersistenceConfig,
    backup_database_to_cloud,
    resolve_cloud_config,
    restore_database_from_cloud,
)


class MemoryStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload(self, object_path: str, payload: bytes, content_type: str, *, upsert: bool = False) -> None:
        if object_path in self.objects and not upsert:
            raise RuntimeError("object already exists")
        self.objects[object_path] = payload

    def download(self, object_path: str) -> bytes | None:
        return self.objects.get(object_path)


def _database(path: Path, value: str = "正式实验") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO records (value) VALUES (?)", (value,))


def _config() -> CloudPersistenceConfig:
    return CloudPersistenceConfig(
        url="https://example.supabase.co",
        service_key="test-service-role-key",
        bucket="private-backups",
    )


def test_config_supports_nested_streamlit_secrets() -> None:
    config = resolve_cloud_config({
        "persistence": {
            "SUPABASE_URL": "https://demo.supabase.co/",
            "SUPABASE_SERVICE_ROLE_KEY": "secret",
            "SUPABASE_STORAGE_BUCKET": "lab-backups",
        }
    })
    assert config.configured
    assert config.url == "https://demo.supabase.co"
    assert config.bucket == "lab-backups"


def test_new_secret_key_is_not_sent_as_bearer_token() -> None:
    from app.cloud_persistence import SupabaseStorageClient

    config = CloudPersistenceConfig(
        url="https://example.supabase.co",
        service_key="sb_secret_example",
        bucket="private-backups",
    )
    headers = SupabaseStorageClient(config)._headers()
    assert headers["apikey"] == "sb_secret_example"
    assert "Authorization" not in headers


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    _database(source)
    storage = MemoryStorage()

    backup = backup_database_to_cloud(
        source,
        reason="approved_experiment",
        protected=True,
        config=_config(),
        client=storage,
    )
    assert backup.ok
    assert backup.action == "backup"
    assert backup.manifest and backup.manifest["protected"] is True
    latest = json.loads(storage.objects["hk-dividend-low-vol/latest/manifest.json"])
    assert latest["sha256"] == backup.manifest["sha256"]
    assert latest["object_path"] in storage.objects

    result = restore_database_from_cloud(
        restored,
        force=True,
        config=_config(),
        client=storage,
    )
    assert result.ok
    assert result.action == "restore"
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "正式实验"


def test_unchanged_database_does_not_create_duplicate_version(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _database(source)
    storage = MemoryStorage()
    first = backup_database_to_cloud(source, config=_config(), client=storage)
    count_after_first = len(storage.objects)
    second = backup_database_to_cloud(source, config=_config(), client=storage)
    assert first.ok and second.ok
    assert second.action == "unchanged"
    assert len(storage.objects) == count_after_first


def test_corrupt_cloud_payload_is_rejected_without_overwriting_local_database(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    local = tmp_path / "local.sqlite3"
    _database(source, "云端")
    _database(local, "本地")
    storage = MemoryStorage()
    backup = backup_database_to_cloud(source, config=_config(), client=storage)
    assert backup.manifest
    storage.objects[backup.manifest["object_path"]] = b"not-a-gzip-file"

    result = restore_database_from_cloud(
        local,
        force=True,
        config=_config(),
        client=storage,
    )
    assert not result.ok
    assert result.action == "restore_failed"
    with sqlite3.connect(local) as connection:
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "本地"


def test_unconfigured_persistence_is_a_safe_noop(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _database(source)
    config = CloudPersistenceConfig(url="", service_key="", bucket="")
    backup = backup_database_to_cloud(source, config=config)
    restore = restore_database_from_cloud(source, config=config)
    assert not backup.configured and backup.action == "disabled"
    assert not restore.configured and restore.action == "disabled"

