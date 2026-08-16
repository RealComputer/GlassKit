from __future__ import annotations

import hashlib
import os
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from typer.testing import CliRunner

import glasskit.eval.cloud_video as cloud_video_module
from glasskit.cli import app
from glasskit.eval.checkpoints import checkpoint_plan_hash
from glasskit.eval.cloud_video import (
    cached_video_path,
    materialize_video,
    prune_video_cache,
    upload_video,
)
from glasskit.eval.expectations import load_eval_directory, load_video_stores
from glasskit.eval.models import (
    EvalConfigError,
    RemoteVideo,
    VideoStore,
    VideoStoreError,
)
from glasskit.eval.review.documents import ReviewRepository

FIXTURES = Path(__file__).parents[1] / "fixtures"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def _http_files(directory: Path) -> Iterator[str]:
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_public_remote_video_is_downloaded_verified_and_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(cache))
    public = tmp_path / "public"
    object_path = public / "recordings" / "demo.mp4"
    object_path.parent.mkdir(parents=True)
    content = b"remote eval video"
    object_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    with _http_files(public) as base_url:
        eval_dir = _remote_eval_dir(tmp_path, digest=digest, public_base_url=base_url)
        first = load_eval_directory(eval_dir).cases[0]

    assert first.video_path.read_bytes() == content
    assert first.remote_video == RemoteVideo(
        store="demo", key="recordings/demo.mp4", sha256=digest
    )

    # The server is gone, so the second load can only succeed from verified cache.
    second = load_eval_directory(eval_dir).cases[0]
    assert second.video_path == first.video_path


def test_unchanged_verified_cache_does_not_rehash_large_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(tmp_path / "cache"))
    public = tmp_path / "public"
    public.mkdir()
    content = b"cache verification record"
    (public / "demo.mp4").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    video = RemoteVideo("demo", "demo.mp4", digest)

    with _http_files(public) as base_url:
        store = VideoStore(name="demo", bucket="unused", public_base_url=base_url)
        first = materialize_video(video, store)

    def fail_if_rehashed(_path: Path) -> str:
        raise AssertionError("unchanged verified cache should not be rehashed")

    monkeypatch.setattr(cloud_video_module, "sha256_file", fail_if_rehashed)

    assert materialize_video(video, store) == first


def test_review_uses_materialized_cloud_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(tmp_path / "cache"))
    public = tmp_path / "public"
    object_path = public / "recordings" / "demo.mp4"
    object_path.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "videos" / "two-state-64x64.mp4", object_path)
    digest = hashlib.sha256(object_path.read_bytes()).hexdigest()

    with _http_files(public) as base_url:
        eval_dir = _remote_eval_dir(tmp_path, digest=digest, public_base_url=base_url)
        document = ReviewRepository(eval_dir).case_file_document("case.yaml")

    assert document.status == "ready"
    assert document.video is not None
    assert document.video.display_path == "demo:recordings/demo.mp4"
    assert document.video.url == "/api/case-files/case.yaml/video"


def test_metadata_only_load_validates_store_without_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(cache))
    digest = hashlib.sha256(b"not downloaded").hexdigest()
    eval_dir = _remote_eval_dir(
        tmp_path,
        digest=digest,
        public_base_url="http://127.0.0.1:1",
    )

    loaded = load_eval_directory(eval_dir, materialize_videos=False)

    assert loaded.cases[0].remote_video is not None
    assert not loaded.cases[0].video_path.exists()
    assert not cache.exists()


def test_unknown_remote_store_fails_even_for_metadata_only_load(tmp_path: Path) -> None:
    digest = hashlib.sha256(b"video").hexdigest()
    eval_dir = _remote_eval_dir(tmp_path, digest=digest, public_base_url=None)
    case_path = eval_dir / "cases" / "case.yaml"
    case_path.write_text(
        case_path.read_text(encoding="utf-8").replace("store: demo", "store: missing"),
        encoding="utf-8",
    )

    with pytest.raises(EvalConfigError, match="unknown store 'missing'"):
        load_eval_directory(eval_dir, materialize_videos=False)


