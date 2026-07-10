from __future__ import annotations

import http.client
import json
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from glasskit.eval.review.server import ReviewServer, create_review_server

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_suite_static_security_and_host_validation(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    static_dir = _static_dir(tmp_path)
    with _running_server(eval_dir, static_dir) as server:
        status, headers, body = _request(server, "GET", "/api/suite")
        suite = json.loads(body)
        assert status == 200
        assert suite["write_token"] == "write-secret"
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
            "/api/suite",
            headers={"Host": f"example.com:{server.port}"},
            skip_host=True,
        )
        assert status == 400
        assert json.loads(body)["error"]["code"] == "invalid_host"

        status, _headers, body = _request(
            server,
            "GET",
            "/api/suite",
            headers={"Host": f"127.0.0.1:{server.port + 1}"},
            skip_host=True,
        )
        assert status == 400
        assert json.loads(body)["error"]["code"] == "invalid_host"

        status, _headers, body = _request(
            server,
            "GET",
            "/api/suite",
            skip_host=True,
        )
        assert status == 400
        assert json.loads(body)["error"]["code"] == "invalid_host"


def test_unknown_path_like_case_and_write_token_rejections(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        encoded = quote("../assembly.yaml", safe="")
        status, _headers, body = _request(server, "GET", f"/api/cases/{encoded}")
        assert status == 404
        assert json.loads(body)["error"]["code"] == "case_not_found"

        payload = json.dumps({"targets": {}}).encode()
        status, _headers, body = _request(
            server,
            "PUT",
            "/api/cases/assembly.yaml/samples",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        assert status == 403
        assert json.loads(body)["error"]["code"] == "invalid_write_token"

        status, _headers, _body = _request(
            server,
            "PUT",
            "/api/cases/assembly.yaml/samples",
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
            "/api/cases/assembly.yaml/samples",
            body=b"",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(2 * 1024 * 1024 + 1),
                "X-GlassKit-Write-Token": "write-secret",
            },
        )
        assert status == 413
        assert json.loads(body)["error"]["code"] == "request_too_large"


def test_video_full_head_and_byte_ranges(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    expected = (tmp_path / "fixtures" / "videos" / "two-state-64x64.mp4").read_bytes()
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        route = "/api/cases/assembly.yaml/video"
        status, headers, body = _request(server, "GET", route)
        assert status == 200
        assert body == expected
        assert headers["accept-ranges"] == "bytes"
        assert int(headers["content-length"]) == len(expected)

        status, headers, body = _request(server, "HEAD", route)
        assert status == 200
        assert body == b""
        assert int(headers["content-length"]) == len(expected)

        status, headers, body = _request(
            server, "HEAD", route, headers={"Range": "bytes=0-9"}
        )
        assert status == 206
        assert body == b""
        assert headers["content-length"] == "10"

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

        for value in ("bytes=999999999-", "bytes=0-1,3-4", "items=0-2"):
            status, headers, body = _request(
                server, "GET", route, headers={"Range": value}
            )
            assert status == 416
            assert body == b""
            assert headers["content-range"] == f"bytes */{len(expected)}"


def test_structured_put_success_and_request_validation(tmp_path: Path) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    with _running_server(eval_dir, _static_dir(tmp_path)) as server:
        status, _headers, body = _request(server, "GET", "/api/cases/assembly.yaml")
        assert status == 200
        document = json.loads(body)
        target = document["targets"][0]
        target["points"][0]["timestamp_s"] = 0.1
        payload = json.dumps(
            {"targets": {target["id"]: {"points": target["points"]}}}
        ).encode()
        status, _headers, body = _request(
            server,
            "PUT",
            "/api/cases/assembly.yaml/samples",
            body=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-GlassKit-Write-Token": "write-secret",
            },
        )
        accepted = json.loads(body)
        assert status == 200
        assert accepted["targets"][0]["points"][0]["timestamp_s"] == 0.1

        status, _headers, body = _request(
            server,
            "PUT",
            "/api/cases/assembly.yaml/samples",
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
            "/api/cases/assembly.yaml/samples",
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
    return destination / "eval_suites" / "review"


def _static_dir(tmp_path: Path) -> Path:
    path = tmp_path / "static"
    assets = path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text("<html>review</html>", encoding="utf-8")
    (assets / "app-abcdefgh.js").write_text("console.log('review')", encoding="utf-8")
    return path
