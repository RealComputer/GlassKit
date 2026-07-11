from __future__ import annotations

import email.utils
import hashlib
import http.client
import json
import os
import shutil
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import pytest

import glasskit.eval.review.server as review_server_module
from glasskit.eval.models import EvalConfigError
from glasskit.eval.review.server import ReviewServer, create_review_server

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_missing_static_assets_explain_source_checkout_build(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)

    with pytest.raises(EvalConfigError, match=r"npm install && npm run build"):
        create_review_server(eval_dir, static_dir=tmp_path / "missing-static")


@pytest.mark.parametrize(
    "disconnect_error",
    [BrokenPipeError(), ConnectionAbortedError(), ConnectionResetError()],
)
def test_client_disconnects_do_not_emit_server_tracebacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    disconnect_error: OSError,
) -> None:
    server = create_review_server(
        _copy_fixtures(tmp_path),
        static_dir=_static_dir(tmp_path),
        write_token="write-secret",
    )

    def raise_disconnect(*_args: object) -> None:
        raise disconnect_error

    monkeypatch.setattr(server, "finish_request", raise_disconnect)
    monkeypatch.setattr(server, "shutdown_request", lambda _request: None)
    try:
        server.process_request_thread(server.socket, ("127.0.0.1", 12345))
    finally:
        server.server_close()

    assert capsys.readouterr().err == ""


def test_unexpected_request_errors_still_emit_server_tracebacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = create_review_server(
        _copy_fixtures(tmp_path),
        static_dir=_static_dir(tmp_path),
        write_token="write-secret",
    )

    def raise_unexpected(*_args: object) -> None:
        raise RuntimeError("unexpected request failure")

    monkeypatch.setattr(server, "finish_request", raise_unexpected)
    monkeypatch.setattr(server, "shutdown_request", lambda _request: None)
    try:
        server.process_request_thread(server.socket, ("127.0.0.1", 12345))
    finally:
        server.server_close()

    stderr = capsys.readouterr().err
    assert "RuntimeError: unexpected request failure" in stderr


