from __future__ import annotations

import email.utils
import hashlib
import http.server
import importlib.resources
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import threading
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from time import time as wall_time
from typing import Any
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from ..models import EvalConfigError
from .documents import ReviewRepository
from .models import (
    ErrorContent,
    ErrorDetail,
    ErrorResponse,
    ReplaceSamplesRequest,
    ReviewAPIError,
    TransportModel,
)

MAX_JSON_BODY_BYTES = 2 * 1024 * 1024
STREAM_CHUNK_BYTES = 64 * 1024
_HASHED_ASSET = re.compile(r"-[A-Za-z0-9_-]{8,}\.")
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; media-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@dataclass(frozen=True)
class StaticAsset:
    content: bytes
    content_type: str
    cache_control: str


@dataclass(frozen=True)
class _VideoFileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    generation: int | None


@dataclass(frozen=True)
class _CachedVideoMetadata:
    identity: _VideoFileIdentity
    etag: str
    last_modified_seconds: int


class ReviewServer(http.server.ThreadingHTTPServer):
    """Threaded loopback server carrying review API and packaged assets."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        repository: ReviewRepository,
        static_assets: dict[str, StaticAsset],
        *,
        write_token: str,
    ) -> None:
        self.repository = repository
        self.static_assets = static_assets
        self.write_token = write_token
        self._video_metadata_cache: dict[Path, _CachedVideoMetadata] = {}
        self._video_metadata_lock = threading.Lock()
        super().__init__(server_address, ReviewRequestHandler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def video_metadata(
        self, path: Path, *, response_time: int
    ) -> tuple[os.stat_result, str, int]:
        with self._video_metadata_lock:
            while True:
                path_stat = path.stat()
                identity = _video_file_identity(path_stat)
                cached = self._video_metadata_cache.get(path)
                if cached is not None and cached.identity == identity:
                    return path_stat, cached.etag, cached.last_modified_seconds

                with path.open("rb") as stream:
                    opened_identity = _video_file_identity(os.fstat(stream.fileno()))
                    if opened_identity != identity:
                        continue
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    hashed_identity = _video_file_identity(os.fstat(stream.fileno()))

                current_stat = path.stat()
                current_identity = _video_file_identity(current_stat)
                if opened_identity != hashed_identity or identity != current_identity:
                    continue

                etag = f'"sha256-{digest}"'
                last_modified_seconds = min(int(current_stat.st_mtime), response_time)
                self._video_metadata_cache[path] = _CachedVideoMetadata(
                    identity=current_identity,
                    etag=etag,
                    last_modified_seconds=last_modified_seconds,
                )
                return current_stat, etag, last_modified_seconds


class ReviewRequestHandler(http.server.BaseHTTPRequestHandler):
    server: ReviewServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch(send_body=False)

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch_put()

    def do_POST(self) -> None:  # noqa: N802
        self._unsupported_method()

    def do_DELETE(self) -> None:  # noqa: N802
        self._unsupported_method()

    def do_PATCH(self) -> None:  # noqa: N802
        self._unsupported_method()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._unsupported_method()

    def do_TRACE(self) -> None:  # noqa: N802
        self._unsupported_method()

    def do_CONNECT(self) -> None:  # noqa: N802
        self._unsupported_method()

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        """Keep stdlib-generated protocol errors in the API error envelope."""

        self.close_connection = True
        try:
            phrase = HTTPStatus(code).phrase
        except ValueError:
            phrase = "HTTP error"
        self._send_error(
            code,
            "http_error",
            message or phrase,
            send_body=getattr(self, "command", None) != "HEAD",
        )

    def log_message(self, format: str, *args: object) -> None:
        # The CLI prints one stable launch URL; routine browser traffic stays quiet.
        return

    def _dispatch(self, *, send_body: bool) -> None:
        if not self._host_is_valid():
            self._send_error(
                400,
                "invalid_host",
                "Host must identify this loopback review server and bound port.",
                send_body=send_body,
            )
            return
        encoded_path = urlsplit(self.path).path
        segments = _route_segments(encoded_path)
        try:
            if segments == ["api", "suite"] and send_body:
                self._send_model(
                    200,
                    self.server.repository.suite_document(
                        write_token=self.server.write_token
                    ),
                )
                return
            if len(segments) == 3 and segments[:2] == ["api", "cases"] and send_body:
                self._send_model(200, self.server.repository.case_document(segments[2]))
                return
            if (
                len(segments) == 4
                and segments[:2] == ["api", "cases"]
                and segments[3] == "video"
            ):
                self._serve_video(segments[2], send_body=send_body)
                return
            if segments and segments[0] == "api":
                self._send_error(
                    404,
                    "route_not_found",
                    "No review API route matches this request.",
                    send_body=send_body,
                )
                return
            self._serve_static(encoded_path, send_body=send_body)
        except ReviewAPIError as error:
            self._send_error(
                error.status,
                error.code,
                error.message,
                details=error.details,
                send_body=send_body,
            )
        except (EvalConfigError, OSError) as error:
            self._send_error(
                500,
                "suite_unavailable",
                f"The review suite could not be refreshed: {error}",
                send_body=send_body,
            )
        except Exception:
            self._send_error(
                500,
                "internal_error",
                "The review server encountered an unexpected local error.",
                send_body=send_body,
            )

    def _dispatch_put(self) -> None:
        # Rejecting a request before consuming its body must not leave unread bytes
        # to be interpreted as another request on a persistent connection.
        self.close_connection = True
        if not self._host_is_valid():
            self._send_error(
                400,
                "invalid_host",
                "Host must identify this loopback review server and bound port.",
            )
            return
        segments = _route_segments(urlsplit(self.path).path)
        if not (
            len(segments) == 4
            and segments[:2] == ["api", "cases"]
            and segments[3] == "samples"
        ):
            self._send_error(
                404,
                "route_not_found",
                "No review API route matches this request.",
            )
            return
        supplied_token = self.headers.get("X-GlassKit-Write-Token", "")
        if not secrets.compare_digest(supplied_token, self.server.write_token):
            self._send_error(
                403,
                "invalid_write_token",
                "A valid review write token is required.",
            )
            return
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            self._send_error(
                415,
                "unsupported_media_type",
                "PUT requests require Content-Type: application/json.",
            )
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_error(
                400,
                "invalid_content_length",
                "A valid Content-Length header is required.",
            )
            return
        if content_length < 0:
            self._send_error(
                400, "invalid_content_length", "Content-Length cannot be negative."
            )
            return
        if content_length > MAX_JSON_BODY_BYTES:
            self._send_error(
                413,
                "request_too_large",
                f"JSON request bodies are limited to {MAX_JSON_BODY_BYTES} bytes.",
            )
            return
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(
                body.decode("utf-8"),
                parse_constant=lambda value: _reject_json_constant(value),
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            RecursionError,
        ) as error:
            self._send_error(
                400,
                "malformed_json",
                f"Request body is not valid UTF-8 JSON: {error}",
            )
            return
        try:
            request = ReplaceSamplesRequest.model_validate(payload)
        except ValidationError as error:
            details = [
                ErrorDetail(
                    path=".".join(str(part) for part in issue["loc"]),
                    message=issue["msg"],
                )
                for issue in error.errors(include_url=False)
            ]
            self._send_error(
                422,
                "invalid_request",
                "The sample replacement request is invalid.",
                details=details,
            )
            return
        try:
            document = self.server.repository.replace_samples(segments[2], request)
        except ReviewAPIError as error:
            self._send_error(
                error.status,
                error.code,
                error.message,
                details=error.details,
            )
            return
        except Exception:
            self._send_error(
                500,
                "internal_error",
                "The review server encountered an unexpected local error.",
            )
            return
        self._send_model(200, document)

    def _unsupported_method(self) -> None:
        self.close_connection = True
        if not self._host_is_valid():
            self._send_error(
                400,
                "invalid_host",
                "Host must identify this loopback review server and bound port.",
            )
            return
        self._send_error(
            405, "method_not_allowed", "This review route does not allow that method."
        )

    def _serve_static(self, encoded_path: str, *, send_body: bool) -> None:
        decoded_path = unquote(encoded_path)
        key = "/index.html" if decoded_path == "/" else decoded_path
        asset = self.server.static_assets.get(key)
        if asset is None:
            asset = self.server.static_assets["/index.html"]
        self._send_bytes(
            200,
            asset.content,
            content_type=asset.content_type,
            cache_control=asset.cache_control,
            send_body=send_body,
        )

    def _serve_video(self, case_id: str, *, send_body: bool) -> None:
        path = self.server.repository.video_path(case_id)
        stat_result, etag, last_modified_seconds = self.server.video_metadata(
            path,
            response_time=int(wall_time()),
        )
        size = stat_result.st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        last_modified = email.utils.formatdate(last_modified_seconds, usegmt=True)
        common_headers = {
            "Accept-Ranges": "bytes",
            "ETag": etag,
            "Last-Modified": last_modified,
            "Cache-Control": "private, max-age=0",
        }

        if_match_values = self.headers.get_all("If-Match") or []
        if if_match_values:
            if not _etag_list_matches(", ".join(if_match_values), etag, weak=False):
                self._send_video_precondition_response(412, common_headers)
                return
        else:
            unmodified_since_values = self.headers.get_all("If-Unmodified-Since") or []
            if len(unmodified_since_values) == 1:
                unmodified_since = _parse_http_date(unmodified_since_values[0])
                if (
                    unmodified_since is not None
                    and last_modified_seconds > unmodified_since
                ):
                    self._send_video_precondition_response(412, common_headers)
                    return

        if_none_match_values = self.headers.get_all("If-None-Match") or []
        if if_none_match_values:
            if _etag_list_matches(", ".join(if_none_match_values), etag, weak=True):
                self._send_video_precondition_response(304, common_headers)
                return
        else:
            modified_since_values = self.headers.get_all("If-Modified-Since") or []
            if len(modified_since_values) == 1:
                modified_since = _parse_http_date(modified_since_values[0])
                if (
                    modified_since is not None
                    and last_modified_seconds <= modified_since
                ):
                    self._send_video_precondition_response(304, common_headers)
                    return

        range_values = self.headers.get_all("Range") or []
        range_header = (
            ", ".join(range_values) if self.command == "GET" and range_values else None
        )
        if_range_values = self.headers.get_all("If-Range") or []
        if range_header is None or (
            if_range_values
            and (
                len(if_range_values) != 1
                or not _if_range_matches(if_range_values[0], etag=etag)
            )
        ):
            self._send_file_range(
                path,
                status=200,
                start=0,
                end=size - 1,
                size=size,
                content_type=content_type,
                headers=common_headers,
                send_body=send_body,
            )
            return
        selected = _parse_byte_range(range_header, size)
        if selected is None:
            headers = dict(common_headers)
            headers["Content-Range"] = f"bytes */{size}"
            self._send_bytes(
                416,
                b"",
                content_type="application/octet-stream",
                cache_control=headers.pop("Cache-Control"),
                extra_headers=headers,
                send_body=False,
            )
            return
        start, end = selected
        headers = dict(common_headers)
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._send_file_range(
            path,
            status=206,
            start=start,
            end=end,
            size=size,
            content_type=content_type,
            headers=headers,
            send_body=send_body,
        )

    def _send_video_precondition_response(
        self, status: int, headers: dict[str, str]
    ) -> None:
        self.send_response(status)
        if status != 304:
            self.send_header("Content-Length", "0")
        for key in ("ETag", "Last-Modified", "Cache-Control"):
            self.send_header(key, headers[key])
        self._send_security_headers()
        self.end_headers()

    def _send_file_range(
        self,
        path: Path,
        *,
        status: int,
        start: int,
        end: int,
        size: int,
        content_type: str,
        headers: dict[str, str],
        send_body: bool,
    ) -> None:
        length = max(0, end - start + 1) if size else 0
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for key, value in headers.items():
            self.send_header(key, value)
        self._send_security_headers()
        self.end_headers()
        if not send_body or length == 0:
            return
        remaining = length
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                while remaining:
                    chunk = stream.read(min(STREAM_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_model(self, status: int, model: TransportModel) -> None:
        content = json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._send_bytes(
            status,
            content,
            content_type="application/json; charset=utf-8",
            cache_control="no-store",
        )

    def _send_error(
        self,
        status: int,
        code: str,
        message: str,
        *,
        details: list[ErrorDetail] | None = None,
        send_body: bool = True,
    ) -> None:
        model = ErrorResponse(
            error=ErrorContent(
                code=code,
                message=message,
                details=details or [],
            )
        )
        content = json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._send_bytes(
            status,
            content,
            content_type="application/json; charset=utf-8",
            cache_control="no-store",
            send_body=send_body,
        )

    def _send_bytes(
        self,
        status: int,
        content: bytes,
        *,
        content_type: str,
        cache_control: str,
        extra_headers: dict[str, str] | None = None,
        send_body: bool = True,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache_control)
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self._send_security_headers()
        self.end_headers()
        if send_body and content:
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                return

    def _send_security_headers(self) -> None:
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)

    def _host_is_valid(self) -> bool:
        value = self.headers.get("Host")
        if not value:
            return False
        try:
            parsed = urlsplit(f"//{value}")
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            return False
        if (
            host is None
            or (port if port is not None else 80) != self.server.port
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return False
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False


def create_review_server(
    eval_dir: Path,
    *,
    port: int = 0,
    static_dir: Any | None = None,
    write_token: str | None = None,
    repository: ReviewRepository | None = None,
) -> ReviewServer:
    if not 0 <= port <= 65535:
        raise EvalConfigError("port must be between 0 and 65535")
    root = static_dir
    if root is None:
        root = importlib.resources.files("glasskit.eval.review").joinpath("static")
    assets = _load_static_assets(root)
    if "/index.html" not in assets:
        raise EvalConfigError(
            "review UI static/index.html is missing; from the CLI source directory, "
            "run `cd review-ui && npm ci && npm run build`"
        )
    resolved_repository = repository or ReviewRepository(eval_dir)
    return ReviewServer(
        ("127.0.0.1", port),
        resolved_repository,
        assets,
        write_token=write_token or secrets.token_urlsafe(32),
    )


def _load_static_assets(root: Any) -> dict[str, StaticAsset]:
    try:
        root_is_dir = root.is_dir()
    except (AttributeError, OSError):
        root_is_dir = False
    if not root_is_dir:
        raise EvalConfigError(
            "review UI static assets are missing; from the CLI source directory, "
            "run `cd review-ui && npm ci && npm run build`"
        )

    assets: dict[str, StaticAsset] = {}

    def visit(directory: Any, prefix: str) -> None:
        for child in directory.iterdir():
            relative = f"{prefix}/{child.name}"
            if child.is_dir():
                visit(child, relative)
            elif child.is_file():
                content_type = (
                    mimetypes.guess_type(child.name)[0] or "application/octet-stream"
                )
                immutable = _HASHED_ASSET.search(child.name) is not None
                assets[relative] = StaticAsset(
                    content=child.read_bytes(),
                    content_type=content_type,
                    cache_control=(
                        "public, max-age=31536000, immutable"
                        if immutable
                        else "no-store"
                    ),
                )

    visit(root, "")
    return assets


def _video_file_identity(stat_result: os.stat_result) -> _VideoFileIdentity:
    return _VideoFileIdentity(
        device=stat_result.st_dev,
        inode=stat_result.st_ino,
        size=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
        ctime_ns=stat_result.st_ctime_ns,
        generation=getattr(stat_result, "st_gen", None),
    )


def _route_segments(encoded_path: str) -> list[str]:
    if encoded_path in {"", "/"}:
        return []
    return [unquote(segment) for segment in encoded_path.lstrip("/").split("/")]


def _parse_byte_range(value: str, size: int) -> tuple[int, int] | None:
    if size <= 0 or not value.startswith("bytes="):
        return None
    spec = value[6:].strip()
    if not spec or "," in spec or spec.count("-") != 1:
        return None
    start_text, end_text = (part.strip() for part in spec.split("-", 1))
    try:
        if not start_text:
            if not _is_ascii_digits(end_text):
                return None
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            start = max(0, size - suffix_length)
            return start, size - 1
        if not _is_ascii_digits(start_text):
            return None
        start = int(start_text)
        if start < 0 or start >= size:
            return None
        if not end_text:
            return start, size - 1
        if not _is_ascii_digits(end_text):
            return None
        end = int(end_text)
        if end < start:
            return None
        return start, min(end, size - 1)
    except ValueError:
        return None


def _etag_list_matches(value: str, current: str, *, weak: bool) -> bool:
    if value.strip() == "*":
        return True
    current_value = current.removeprefix("W/") if weak else current
    for raw_candidate in value.split(","):
        candidate = raw_candidate.strip()
        if weak:
            candidate = candidate.removeprefix("W/")
        elif candidate.startswith("W/"):
            continue
        if candidate == current_value:
            return True
    return False


def _if_range_matches(value: str, *, etag: str) -> bool:
    # HTTP dates have only one-second resolution, so the file's Last-Modified
    # value cannot prove byte-for-byte identity across rapid replacements.
    return value.strip() == etag


def _parse_http_date(value: str) -> int | None:
    try:
        parsed = email.utils.parsedate_tz(value)
        return int(email.utils.mktime_tz(parsed)) if parsed is not None else None
    except (OverflowError, TypeError, ValueError):
        return None


def _is_ascii_digits(value: str) -> bool:
    return bool(value) and all("0" <= character <= "9" for character in value)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")
