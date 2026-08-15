from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .models import EvalConfigError, EvalDirectory

CHECKPOINT_SCHEMA_VERSION = 1
CheckpointKind = Literal["run", "seed"]
_O_BINARY = getattr(os, "O_BINARY", 0)
_WINDOWS = os.name == "nt"


@dataclass(frozen=True)
class CheckpointSnapshot:
    path: Path
    manifest: dict[str, Any]

    @property
    def invocation(self) -> dict[str, Any]:
        invocation = self.manifest.get("invocation")
        if not isinstance(invocation, dict):
            raise EvalConfigError(
                f"checkpoint manifest has no valid invocation: {self.path}"
            )
        return invocation


class CheckpointStore:
    def __init__(
        self, snapshot: CheckpointSnapshot, *, created_by_current_operation: bool
    ) -> None:
        self.path = snapshot.path
        self.manifest = snapshot.manifest
        self._events_path = self.path / "events.jsonl"
        self._lock_path = self.path / "active.lock"
        self._lock_token = secrets.token_hex(16)
        self._created_by_current_operation = created_by_current_operation
        self._has_reusable_results = False
        self._acquire_lock()
        try:
            self._prepare_event_log()
        except BaseException:
            self.release()
            raise

    @classmethod
    def create(
        cls,
        *,
        kind: CheckpointKind,
        eval_dir: Path,
        invocation: dict[str, Any],
        plan_hash: str,
        total: int,
    ) -> CheckpointStore:
        checkpoint_id = _new_checkpoint_id(kind)
        root = _checkpoint_root(eval_dir)
        path = root / checkpoint_id
        try:
            path.mkdir(parents=True, mode=0o700)
            os.chmod(path, 0o700)
        except OSError as error:
            raise EvalConfigError(
                f"could not create checkpoint directory {path}: {error}"
            ) from error
        now = _utc_timestamp()
        manifest = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "id": checkpoint_id,
            "kind": kind,
            "status": "in_progress",
            "eval_dir": str(eval_dir.expanduser().resolve()),
            "created_at": now,
            "updated_at": now,
            "plan_hash": plan_hash,
            "total": total,
            "invocation": invocation,
        }
        _atomic_write_json(path / "manifest.json", manifest)
        return cls(
            CheckpointSnapshot(path=path, manifest=manifest),
            created_by_current_operation=True,
        )

    @classmethod
    def resume(
        cls,
        *,
        eval_dir: Path,
        reference: Path,
        kind: CheckpointKind,
        plan_hash: str,
    ) -> CheckpointStore:
        snapshot = load_checkpoint(eval_dir, reference, expected_kind=kind)
        status = snapshot.manifest.get("status")
        if status == "complete":
            raise EvalConfigError(f"checkpoint is already complete: {snapshot.path}")
        if snapshot.manifest.get("plan_hash") != plan_hash:
            raise EvalConfigError(
                "checkpoint inputs changed; start a new operation instead of "
                f"resuming {snapshot.path}"
            )
        return cls(snapshot, created_by_current_operation=False)

    @property
    def has_reusable_results(self) -> bool:
        return self._has_reusable_results

    def mark_reusable(self) -> bool:
        if self._has_reusable_results:
            return False
        self._has_reusable_results = True
        return True

    def latest(self, event_type: str) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for event in self._read_events():
            if event.get("type") != event_type:
                continue
            key = event.get("key")
            payload = event.get("payload")
            if not isinstance(key, str) or not isinstance(payload, dict):
                raise EvalConfigError(
                    f"checkpoint contains an invalid {event_type} event: {self.path}"
                )
            latest[key] = payload
        return latest

    def record(self, event_type: str, key: str, payload: dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "key": key,
            "recorded_at": _utc_timestamp(),
            "payload": payload,
        }
        try:
            encoded = (
                json.dumps(
                    event,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise EvalConfigError(
                f"checkpoint result is not JSON serializable: {error}"
            ) from error
        try:
            descriptor = os.open(
                self._events_path,
                os.O_APPEND | os.O_WRONLY | _O_BINARY,
            )
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(descriptor, view)
                    if written == 0:
                        raise OSError("checkpoint append made no progress")
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise EvalConfigError(
                f"could not persist checkpoint result to {self.path}: {error}"
            ) from error

    def mark_complete(self) -> None:
        self.manifest["status"] = "complete"
        self.manifest["updated_at"] = _utc_timestamp()
        _atomic_write_json(self.path / "manifest.json", self.manifest)

    def release(self) -> None:
        self._release_lock(self._lock_path)

    def _release_lock(self, path: Path) -> None:
        try:
            lock = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(lock, dict) and lock.get("token") == self._lock_token:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def discard_if_no_reusable_results(self) -> None:
        if not self._created_by_current_operation or self._has_reusable_results:
            return
        discarded_path = self.path.with_name(
            f".{self.path.name}.{self._lock_token}.discarding"
        )
        try:
            os.replace(self.path, discarded_path)
        except OSError:
            return
        _sync_directory_best_effort(discarded_path.parent)

        contents_removed = True
        for path in (
            discarded_path / self._events_path.name,
            discarded_path / "manifest.json",
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                contents_removed = False
        self._release_lock(discarded_path / self._lock_path.name)
        if not contents_removed:
            return
        try:
            discarded_path.rmdir()
        except OSError:
            return
        _sync_directory_best_effort(discarded_path.parent)

    def _acquire_lock(self) -> None:
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "token": self._lock_token,
                "started_at": _utc_timestamp(),
            },
            ensure_ascii=True,
            sort_keys=True,
        ).encode("utf-8")
        for attempt in range(2):
            try:
                descriptor = os.open(
                    self._lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as error:
                if attempt == 0 and _checkpoint_lock_is_stale(self._lock_path):
                    try:
                        self._lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        raise EvalConfigError(
                            f"could not clear stale checkpoint lock: {self._lock_path}"
                        ) from error
                    continue
                raise EvalConfigError(
                    f"checkpoint is already active in another process: {self.path}"
                ) from error
            except OSError as error:
                raise EvalConfigError(
                    f"could not lock checkpoint {self.path}: {error}"
                ) from error
            try:
                os.write(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return
        raise RuntimeError("internal error: checkpoint lock retry was exhausted")

    def _prepare_event_log(self) -> None:
        created = False
        try:
            try:
                descriptor = os.open(
                    self._events_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_BINARY,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                created = True
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except OSError as error:
            raise EvalConfigError(
                f"could not create checkpoint event log in {self.path}: {error}"
            ) from error
        if created:
            _sync_directory_best_effort(self.path)
        self._truncate_torn_event_tail()

    def _truncate_torn_event_tail(self) -> None:
        descriptor: int | None = None
        try:
            descriptor = os.open(self._events_path, os.O_RDWR | _O_BINARY)
            size = os.lseek(descriptor, 0, os.SEEK_END)
            if size == 0:
                return
            os.lseek(descriptor, -1, os.SEEK_END)
            if os.read(descriptor, 1) == b"\n":
                return

            os.lseek(descriptor, 0, os.SEEK_SET)
            raw = bytearray()
            while len(raw) < size:
                chunk = os.read(descriptor, min(64 * 1024, size - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            complete_length = raw.rfind(b"\n") + 1
            os.ftruncate(descriptor, complete_length)
            os.fsync(descriptor)
        except OSError as error:
            raise EvalConfigError(
                f"could not repair checkpoint event log in {self.path}: {error}"
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _read_events(self) -> list[dict[str, Any]]:
        try:
            raw = self._events_path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError as error:
            raise EvalConfigError(
                f"could not read checkpoint events from {self.path}: {error}"
            ) from error
        if raw and not raw.endswith(b"\n"):
            raise EvalConfigError(
                f"checkpoint event log has an incomplete final record: "
                f"{self._events_path}"
            )
        lines = raw.splitlines(keepends=True)
        events: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise EvalConfigError(
                    f"checkpoint event log is corrupt at line {index + 1}: "
                    f"{self._events_path}: {error}"
                ) from error
            if not isinstance(event, dict):
                raise EvalConfigError(
                    f"checkpoint event at line {index + 1} is not an object: "
                    f"{self._events_path}"
                )
            events.append(event)
        return events


def load_checkpoint(
    eval_dir: Path,
    reference: Path,
    *,
    expected_kind: CheckpointKind,
) -> CheckpointSnapshot:
    path = _resolve_checkpoint_path(eval_dir, reference)
    manifest_path = path / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise EvalConfigError(
            f"could not read checkpoint manifest {manifest_path}: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise EvalConfigError(
            f"invalid checkpoint manifest {manifest_path}: {error}"
        ) from error
    if not isinstance(manifest, dict):
        raise EvalConfigError(f"checkpoint manifest must be an object: {manifest_path}")
    if manifest.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise EvalConfigError(
            f"unsupported checkpoint schema in {manifest_path}: "
            f"{manifest.get('schema_version')!r}"
        )
    if manifest.get("kind") != expected_kind:
        raise EvalConfigError(
            f"checkpoint {path} is for {manifest.get('kind')!r}, not {expected_kind!r}"
        )
    return CheckpointSnapshot(path=path, manifest=manifest)


def checkpoint_plan_hash(
    eval_directory: EvalDirectory, invocation: dict[str, Any]
) -> str:
    cases: list[dict[str, Any]] = []
    for case in eval_directory.cases:
        try:
            source = case.path.read_bytes()
        except OSError as error:
            raise EvalConfigError(
                f"could not fingerprint checkpoint input for {case.name}: {error}"
            ) from error
        if case.remote_video is not None:
            video_fingerprint: dict[str, Any] = {
                "store": case.remote_video.store,
                "key": case.remote_video.key,
                "sha256": case.remote_video.sha256,
            }
        else:
            try:
                video_stat = case.video_path.stat()
            except OSError as error:
                raise EvalConfigError(
                    f"could not fingerprint checkpoint input for {case.name}: {error}"
                ) from error
            video_fingerprint = {
                "path": str(case.video_path.expanduser().resolve()),
                "size": video_stat.st_size,
                "mtime_ns": video_stat.st_mtime_ns,
            }
        cases.append(
            {
                "path": str(case.path.expanduser().resolve()),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "video": video_fingerprint,
            }
        )
    payload = {"invocation": invocation, "cases": cases}
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise EvalConfigError(
            f"eval options cannot be checkpointed as JSON: {error}"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def attach_checkpoint(error: BaseException, checkpoint: CheckpointStore) -> None:
    error.__dict__["checkpoint_path"] = checkpoint.path


def checkpoint_path_from_error(error: BaseException) -> Path | None:
    value = getattr(error, "checkpoint_path", None)
    return value if isinstance(value, Path) else None


def _resolve_checkpoint_path(eval_dir: Path, reference: Path) -> Path:
    expanded = reference.expanduser()
    if expanded.is_absolute() or expanded.parent != Path("."):
        return expanded.resolve()
    direct = expanded.resolve()
    if direct.exists():
        return direct
    return _checkpoint_root(eval_dir) / expanded.name


def _checkpoint_root(eval_dir: Path) -> Path:
    return eval_dir.expanduser().resolve() / "runs" / "checkpoints"


def _checkpoint_lock_is_stale(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        try:
            return time.time() - path.stat().st_mtime > 5.0
        except OSError:
            return True
    pid = value.get("pid") if isinstance(value, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return True
    return not _pid_exists(pid)


def _pid_exists(pid: int) -> bool:
    if _WINDOWS:
        return _windows_pid_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _windows_pid_exists(pid: int) -> bool:
    # os.kill(pid, 0) terminates rather than probes a process on Windows. Query a
    # minimal process handle instead, treating access failures as active locks.
    import ctypes
    from ctypes import wintypes

    windows_ctypes: Any = ctypes
    win_dll = windows_ctypes.WinDLL
    get_last_error = windows_ctypes.get_last_error
    kernel32 = win_dll("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    synchronize = 0x00100000
    error_invalid_parameter = 87
    wait_object_0 = 0
    handle = open_process(synchronize, False, pid)
    if not handle:
        return get_last_error() != error_invalid_parameter
    try:
        return wait_for_single_object(handle, 0) != wait_object_0
    finally:
        close_handle(handle)


def _new_checkpoint_id(kind: CheckpointKind) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{kind}-{timestamp}-{secrets.token_hex(4)}"


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as error:
        raise EvalConfigError(
            f"checkpoint manifest is not JSON serializable: {error}"
        ) from error
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory_best_effort(path.parent)
    except OSError as error:
        raise EvalConfigError(
            f"could not write checkpoint manifest {path}: {error}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _sync_directory_best_effort(directory: Path) -> None:
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if directory_flag is None:
        return
    try:
        descriptor = os.open(directory, directory_flag | os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
