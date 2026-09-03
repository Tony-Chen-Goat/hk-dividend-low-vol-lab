from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


_BOOTSTRAP_LOCK = threading.RLock()
_BOOTSTRAP_RESULTS: dict[str, "PersistenceResult"] = {}
_SEED_RESULTS: dict[str, "PersistenceResult"] = {}


@dataclass(frozen=True)
class CloudPersistenceConfig:
    url: str
    service_key: str
    bucket: str
    prefix: str = "hk-dividend-low-vol"
    timeout_seconds: int = 120

    @property
    def configured(self) -> bool:
        return bool(self.url and self.service_key and self.bucket)


@dataclass(frozen=True)
class PersistenceResult:
    ok: bool
    configured: bool
    action: str
    message: str
    manifest: dict[str, Any] | None = None


def _mapping_value(source: Mapping[str, Any] | None, key: str) -> Any:
    if source is None:
        return None
    try:
        value = source.get(key)
    except Exception:
        value = None
    if value not in (None, ""):
        return value
    try:
        nested = source.get("persistence")
    except Exception:
        nested = None
    if isinstance(nested, Mapping):
        return nested.get(key)
    return None


def resolve_cloud_config(secrets: Mapping[str, Any] | None = None) -> CloudPersistenceConfig:
    def value(name: str, default: str = "") -> str:
        candidate = _mapping_value(secrets, name)
        if candidate in (None, ""):
            candidate = os.environ.get(name, default)
        return str(candidate or default).strip()

    timeout_text = value("SUPABASE_STORAGE_TIMEOUT_SECONDS", "120")
    try:
        timeout = max(10, int(timeout_text))
    except ValueError:
        timeout = 120
    return CloudPersistenceConfig(
        url=value("SUPABASE_URL").rstrip("/"),
        service_key=value("SUPABASE_SECRET_KEY") or value("SUPABASE_SERVICE_ROLE_KEY"),
        bucket=value("SUPABASE_STORAGE_BUCKET", "hk-dividend-low-vol-backups"),
        prefix=value("SUPABASE_STORAGE_PREFIX", "hk-dividend-low-vol").strip("/"),
        timeout_seconds=timeout,
    )


class SupabaseStorageClient:
    def __init__(self, config: CloudPersistenceConfig):
        self.config = config

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"apikey": self.config.service_key, "Cache-Control": "no-store"}
        # New sb_secret_* keys are opaque API keys and must not be sent as Bearer tokens.
        # Legacy service_role JWTs still require Authorization for Storage compatibility.
        if not self.config.service_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.config.service_key}"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _object_url(self, object_path: str, authenticated: bool = False) -> str:
        bucket = quote(self.config.bucket, safe="")
        path = quote(object_path.strip("/"), safe="/")
        segment = "object/authenticated" if authenticated else "object"
        return f"{self.config.url}/storage/v1/{segment}/{bucket}/{path}"

    def upload(self, object_path: str, payload: bytes, content_type: str, *, upsert: bool = False) -> None:
        headers = self._headers(content_type)
        headers["x-upsert"] = "true" if upsert else "false"
        request = Request(
            self._object_url(object_path),
            data=payload,
            headers=headers,
            method="POST",
        )
        self._open(request)

    def download(self, object_path: str) -> bytes | None:
        request = Request(
            self._object_url(object_path, authenticated=True),
            headers=self._headers(),
            method="GET",
        )
        try:
            return self._open(request)
        except FileNotFoundError:
            return None

    def _open(self, request: Request) -> bytes:
        transient_codes = {408, 425, 429, 500, 502, 503, 504}
        for attempt in range(3):
            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    return response.read()
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code == 404:
                    raise FileNotFoundError("云端对象不存在") from exc
                if exc.code not in transient_codes or attempt == 2:
                    raise RuntimeError(f"Supabase Storage 请求失败（HTTP {exc.code}）：{body}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise RuntimeError(f"无法连接 Supabase Storage：{getattr(exc, 'reason', exc)}") from exc
            time.sleep(0.5 * (2**attempt))
        raise RuntimeError("Supabase Storage 请求在重试后仍未完成")


def _sqlite_snapshot_bytes(path: str | Path) -> bytes:
    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite 数据库不存在：{source_path.name}")
    descriptor, temporary_name = tempfile.mkstemp(prefix="hk-lab-snapshot-", suffix=".sqlite3")
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with closing(sqlite3.connect(source_path, timeout=30)) as source:
            with closing(sqlite3.connect(temporary_path)) as target:
                source.backup(target)
                target.commit()
        with closing(sqlite3.connect(temporary_path)) as check:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"SQLite 快照完整性检查失败：{result}")
        return temporary_path.read_bytes()
    finally:
        temporary_path.unlink(missing_ok=True)


def _install_sqlite_bytes(payload: bytes, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
    temporary.write_bytes(payload)
    try:
        with closing(sqlite3.connect(temporary)) as check:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"云端 SQLite 完整性检查失败：{result}")
        for suffix in ("-wal", "-shm"):
            target.with_name(target.name + suffix).unlink(missing_ok=True)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _latest_manifest_path(config: CloudPersistenceConfig) -> str:
    return f"{config.prefix}/latest/manifest.json"


