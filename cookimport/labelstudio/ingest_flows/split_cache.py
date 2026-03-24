from __future__ import annotations

from cookimport.labelstudio.ingest import *  # noqa: F401,F403
from cookimport.labelstudio import ingest as _ingest

globals().update(
    {name: getattr(_ingest, name) for name in dir(_ingest) if not name.startswith("__")}
)


def _normalize_single_book_split_cache_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"", "off", "none", "disabled", "false", "0"}:
        return "off"
    if normalized in {"auto", "on", "enabled", "true", "1"}:
        return "auto"
    raise ValueError(
        "Invalid single_book_split_cache_mode. Expected one of: off, auto."
    )

def _single_book_split_cache_entry_path(
    *,
    cache_root: Path,
    split_cache_key: str,
) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(split_cache_key or "").strip())
    if not safe_key:
        safe_key = "unknown"
    return cache_root / f"{safe_key}.json"

def _single_book_split_cache_lock_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(
        f"{cache_path.suffix}{SINGLE_BOOK_SPLIT_CACHE_LOCK_SUFFIX}"
    )

def _load_single_book_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
) -> dict[str, Any] | None:
    if not cache_path.exists() or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if (
        str(payload.get("schema_version") or "").strip()
        != SINGLE_BOOK_SPLIT_CACHE_SCHEMA_VERSION
    ):
        return None
    cached_key = str(payload.get("single_book_split_cache_key") or "").strip()
    if cached_key != str(expected_key or "").strip():
        return None
    conversion_payload = payload.get("conversion_result")
    if not isinstance(conversion_payload, dict):
        return None
    return payload

def _write_single_book_split_cache_entry(
    *,
    cache_path: Path,
    payload: dict[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(
        f"{cache_path.suffix}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    )
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)

def _acquire_single_book_split_cache_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                    sort_keys=True,
                )
            )
    except Exception:  # noqa: BLE001
        try:
            lock_path.unlink()
        except OSError:
            pass
        return False
    return True

def _release_single_book_split_cache_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        return

def _wait_for_single_book_split_cache_entry(
    *,
    cache_path: Path,
    expected_key: str,
    lock_path: Path,
    wait_seconds: float = SINGLE_BOOK_SPLIT_CACHE_WAIT_SECONDS,
    poll_seconds: float = SINGLE_BOOK_SPLIT_CACHE_POLL_SECONDS,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    sleep_seconds = max(0.05, float(poll_seconds))
    while time.monotonic() < deadline:
        cached = _load_single_book_split_cache_entry(
            cache_path=cache_path,
            expected_key=expected_key,
        )
        if cached is not None:
            return cached
        if not lock_path.exists():
            break
        time.sleep(sleep_seconds)
    return _load_single_book_split_cache_entry(
        cache_path=cache_path,
        expected_key=expected_key,
    )

def _normalize_split_phase_slots(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized

def _try_acquire_file_lock_nonblocking(handle: Any) -> bool:
    if fcntl is None:
        return True
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True

def _release_file_lock(handle: Any) -> None:
    if fcntl is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return

def _emit_split_phase_status(
    *,
    notify: Callable[[str], None] | None,
    message: str,
) -> None:
    cleaned = str(message or "").strip()
    if not cleaned:
        return
    if notify is not None:
        _notify_progress_callback(notify, cleaned)
        return
    print(cleaned)

def _acquire_split_phase_slot(
    *,
    slots: int,
    gate_dir: Path | str | None,
    notify: Callable[[str], None] | None,
    status_label: str | None,
) -> Iterable[tuple[int, int] | None]:
    normalized_slots = _normalize_split_phase_slots(slots)
    if normalized_slots is None:
        yield None
        return

    slot_total = max(1, normalized_slots)
    slot_label = str(status_label or "").strip()
    gate_root = Path(gate_dir) if gate_dir is not None else None
    if gate_root is None:
        yield (1, slot_total)
        return
    gate_root.mkdir(parents=True, exist_ok=True)

    def _status(message: str) -> str:
        if slot_label:
            return f"{slot_label} {message}"
        return message

    waited = False
    while True:
        for slot_index in range(1, slot_total + 1):
            slot_path = gate_root / f"split_slot_{slot_index:02d}.lock"
            handle = slot_path.open("a+", encoding="utf-8")
            if not _try_acquire_file_lock_nonblocking(handle):
                handle.close()
                continue

            _emit_split_phase_status(
                notify=notify,
                message=_status(f"acquired split slot {slot_index}/{slot_total}."),
            )
            try:
                yield (slot_index, slot_total)
            finally:
                _release_file_lock(handle)
                handle.close()
                _emit_split_phase_status(
                    notify=notify,
                    message=_status(f"released split slot {slot_index}/{slot_total}."),
                )
            return

        if not waited:
            _emit_split_phase_status(
                notify=notify,
                message=_status("waiting for split slot..."),
            )
            waited = True
        time.sleep(0.2)
