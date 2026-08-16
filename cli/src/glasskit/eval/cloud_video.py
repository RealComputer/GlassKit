from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .models import RemoteVideo, VideoStore, VideoStoreError

CACHE_ENV_VAR = "GLASSKIT_EVAL_CACHE_DIR"
_LOCK_STALE_AFTER_S = 60 * 60
_LOCK_TIMEOUT_S = 5 * 60
_COPY_CHUNK_SIZE = 1024 * 1024
_SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


@dataclass(frozen=True)
class UploadResult:
    store: str
    key: str
    sha256: str
    size_bytes: int
    already_existed: bool


def video_cache_dir() -> Path:
    override = os.environ.get(CACHE_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "GlassKit" / "Cache" / "eval" / "videos"
    if sys_platform() == "darwin":
        return Path.home() / "Library" / "Caches" / "glasskit" / "eval" / "videos"
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "glasskit" / "eval" / "videos"


def sys_platform() -> str:
    # Kept behind a tiny function so platform-specific cache defaults are easy to test.
    import sys

    return sys.platform


def cached_video_path(video: RemoteVideo) -> Path:
    suffix = Path(video.key).suffix.lower()
    return video_cache_dir() / "sha256" / video.sha256[:2] / f"{video.sha256}{suffix}"


def materialize_video(video: RemoteVideo, store: VideoStore) -> Path:
    destination = cached_video_path(video)
    if _verified_file(destination, video.sha256):
        return destination

    try:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as error:
        raise VideoStoreError(
            f"could not create video cache directory {destination.parent}: {error}"
        ) from error
    with _cache_lock(destination):
        if _verified_file(destination, video.sha256):
            return destination
        temporary = destination.with_name(
            f".{destination.name}.part-{os.getpid()}-{uuid.uuid4().hex}"
        )
        try:
            if store.public_base_url is not None:
                _download_public(store, video.key, temporary)
            else:
                _download_s3(store, video.key, temporary)
            actual = sha256_file(temporary)
            if actual != video.sha256:
                raise VideoStoreError(
                    f"downloaded video {video.display_name!r} has SHA-256 {actual}, "
                    f"expected {video.sha256}"
                )
            try:
                os.chmod(temporary, 0o600)
                os.replace(temporary, destination)
            except OSError as error:
                raise VideoStoreError(
                    f"could not install cached video {destination}: {error}"
                ) from error
            _write_verification_record(destination, video.sha256)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
    return destination


def upload_video(
    source: Path,
    store: VideoStore,
    *,
    key: str | None = None,
) -> UploadResult:
    path = source.expanduser().resolve()
    if not path.exists():
        raise VideoStoreError(f"video file does not exist: {path}")
    if not path.is_file():
        raise VideoStoreError(f"video path is not a file: {path}")
    _require_video_suffix(path.name)
    digest = sha256_file(path)
    object_key = key.strip() if key is not None else default_object_key(path, digest)
    if not object_key:
        raise VideoStoreError("object key must not be empty")
    _require_video_suffix(object_key)
    try:
        size = path.stat().st_size
    except OSError as error:
        raise VideoStoreError(
            f"could not inspect video file {path}: {error}"
        ) from error
    client = _s3_client(store)
    existing = _head_object(client, store.bucket, object_key)
    if existing is not None:
        metadata = existing.get("Metadata") or {}
        if (
            existing.get("ContentLength") == size
            and metadata.get("sha256", "").lower() == digest
        ):
            return UploadResult(store.name, object_key, digest, size, True)
        raise VideoStoreError(
            f"refusing to overwrite existing object {store.name}:{object_key}"
        )

    extra_args: dict[str, Any] = {"Metadata": {"sha256": digest}}
    content_type = mimetypes.guess_type(path.name)[0]
    if content_type is not None:
        extra_args["ContentType"] = content_type
    try:
        client.upload_file(str(path), store.bucket, object_key, ExtraArgs=extra_args)
    except Exception as error:
        raise VideoStoreError(
            f"could not upload {path} to {store.name}:{object_key}: {error}"
        ) from error

    uploaded = _head_object(client, store.bucket, object_key)
    if uploaded is None:
        raise VideoStoreError(
            f"uploaded object could not be verified: {store.name}:{object_key}"
        )
    metadata = uploaded.get("Metadata") or {}
    if (
        uploaded.get("ContentLength") != size
        or metadata.get("sha256", "").lower() != digest
    ):
        raise VideoStoreError(
            f"uploaded object metadata did not verify: {store.name}:{object_key}"
        )
    return UploadResult(store.name, object_key, digest, size, False)


def default_object_key(source: Path, digest: str) -> str:
    return f"{digest}{source.suffix.lower()}"


def _require_video_suffix(name: str) -> None:
    if Path(name).suffix.lower() in _SUPPORTED_VIDEO_SUFFIXES:
        return
    supported = ", ".join(sorted(_SUPPORTED_VIDEO_SUFFIXES))
    raise VideoStoreError(
        f"unsupported video file type for {name}; supported suffixes: {supported}"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            while chunk := file.read(_COPY_CHUNK_SIZE):
                digest.update(chunk)
    except OSError as error:
        raise VideoStoreError(
            f"could not read {path} to calculate SHA-256: {error}"
        ) from error
    return digest.hexdigest()


def prune_video_cache(*, remove_verified: bool = False) -> tuple[int, int]:
    root = video_cache_dir()
    if not root.exists():
        return 0, 0
    removed_files = 0
    removed_bytes = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        is_temporary = ".part-" in path.name or path.name.endswith(".lock")
        if is_temporary:
            try:
                if path.name.endswith(".lock"):
                    is_stale = _cache_lock_is_stale(path)
                else:
                    lock = _lock_for_temporary(path)
                    is_stale = (
                        not lock.exists() or _cache_lock_is_stale(lock)
                    ) and time.time() - path.stat().st_mtime > _LOCK_STALE_AFTER_S
            except FileNotFoundError:
                continue
            if not is_stale:
                continue
        if not remove_verified and not is_temporary:
            continue
        try:
            size = path.stat().st_size
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise VideoStoreError(
                f"could not remove cached file {path}: {error}"
            ) from error
        removed_files += 1
        removed_bytes += size
    _remove_empty_directories(root)
    return removed_files, removed_bytes


def _verified_file(path: Path, expected_sha256: str) -> bool:
    if not path.is_file():
        return False
    try:
        stat = path.stat()
    except OSError as error:
        raise VideoStoreError(
            f"could not inspect cached video {path}: {error}"
        ) from error
    if _verification_record_matches(
        path, expected_sha256, stat.st_size, stat.st_mtime_ns
    ):
        return True
    actual = sha256_file(path)
    if actual == expected_sha256:
        _write_verification_record(path, expected_sha256)
        return True
    try:
        path.unlink()
        _verification_record_path(path).unlink(missing_ok=True)
    except OSError as error:
        raise VideoStoreError(
            f"could not replace invalid cached video {path}: {error}"
        ) from error
    return False


def _verification_record_matches(
    path: Path,
    expected_sha256: str,
    size: int,
    mtime_ns: int,
) -> bool:
    try:
        value = json.loads(_verification_record_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and value == {
        "sha256": expected_sha256,
        "size": size,
        "mtime_ns": mtime_ns,
    }


def _write_verification_record(path: Path, sha256: str) -> None:
    try:
        stat = path.stat()
    except OSError:
        return
    record = {
        "sha256": sha256,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    destination = _verification_record_path(path)
    temporary = destination.with_name(
        f".{destination.name}.part-{os.getpid()}-{uuid.uuid4().hex}"
    )
    try:
        temporary.write_text(
            json.dumps(record, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _verification_record_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.verified.json")


@contextmanager
def _cache_lock(destination: Path) -> Iterator[None]:
    lock = destination.with_name(f".{destination.name}.lock")
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _cache_lock_is_stale(lock):
                try:
                    lock.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise VideoStoreError(
                    f"timed out waiting for video cache lock: {lock}"
                ) from None
            time.sleep(0.1)
            continue
        except OSError as error:
            raise VideoStoreError(
                f"could not lock video cache file {destination}: {error}"
            ) from error
        else:
            with os.fdopen(descriptor, "w", encoding="ascii") as file:
                file.write(f"{os.getpid()}\n")
            break
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _download_public(store: VideoStore, key: str, destination: Path) -> None:
    assert store.public_base_url is not None
    url = f"{store.public_base_url.rstrip('/')}/{quote(key, safe='/')}"
    request = Request(url, headers={"User-Agent": "glasskit-eval"})
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as file:
            shutil.copyfileobj(response, file, length=_COPY_CHUNK_SIZE)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise VideoStoreError(
            f"could not download public video {store.name}:{key} from {url}: {error}"
        ) from error


def _download_s3(store: VideoStore, key: str, destination: Path) -> None:
    client = _s3_client(store)
    try:
        client.download_file(store.bucket, key, str(destination))
    except Exception as error:
        raise VideoStoreError(
            f"could not download private video {store.name}:{key}: {error}"
        ) from error


def _s3_client(store: VideoStore) -> Any:
    try:
        import boto3
    except ImportError as error:  # Defensive for source checkouts with a stale env.
        raise VideoStoreError(
            "S3-compatible video storage requires boto3; reinstall GlassKit "
            "dependencies"
        ) from error

    kwargs: dict[str, Any] = {"region_name": store.region}
    if store.endpoint_url is not None:
        kwargs["endpoint_url"] = store.endpoint_url
    credential_names = (
        ("aws_access_key_id", store.access_key_id_env),
        ("aws_secret_access_key", store.secret_access_key_env),
        ("aws_session_token", store.session_token_env),
    )
    for argument, env_name in credential_names:
        if env_name is None:
            continue
        value = os.environ.get(env_name)
        if not value:
            raise VideoStoreError(
                f"authenticated access to video store {store.name!r} requires "
                f"environment variable {env_name}"
            )
        kwargs[argument] = value
    try:
        return boto3.client("s3", **kwargs)
    except Exception as error:
        raise VideoStoreError(
            f"could not configure S3-compatible video store {store.name!r}: {error}"
        ) from error


def _head_object(client: Any, bucket: str, key: str) -> Mapping[str, Any] | None:
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except Exception as error:
        status = (
            getattr(error, "response", {})
            .get("ResponseMetadata", {})
            .get("HTTPStatusCode")
        )
        code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise VideoStoreError(
            f"could not inspect s3://{bucket}/{key}: {error}"
        ) from error
    return response


def _remove_empty_directories(root: Path) -> None:
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in directories:
        try:
            path.rmdir()
        except OSError:
            pass


def _lock_for_temporary(path: Path) -> Path:
    destination_name = path.name.split(".part-", maxsplit=1)[0]
    return path.with_name(f"{destination_name}.lock")


def _cache_lock_is_stale(path: Path) -> bool:
    try:
        pid = int(path.read_text(encoding="ascii").strip())
    except (OSError, UnicodeError, ValueError):
        try:
            return time.time() - path.stat().st_mtime > _LOCK_STALE_AFTER_S
        except OSError:
            return True
    if pid <= 0:
        return True
    if os.name == "nt":
        # os.kill(pid, 0) can terminate a process on Windows, so fall back to age.
        try:
            return time.time() - path.stat().st_mtime > _LOCK_STALE_AFTER_S
        except OSError:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False