def read_latest_manifest(
    config: CloudPersistenceConfig,
    client: SupabaseStorageClient | None = None,
) -> dict[str, Any] | None:
    if not config.configured:
        return None
    storage = client or SupabaseStorageClient(config)
    payload = storage.download(_latest_manifest_path(config))
    if payload is None:
        return None
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("云端最新备份清单不是有效 JSON") from exc
    required = {"object_path", "sha256", "raw_size", "created_at"}
    if not isinstance(manifest, dict) or not required.issubset(manifest):
        raise ValueError("云端最新备份清单字段不完整")
    return manifest


def backup_database_to_cloud(
    path: str | Path,
    secrets: Mapping[str, Any] | None = None,
    *,
    reason: str = "manual",
    protected: bool = False,
    force: bool = False,
    config: CloudPersistenceConfig | None = None,
    client: SupabaseStorageClient | None = None,
) -> PersistenceResult:
    active_config = config or resolve_cloud_config(secrets)
    if not active_config.configured:
        return PersistenceResult(False, False, "disabled", "尚未配置 Supabase 云端备份。")
    storage = client or SupabaseStorageClient(active_config)
    try:
        raw = _sqlite_snapshot_bytes(path)
        digest = hashlib.sha256(raw).hexdigest()
        if not force:
            latest = read_latest_manifest(active_config, storage)
            if latest and latest.get("sha256") == digest:
                return PersistenceResult(True, True, "unchanged", "数据库没有变化，无需重复备份。", latest)
        created_at = datetime.now(timezone.utc).isoformat()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        label = "-protected" if protected else ""
        version = f"{timestamp}-{digest[:10]}{label}"
        object_path = f"{active_config.prefix}/history/{version}.sqlite3.gz"
        manifest_path = f"{active_config.prefix}/history/{version}.json"
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        manifest = {
            "schema_version": 1,
            "created_at": created_at,
            "object_path": object_path,
            "sha256": digest,
            "raw_size": len(raw),
            "compressed_size": len(compressed),
            "reason": str(reason),
            "protected": bool(protected),
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        storage.upload(object_path, compressed, "application/gzip")
        storage.upload(manifest_path, manifest_bytes, "application/json")
        storage.upload(_latest_manifest_path(active_config), manifest_bytes, "application/json", upsert=True)
        return PersistenceResult(True, True, "backup", "云端数据库备份完成。", manifest)
    except Exception as exc:
        return PersistenceResult(False, True, "backup_failed", f"云端备份失败：{exc}")


def restore_database_from_cloud(
    path: str | Path,
    secrets: Mapping[str, Any] | None = None,
    *,
    force: bool = False,
    config: CloudPersistenceConfig | None = None,
    client: SupabaseStorageClient | None = None,
) -> PersistenceResult:
    active_config = config or resolve_cloud_config(secrets)
    if not active_config.configured:
        return PersistenceResult(False, False, "disabled", "尚未配置 Supabase 云端备份。")
    target = Path(path)
    if target.exists() and target.stat().st_size > 0 and not force:
        return PersistenceResult(True, True, "local_preserved", "检测到本地数据库，启动时未覆盖。")
    storage = client or SupabaseStorageClient(active_config)
    try:
        manifest = read_latest_manifest(active_config, storage)
        if manifest is None:
            return PersistenceResult(True, True, "remote_empty", "云端尚无数据库备份。")
        compressed = storage.download(str(manifest["object_path"]))
        if compressed is None:
            raise FileNotFoundError("最新清单指向的数据库快照不存在")
        try:
            raw = gzip.decompress(compressed)
        except (OSError, EOFError) as exc:
            raise ValueError("云端数据库压缩包损坏") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if digest != manifest["sha256"]:
            raise ValueError("云端数据库 SHA-256 校验失败")
        if len(raw) != int(manifest["raw_size"]):
            raise ValueError("云端数据库文件大小校验失败")
        _install_sqlite_bytes(raw, target)
        return PersistenceResult(True, True, "restore", "已从云端恢复最新数据库。", manifest)
    except Exception as exc:
        return PersistenceResult(False, True, "restore_failed", f"云端恢复失败：{exc}")


def bootstrap_cloud_database(
    path: str | Path,
    secrets: Mapping[str, Any] | None = None,
    *,
    force: bool = False,
) -> PersistenceResult:
    key = str(Path(path).resolve())
    with _BOOTSTRAP_LOCK:
        if not force and key in _BOOTSTRAP_RESULTS:
            return _BOOTSTRAP_RESULTS[key]
        result = restore_database_from_cloud(path, secrets, force=force)
        _BOOTSTRAP_RESULTS[key] = result
        return result


def seed_cloud_database_once(
    path: str | Path,
    secrets: Mapping[str, Any] | None = None,
) -> PersistenceResult:
    key = str(Path(path).resolve())
    with _BOOTSTRAP_LOCK:
        if key in _SEED_RESULTS:
            return _SEED_RESULTS[key]
        result = backup_database_to_cloud(path, secrets, reason="application_startup")
        _SEED_RESULTS[key] = result
        return result


def runtime_status(result: PersistenceResult) -> dict[str, Any]:
    payload = asdict(result)
    manifest = payload.get("manifest") or {}
    payload["last_backup_at"] = manifest.get("created_at")
    payload["last_backup_reason"] = manifest.get("reason")
    payload["protected"] = bool(manifest.get("protected", False))
    return payload