def test_hash_mismatch_does_not_install_cache_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(tmp_path / "cache"))
    public = tmp_path / "public"
    public.mkdir()
    (public / "demo.mp4").write_bytes(b"unexpected")
    expected = hashlib.sha256(b"expected").hexdigest()
    video = RemoteVideo("demo", "demo.mp4", expected)

    with _http_files(public) as base_url:
        store = VideoStore(name="demo", bucket="unused", public_base_url=base_url)
        with pytest.raises(VideoStoreError, match="has SHA-256"):
            materialize_video(video, store)

    assert not cached_video_path(video).exists()
    assert not list((tmp_path / "cache").rglob("*.part-*"))


def test_private_download_uses_configured_credential_environment_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TEAM_R2_KEY", "key-id")
    monkeypatch.setenv("TEAM_R2_SECRET", "secret")
    content = b"private video"
    digest = hashlib.sha256(content).hexdigest()
    captured: dict[str, object] = {}

    class FakeClient:
        def download_file(self, bucket: str, key: str, destination: str) -> None:
            captured["download"] = (bucket, key)
            Path(destination).write_bytes(content)

    def fake_client(service: str, **kwargs: object) -> FakeClient:
        captured["client"] = (service, kwargs)
        return FakeClient()

    monkeypatch.setattr(boto3, "client", fake_client)
    store = VideoStore(
        name="team",
        bucket="evals",
        endpoint_url="https://account.r2.cloudflarestorage.com",
        region="auto",
        access_key_id_env="TEAM_R2_KEY",
        secret_access_key_env="TEAM_R2_SECRET",
    )

    path = materialize_video(RemoteVideo("team", "private/demo.mp4", digest), store)

    assert path.read_bytes() == content
    assert captured["download"] == ("evals", "private/demo.mp4")
    assert captured["client"] == (
        "s3",
        {
            "region_name": "auto",
            "endpoint_url": "https://account.r2.cloudflarestorage.com",
            "aws_access_key_id": "key-id",
            "aws_secret_access_key": "secret",
        },
    )


def test_private_download_reports_missing_named_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("TEAM_R2_KEY", raising=False)
    monkeypatch.delenv("TEAM_R2_SECRET", raising=False)
    store = VideoStore(
        name="team",
        bucket="evals",
        access_key_id_env="TEAM_R2_KEY",
        secret_access_key_env="TEAM_R2_SECRET",
    )

    with pytest.raises(VideoStoreError, match="environment variable TEAM_R2_KEY"):
        materialize_video(RemoteVideo("team", "private/demo.mp4", "0" * 64), store)


def test_upload_uses_immutable_default_key_and_sha_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "demo.mp4"
    content = b"upload video"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    captured: dict[str, object] = {}

    class FakeClient:
        uploaded = False

        def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            if not self.uploaded:
                raise ClientError(
                    {
                        "Error": {"Code": "404", "Message": "missing"},
                        "ResponseMetadata": {"HTTPStatusCode": 404},
                    },
                    "HeadObject",
                )
            return {
                "ContentLength": len(content),
                "Metadata": {"sha256": digest},
            }

        def upload_file(
            self,
            filename: str,
            bucket: str,
            key: str,
            *,
            ExtraArgs: dict[str, object],
        ) -> None:
            self.uploaded = True
            captured["upload"] = (filename, bucket, key, ExtraArgs)

    client = FakeClient()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)

    result = upload_video(source, VideoStore(name="demo", bucket="evals"))

    expected_key = f"{digest}.mp4"
    assert result.key == expected_key
    assert result.sha256 == digest
    assert captured["upload"] == (
        str(source),
        "evals",
        expected_key,
        {"Metadata": {"sha256": digest}, "ContentType": "video/mp4"},
    )


def test_remote_checkpoint_fingerprint_does_not_depend_on_cache_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(tmp_path / "cache"))
    digest = hashlib.sha256(b"remote identity").hexdigest()
    eval_dir = _remote_eval_dir(tmp_path, digest=digest, public_base_url=None)
    loaded = load_eval_directory(eval_dir, materialize_videos=False)

    first = checkpoint_plan_hash(loaded, {"command": "run"})
    path = loaded.cases[0].video_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"cache contents do not define the input")
    os.utime(path, ns=(1, 1))
    second = checkpoint_plan_hash(loaded, {"command": "run"})

    assert second == first


