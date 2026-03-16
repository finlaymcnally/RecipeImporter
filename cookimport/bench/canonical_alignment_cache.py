from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

CANONICAL_ALIGNMENT_CACHE_SCHEMA_VERSION = "canonical_alignment_cache.v1"
CANONICAL_ALIGNMENT_NORMALIZATION_VERSION = 1
CANONICAL_ALIGNMENT_ALGO_VERSION = 1


def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def hash_block_boundaries(boundaries: list[tuple[int, int]]) -> str:
    normalized = [[int(start), int(end)] for start, end in boundaries]
    payload = json.dumps(normalized, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_cache_file_key(
    *,
    alignment_strategy: str,
    canonical_normalized_sha256: str,
    prediction_normalized_sha256: str,
    prediction_block_boundaries_sha256: str,
    normalization_version: int = CANONICAL_ALIGNMENT_NORMALIZATION_VERSION,
    algo_version: int = CANONICAL_ALIGNMENT_ALGO_VERSION,
) -> str:
    payload = {
        "schema_version": CANONICAL_ALIGNMENT_CACHE_SCHEMA_VERSION,
        "normalization_version": int(normalization_version),
        "alignment_strategy": str(alignment_strategy or "global"),
        "algo_version": int(algo_version),
        "canonical_sha256": str(canonical_normalized_sha256),
        "prediction_sha256": str(prediction_normalized_sha256),
        "prediction_boundaries_sha256": str(prediction_block_boundaries_sha256),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CanonicalAlignmentCacheEntry:
    schema_version: str
    created_at: str
    alignment_strategy: str
    normalization_version: int
    repo_alignment_algo_version: int
    canonical_normalized_sha256: str
    prediction_normalized_sha256: str
    prediction_block_boundaries_sha256: str
    canonical_normalized_char_count: int
    prediction_normalized_char_count: int
    payload: dict[str, Any]
    python_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        row = {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "alignment_strategy": self.alignment_strategy,
            "normalization_version": int(self.normalization_version),
            "repo_alignment_algo_version": int(self.repo_alignment_algo_version),
            "canonical_normalized_sha256": self.canonical_normalized_sha256,
            "prediction_normalized_sha256": self.prediction_normalized_sha256,
            "prediction_block_boundaries_sha256": self.prediction_block_boundaries_sha256,
            "canonical_normalized_char_count": int(self.canonical_normalized_char_count),
            "prediction_normalized_char_count": int(self.prediction_normalized_char_count),
            "payload": self.payload,
        }
        if self.python_version:
            row["python_version"] = self.python_version
        return row

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> CanonicalAlignmentCacheEntry:
        if not isinstance(row, Mapping):
            raise ValueError("cache entry must be an object")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("cache entry payload must be an object")
        schema_version = str(row.get("schema_version") or "")
        if schema_version != CANONICAL_ALIGNMENT_CACHE_SCHEMA_VERSION:
            raise ValueError("cache entry schema version mismatch")
        return cls(
            schema_version=schema_version,
            created_at=str(row.get("created_at") or ""),
            alignment_strategy=str(row.get("alignment_strategy") or ""),
            normalization_version=int(row.get("normalization_version") or 0),
            repo_alignment_algo_version=int(row.get("repo_alignment_algo_version") or 0),
            canonical_normalized_sha256=str(row.get("canonical_normalized_sha256") or ""),
            prediction_normalized_sha256=str(row.get("prediction_normalized_sha256") or ""),
            prediction_block_boundaries_sha256=str(
                row.get("prediction_block_boundaries_sha256") or ""
            ),
            canonical_normalized_char_count=int(row.get("canonical_normalized_char_count") or 0),
            prediction_normalized_char_count=int(
                row.get("prediction_normalized_char_count") or 0
            ),
            payload=payload,
            python_version=str(row.get("python_version") or "") or None,
        )


class CanonicalAlignmentDiskCache:
    def __init__(
        self,
        cache_dir: Path,
        *,
        wait_seconds: int = 3600,
        poll_seconds: float = 0.1,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self._wait_seconds = max(1, int(wait_seconds))
        self._poll_seconds = max(0.01, float(poll_seconds))

    def cache_path_for_key(self, key: str) -> Path:
        digest = str(key or "").strip().lower()
        if not digest:
            raise ValueError("cache key must be a non-empty string")
        prefix = digest[:2]
        return self.cache_dir / prefix / f"{digest}.json"

    def lock_path_for_key(self, key: str) -> Path:
        return self.cache_path_for_key(key).with_suffix(".lock")

    def try_load(
        self,
        key: str,
        *,
        expected_signatures: Mapping[str, Any],
    ) -> tuple[CanonicalAlignmentCacheEntry | None, str | None]:
        cache_path = self.cache_path_for_key(key)
        if not cache_path.exists():
            return None, None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._move_aside_corrupt(cache_path, reason="decode")
            return None, f"cache_read_error:{exc.__class__.__name__}"
        try:
            entry = CanonicalAlignmentCacheEntry.from_dict(payload)
        except Exception as exc:  # noqa: BLE001
            self._move_aside_corrupt(cache_path, reason="schema")
            return None, f"cache_schema_error:{exc}"
        signature_error = self._signature_mismatch(
            entry=entry,
            expected_signatures=expected_signatures,
        )
        if signature_error is not None:
            return None, signature_error
        return entry, None

    @contextmanager
    def lock_for_key(self, key: str) -> Iterator[bool]:
        cache_path = self.cache_path_for_key(key)
        lock_path = self.lock_path_for_key(key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        acquired = False
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if cache_path.exists():
                    yield False
                    return
                if self._is_lock_stale(lock_path):
                    try:
                        lock_path.unlink()
                        continue
                    except FileNotFoundError:
                        continue
                    except OSError:
                        pass
                time.sleep(self._poll_seconds)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"pid={os.getpid()} started_at={time.time():.6f}\n")
                handle.flush()
                os.fsync(handle.fileno())
            acquired = True
            break
        try:
            yield True
        finally:
            if acquired:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    def write_atomic(self, key: str, entry: CanonicalAlignmentCacheEntry) -> None:
        cache_path = self.cache_path_for_key(key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            return
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{cache_path.name}.",
            suffix=".tmp",
            dir=str(cache_path.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
            if cache_path.exists():
                return
            os.replace(tmp_path, cache_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _is_lock_stale(self, lock_path: Path) -> bool:
        owner_pid = self._read_lock_owner_pid(lock_path)
        if owner_pid is not None and not self._is_process_alive(owner_pid):
            return True
        try:
            stat_result = lock_path.stat()
        except OSError:
            return False
        age_seconds = max(0.0, time.time() - float(stat_result.st_mtime))
        return age_seconds >= float(self._wait_seconds)

    def _read_lock_owner_pid(self, lock_path: Path) -> int | None:
        try:
            raw_line = lock_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw_line:
            return None
        for token in raw_line.split():
            if not token.startswith("pid="):
                continue
            try:
                pid = int(token.split("=", 1)[1])
            except (TypeError, ValueError):
                return None
            return pid if pid > 0 else None
        return None

    def _is_process_alive(self, pid: int) -> bool:
        if int(pid) <= 0:
            return False
        try:
            os.kill(int(pid), 0)
        except (ValueError, OverflowError):
            return False
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
        return True

    def _move_aside_corrupt(self, cache_path: Path, *, reason: str) -> None:
        timestamp = str(int(time.time()))
        destination = cache_path.with_suffix(f".corrupt.{reason}.{timestamp}.json")
        try:
            os.replace(cache_path, destination)
        except OSError:
            return

    def _signature_mismatch(
        self,
        *,
        entry: CanonicalAlignmentCacheEntry,
        expected_signatures: Mapping[str, Any],
    ) -> str | None:
        pairs = (
            ("alignment_strategy", entry.alignment_strategy),
            ("normalization_version", int(entry.normalization_version)),
            ("repo_alignment_algo_version", int(entry.repo_alignment_algo_version)),
            ("canonical_normalized_sha256", entry.canonical_normalized_sha256),
            ("prediction_normalized_sha256", entry.prediction_normalized_sha256),
            (
                "prediction_block_boundaries_sha256",
                entry.prediction_block_boundaries_sha256,
            ),
            ("canonical_normalized_char_count", int(entry.canonical_normalized_char_count)),
            ("prediction_normalized_char_count", int(entry.prediction_normalized_char_count)),
        )
        for key, observed in pairs:
            expected = expected_signatures.get(key)
            if expected is None:
                return f"cache_signature_missing:{key}"
            if str(observed) != str(expected):
                return f"cache_signature_mismatch:{key}"
        return None


def make_cache_entry(
    *,
    alignment_strategy: str,
    canonical_normalized_sha256: str,
    prediction_normalized_sha256: str,
    prediction_block_boundaries_sha256: str,
    canonical_normalized_char_count: int,
    prediction_normalized_char_count: int,
    payload: dict[str, Any],
) -> CanonicalAlignmentCacheEntry:
    return CanonicalAlignmentCacheEntry(
        schema_version=CANONICAL_ALIGNMENT_CACHE_SCHEMA_VERSION,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        alignment_strategy=str(alignment_strategy or "global"),
        normalization_version=CANONICAL_ALIGNMENT_NORMALIZATION_VERSION,
        repo_alignment_algo_version=CANONICAL_ALIGNMENT_ALGO_VERSION,
        canonical_normalized_sha256=str(canonical_normalized_sha256),
        prediction_normalized_sha256=str(prediction_normalized_sha256),
        prediction_block_boundaries_sha256=str(prediction_block_boundaries_sha256),
        canonical_normalized_char_count=max(0, int(canonical_normalized_char_count)),
        prediction_normalized_char_count=max(0, int(prediction_normalized_char_count)),
        payload=payload,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
