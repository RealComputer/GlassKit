from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from glasskit.eval import checkpoints
from glasskit.eval.checkpoints import CheckpointStore


def test_checkpoint_creates_and_directory_syncs_event_log_before_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced_directories: list[Path] = []
    monkeypatch.setattr(
        checkpoints,
        "_sync_directory_best_effort",
        synced_directories.append,
    )

    store = _create_checkpoint(tmp_path)
    try:
        events_path = store.path / "events.jsonl"
        assert events_path.read_bytes() == b""
        assert synced_directories == [store.path, store.path]
    finally:
        store.release()


def test_directory_sync_is_best_effort_when_opening_directories_is_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = os.open
    directory_flag = getattr(os, "O_DIRECTORY", 0x100000)

    def unsupported_directory_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
    ) -> int:
        if flags & directory_flag:
            raise OSError(errno.EINVAL, "directory descriptors are unsupported")
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "O_DIRECTORY", directory_flag, raising=False)
    monkeypatch.setattr(checkpoints.os, "open", unsupported_directory_open)

    store = _create_checkpoint(tmp_path)
    try:
        assert (store.path / "manifest.json").is_file()
        assert (store.path / "events.jsonl").is_file()
    finally:
        store.release()


@pytest.mark.parametrize(
    "torn_tail",
    [
        b'{"key":"unfinished',
        json.dumps(
            {
                "key": "uncommitted",
                "payload": {"value": 999},
                "recorded_at": "2026-07-20T00:00:00Z",
                "type": "result",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
    ],
)
def test_resume_truncates_any_event_tail_without_a_newline_before_appending(
    tmp_path: Path, torn_tail: bytes
) -> None:
    store = _create_checkpoint(tmp_path)
    events_path = store.path / "events.jsonl"
    checkpoint_path = store.path
    store.record("result", "first", {"value": 1})
    store.release()

    with events_path.open("ab") as stream:
        stream.write(torn_tail)
        stream.flush()
        os.fsync(stream.fileno())

    resumed = CheckpointStore.resume(
        eval_dir=tmp_path / "eval",
        reference=checkpoint_path,
        kind="seed",
        plan_hash="test-plan",
    )
    try:
        assert resumed.latest("result") == {"first": {"value": 1}}
        resumed.record("result", "second", {"value": 2})
        assert resumed.latest("result") == {
            "first": {"value": 1},
            "second": {"value": 2},
        }
    finally:
        resumed.release()

    raw = events_path.read_bytes()
    assert raw.endswith(b"\n")
    assert len(raw.splitlines()) == 2


def _create_checkpoint(tmp_path: Path) -> CheckpointStore:
    return CheckpointStore.create(
        kind="seed",
        eval_dir=tmp_path / "eval",
        invocation={"verbose": False},
        plan_hash="test-plan",
        total=2,
    )