def test_video_store_cli_is_distinct_from_local_video_commands() -> None:
    eval_help = CliRunner().invoke(app, ["eval", "--help"])
    store_help = CliRunner().invoke(app, ["eval", "video-store", "--help"])

    assert eval_help.exit_code == 0
    assert "video-store" in eval_help.output
    assert store_help.exit_code == 0
    for command in ("pull", "upload", "prune-cache"):
        assert command in store_help.output


def test_cloud_video_pull_ignores_unrelated_missing_local_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(tmp_path / "cache"))
    public = tmp_path / "public"
    object_path = public / "recordings" / "demo.mp4"
    object_path.parent.mkdir(parents=True)
    content = b"pull command video"
    object_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    with _http_files(public) as base_url:
        eval_dir = _remote_eval_dir(tmp_path, digest=digest, public_base_url=base_url)
        (eval_dir / "cases" / "local.yaml").write_text(
            "video: missing-local.mp4\n"
            "targets:\n"
            "  step:\n"
            "    samples:\n"
            "    - at: 0\n"
            "      expect: true\n",
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            app,
            ["eval", "video-store", "pull", "--eval-dir", str(eval_dir)],
        )

    assert result.exit_code == 0
    assert digest in result.output


def test_store_urls_cannot_embed_credentials_or_queries(tmp_path: Path) -> None:
    digest = hashlib.sha256(b"video").hexdigest()
    eval_dir = _remote_eval_dir(tmp_path, digest=digest, public_base_url=None)
    config_path = eval_dir / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "    endpoint_url: https://user:secret@example.com?token=secret\n",
        encoding="utf-8",
    )

    with pytest.raises(EvalConfigError, match="without credentials"):
        load_video_stores(eval_dir)


def test_prune_cache_keeps_active_transfers_and_removes_stale_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("GLASSKIT_EVAL_CACHE_DIR", str(cache))
    cache.mkdir()
    active = cache / ".video.part-active"
    stale = cache / ".video.part-stale"
    verified = cache / "video.mp4"
    for path in (active, stale, verified):
        path.write_bytes(b"1234")
    old = 1
    os.utime(stale, (old, old))

    count, size = prune_video_cache()

    assert (count, size) == (1, 4)
    assert active.exists()
    assert verified.exists()
    assert not stale.exists()


def test_remote_video_sha256_is_mandatory(tmp_path: Path) -> None:
    eval_dir = _remote_eval_dir(
        tmp_path,
        digest=hashlib.sha256(b"video").hexdigest(),
        public_base_url=None,
    )
    case_path = eval_dir / "cases" / "case.yaml"
    case_path.write_text(
        case_path.read_text(encoding="utf-8").replace(
            f"  sha256: {hashlib.sha256(b'video').hexdigest()}\n", ""
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvalConfigError, match="video.sha256.*Field required"):
        load_eval_directory(eval_dir, materialize_videos=False)


def _remote_eval_dir(
    tmp_path: Path,
    *,
    digest: str,
    public_base_url: str | None,
) -> Path:
    eval_dir = tmp_path / "eval"
    cases = eval_dir / "cases"
    cases.mkdir(parents=True)
    public_line = (
        f"    public_base_url: {public_base_url}\n"
        if public_base_url is not None
        else ""
    )
    (eval_dir / "config.yaml").write_text(
        f"video_stores:\n  demo:\n    type: s3\n    bucket: eval-videos\n{public_line}",
        encoding="utf-8",
    )
    (cases / "case.yaml").write_text(
        "video:\n"
        "  store: demo\n"
        "  key: recordings/demo.mp4\n"
        f"  sha256: {digest}\n"
        "targets:\n"
        "  step:\n"
        "    samples:\n"
        "    - at: 0\n"
        "      expect: true\n",
        encoding="utf-8",
    )
    assert load_video_stores(eval_dir)["demo"].bucket == "eval-videos"
    return eval_dir