def test_eval_directory_static_security_and_host_validation(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    (eval_dir / "cases" / "invalid-encoding.yaml").write_bytes(b"video: \xff\n")
    static_dir = _static_dir(tmp_path)
    with _running_server(eval_dir, static_dir) as server:
        status, headers, body = _request(server, "GET", "/api/eval-directory")
        eval_directory = json.loads(body)
        assert status == 200
        assert eval_directory["write_token"] == "write-secret"
        invalid = next(
            case
            for case in eval_directory["cases"]
            if case["id"] == "invalid-encoding.yaml"
        )
        assert invalid["status"] == "blocked"
        assert invalid["error"]["code"] == "invalid_encoding"
        assert server.port > 0
        assert headers["cache-control"] == "no-store"
        assert headers["content-security-policy"].startswith("default-src 'self'")

        status, headers, body = _request(server, "GET", "/")
        assert status == 200
        assert body == b"<html>review</html>"
        assert headers["cache-control"] == "no-store"

        status, headers, body = _request(server, "GET", "/assets/app-abcdefgh.js")
        assert status == 200
        assert body == b"console.log('review')"
        assert headers["cache-control"] == ("public, max-age=31536000, immutable")

        status, _headers, body = _request(server, "GET", "/nested/client/route")
        assert status == 200
        assert body == b"<html>review</html>"

        status, _headers, body = _request(
            server,
            "GET",
            "/api/eval-directory",
            headers={"Host": f"example.com:{server.port}"},
            skip_host=True,
        )
        assert status == 400
        assert json.loads(body)["error"]["code"] == "invalid_host"

        status, _headers, body = _request(
            server,
            "GET",
            "/api/eval-directory",
            headers={"Host": f"127.0.0.1:{server.port + 1}"},
            skip_host=True,
        )
        assert status == 400
        assert json.loads(body)["error"]["code"] == "invalid_host"

        status, _headers, body = _request(
            server,
            "GET",
            "/api/eval-directory",
            skip_host=True,
        )
        assert status == 400
        assert json.loads(body)["error"]["code"] == "invalid_host"


def test_unsafe_partial_video_path_stays_isolated_in_blocked_document(
    tmp_path: Path,
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    (eval_dir / "cases" / "unsafe-video.yaml").write_text(
        'video: "\\uD800"\ntargets: {}\n',
        encoding="utf-8",
    )

    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        status, _headers, body = _request(
            server,
            "GET",
            "/api/case-files/unsafe-video.yaml",
        )

    document = json.loads(body)
    assert status == 200
    assert document["status"] == "blocked"
    assert document["video"] is None
    assert document["load_error"]["code"] == "invalid_case"


def test_unknown_path_like_case_and_write_token_rejections(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        encoded = quote("../assembly.yaml", safe="")
        status, _headers, body = _request(server, "GET", f"/api/case-files/{encoded}")
        assert status == 404
        assert json.loads(body)["error"]["code"] == "case_file_not_found"

        payload = json.dumps({"targets": {}}).encode()
        status, _headers, body = _request(
            server,
            "PUT",
            "/api/case-files/assembly.yaml/samples",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        assert status == 403
        assert json.loads(body)["error"]["code"] == "invalid_write_token"

        status, _headers, _body = _request(
            server,
            "PUT",
            "/api/case-files/assembly.yaml/samples",
            body=payload,
            headers={
                "Content-Type": "text/plain",
                "X-GlassKit-Write-Token": "write-secret",
            },
        )
        assert status == 415

        status, _headers, body = _request(
            server,
            "PUT",
            "/api/case-files/assembly.yaml/samples",
            body=b"",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(2 * 1024 * 1024 + 1),
                "X-GlassKit-Write-Token": "write-secret",
            },
        )
        assert status == 413
        assert json.loads(body)["error"]["code"] == "request_too_large"

        status, headers, body = _request(server, "TRACE", "/api/eval-directory")
        assert status == 405
        assert headers["content-type"].startswith("application/json")
        assert "content-security-policy" in headers
        assert json.loads(body)["error"]["code"] == "method_not_allowed"

        nested_json = (b"[" * 10_000) + b"0" + (b"]" * 10_000)
        status, _headers, body = _request(
            server,
            "PUT",
            "/api/case-files/assembly.yaml/samples",
            body=nested_json,
            headers={
                "Content-Type": "application/json",
                "X-GlassKit-Write-Token": "write-secret",
            },
        )
        assert status == 400
        assert json.loads(body)["error"]["code"] == "malformed_json"


def test_video_full_head_and_byte_ranges(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    expected = (tmp_path / "fixtures" / "videos" / "two-state-64x64.mp4").read_bytes()
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        route = "/api/case-files/assembly.yaml/video"
        status, headers, body = _request(server, "GET", route)
        assert status == 200
        assert body == expected
        assert headers["accept-ranges"] == "bytes"
        assert headers["etag"] == f'"sha256-{hashlib.sha256(expected).hexdigest()}"'
        assert headers["last-modified"].endswith(" GMT")
        assert int(headers["content-length"]) == len(expected)

        status, headers, body = _request(server, "HEAD", route)
        assert status == 200
        assert body == b""
        assert int(headers["content-length"]) == len(expected)

        status, headers, body = _request(
            server, "HEAD", route, headers={"Range": "bytes=0-9"}
        )
        assert status == 200
        assert body == b""
        assert int(headers["content-length"]) == len(expected)
        assert "content-range" not in headers

        for value, selected in (
            ("bytes=0-9", expected[:10]),
            ("bytes=10-", expected[10:]),
            ("bytes=-12", expected[-12:]),
        ):
            status, headers, body = _request(
                server, "GET", route, headers={"Range": value}
            )
            assert status == 206
            assert body == selected
            assert headers["content-range"].startswith("bytes ")

        for value in (
            "bytes=999999999-",
            "bytes=0-1,3-4",
            "bytes=+1-2",
            "bytes=1-+2",
            "items=0-2",
        ):
            status, headers, body = _request(
                server, "GET", route, headers={"Range": value}
            )
            assert status == 416
            assert body == b""
            assert headers["content-range"] == f"bytes */{len(expected)}"


def test_video_conditional_cache_requests(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    expected = (tmp_path / "fixtures" / "videos" / "two-state-64x64.mp4").read_bytes()
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        route = "/api/case-files/assembly.yaml/video"
        status, headers, body = _request(server, "GET", route)
        assert status == 200
        assert body == expected
        etag = headers["etag"]
        last_modified = headers["last-modified"]

        for method, conditional_headers in (
            ("GET", {"If-None-Match": etag}),
            ("GET", {"If-None-Match": f'"stale", W/{etag}'}),
            ("GET", {"If-None-Match": "*"}),
            ("GET", {"If-None-Match": etag, "Range": "bytes=0-9"}),
            ("GET", {"If-Modified-Since": last_modified}),
            ("HEAD", {"If-None-Match": etag}),
            ("HEAD", {"If-Modified-Since": last_modified}),
        ):
            status, response_headers, body = _request(
                server, method, route, headers=conditional_headers
            )
            assert status == 304
            assert body == b""
            assert response_headers["etag"] == etag
            assert response_headers["last-modified"] == last_modified
            assert response_headers["cache-control"] == "private, max-age=0"
            assert "content-length" not in response_headers

        status, _headers, body = _request(
            server,
            "GET",
            route,
            headers={
                "If-None-Match": '"stale"',
                "If-Modified-Since": last_modified,
            },
        )
        assert status == 200
        assert body == expected

        for conditional_headers in (
            {"If-Modified-Since": "not-a-date"},
            {"If-Modified-Since": "Thu, 01 Jan 1970 00:00:00 GMT"},
        ):
            status, _headers, body = _request(
                server, "GET", route, headers=conditional_headers
            )
            assert status == 200
            assert body == expected


def test_video_precondition_precedence(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    expected = (tmp_path / "fixtures" / "videos" / "two-state-64x64.mp4").read_bytes()
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        route = "/api/case-files/assembly.yaml/video"
        _status, headers, _body = _request(server, "GET", route)
        etag = headers["etag"]

        for conditional_headers in (
            {"If-Match": '"stale"'},
            {"If-Match": f"W/{etag}"},
            {"If-Unmodified-Since": "Thu, 01 Jan 1970 00:00:00 GMT"},
        ):
            status, response_headers, body = _request(
                server, "GET", route, headers=conditional_headers
            )
            assert status == 412
            assert body == b""
            assert response_headers["etag"] == etag
            assert response_headers["content-length"] == "0"

        for conditional_headers in (
            {"If-Match": etag},
            {"If-Match": "*"},
            {
                "If-Match": etag,
                "If-Unmodified-Since": "Thu, 01 Jan 1970 00:00:00 GMT",
            },
        ):
            status, _headers, body = _request(
                server, "GET", route, headers=conditional_headers
            )
            assert status == 200
            assert body == expected


def test_video_if_range_protects_replaced_content(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    video_path = tmp_path / "fixtures" / "videos" / "two-state-64x64.mp4"
    expected = video_path.read_bytes()
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        route = "/api/case-files/assembly.yaml/video"
        _status, headers, _body = _request(server, "GET", route)
        etag = headers["etag"]
        last_modified = headers["last-modified"]
        original_stat = video_path.stat()

        status, response_headers, body = _request(
            server,
            "GET",
            route,
            headers={"Range": "bytes=0-9", "If-Range": etag},
        )
        assert status == 206
        assert body == expected[:10]
        assert response_headers["content-range"].startswith("bytes 0-9/")

        for validator in (
            '"stale"',
            f"W/{etag}",
            last_modified,
            "not-a-validator",
        ):
            status, response_headers, body = _request(
                server,
                "GET",
                route,
                headers={"Range": "bytes=0-9", "If-Range": validator},
            )
            assert status == 200
            assert body == expected
            assert "content-range" not in response_headers

        replacement = bytes(len(expected))
        video_path.write_bytes(replacement)
        os.utime(
            video_path,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        replaced_stat = video_path.stat()
        assert replaced_stat.st_size == original_stat.st_size
        assert replaced_stat.st_mtime_ns == original_stat.st_mtime_ns

        status, response_headers, body = _request(
            server,
            "GET",
            route,
            headers={"If-None-Match": etag},
        )
        assert status == 200
        assert body == replacement
        assert response_headers["etag"] == (
            f'"sha256-{hashlib.sha256(replacement).hexdigest()}"'
        )

        for validator in (etag, last_modified):
            status, response_headers, body = _request(
                server,
                "GET",
                route,
                headers={"Range": "bytes=0-9", "If-Range": validator},
            )
            assert status == 200
            assert body == replacement
            assert response_headers["etag"] != etag
            assert "content-range" not in response_headers


def test_video_future_last_modified_is_clamped_and_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    video_path = tmp_path / "fixtures" / "videos" / "two-state-64x64.mp4"
    expected = video_path.read_bytes()
    response_time = int(time.time())
    monkeypatch.setattr(review_server_module, "wall_time", lambda: response_time)
    future = response_time + 24 * 60 * 60
    os.utime(video_path, (future, future))

    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        route = "/api/case-files/assembly.yaml/video"
        status, headers, _body = _request(
            server,
            "GET",
            route,
        )
        assert status == 200
        response_date = email.utils.parsedate_to_datetime(headers["date"])
        last_modified = email.utils.parsedate_to_datetime(headers["last-modified"])
        assert last_modified <= response_date
        assert headers["last-modified"] == email.utils.formatdate(
            response_time, usegmt=True
        )

        monkeypatch.setattr(
            review_server_module,
            "wall_time",
            lambda: response_time + 2,
        )
        status, revalidated_headers, body = _request(
            server,
            "GET",
            route,
            headers={"If-Modified-Since": headers["last-modified"]},
        )
        assert status == 304
        assert body == b""
        assert revalidated_headers["last-modified"] == headers["last-modified"]

        status, revalidated_headers, body = _request(
            server,
            "GET",
            route,
            headers={"If-Unmodified-Since": headers["last-modified"]},
        )
        assert status == 200
        assert body == expected
        assert revalidated_headers["last-modified"] == headers["last-modified"]

        replacement = b"replacement video bytes"
        video_path.write_bytes(replacement)
        os.utime(video_path, (response_time + 1, response_time + 1))
        status, _headers, body = _request(
            server,
            "GET",
            route,
            headers={"If-Modified-Since": headers["last-modified"]},
        )
        assert status == 200
        assert body == replacement


def test_structured_put_success_and_request_validation(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        status, _headers, body = _request(
            server, "GET", "/api/case-files/assembly.yaml"
        )
        assert status == 200
        document = json.loads(body)
        target = document["targets"][0]
        target["samples"][0]["timestamp_s"] = 0.1
        payload = json.dumps(
            {"targets": {target["id"]: {"samples": target["samples"]}}}
        ).encode()
        status, _headers, body = _request(
            server,
            "PUT",
            "/api/case-files/assembly.yaml/samples",
            body=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-GlassKit-Write-Token": "write-secret",
            },
        )
        accepted = json.loads(body)
        assert status == 200
        assert accepted["targets"][0]["samples"][0]["timestamp_s"] == 0.1

        status, _headers, body = _request(
            server,
            "PUT",
            "/api/case-files/assembly.yaml/samples",
            body=b'{"targets":',
            headers={
                "Content-Type": "application/json",
                "X-GlassKit-Write-Token": "write-secret",
            },
        )
        assert status == 400
        assert json.loads(body)["error"]["code"] == "malformed_json"

        status, _headers, body = _request(
            server,
            "PUT",
            "/api/case-files/assembly.yaml/samples",
            body=b'{"targets":{}}',
            headers={
                "Content-Type": "application/json",
                "X-GlassKit-Write-Token": "write-secret",
            },
        )
        assert status == 422
        assert json.loads(body)["error"]["details"]


@contextmanager
def _running_server(eval_dir: Path, static_dir: Path) -> Iterator[ReviewServer]:
    server = create_review_server(
        eval_dir,
        static_dir=static_dir,
        write_token="write-secret",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(
    server: ReviewServer,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    skip_host: bool = False,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    if skip_host:
        connection.putrequest(method, path, skip_host=True)
        for key, value in (headers or {}).items():
            connection.putheader(key, value)
        if body is not None:
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
    else:
        connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    response_body = response.read()
    result = (
        response.status,
        {key.lower(): value for key, value in response.getheaders()},
        response_body,
    )
    connection.close()
    return result


def _copy_fixtures(tmp_path: Path) -> Path:
    destination = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, destination)
    return destination / "eval_directories" / "review"


def _static_dir(tmp_path: Path) -> Path:
    path = tmp_path / "static"
    assets = path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text("<html>review</html>", encoding="utf-8")
    (assets / "app-abcdefgh.js").write_text("console.log('review')", encoding="utf-8")
    return path
