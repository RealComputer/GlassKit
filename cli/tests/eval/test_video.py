from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from glasskit.eval.models import ComparisonConfig, SampleExpectation
from glasskit.eval.video import (
    _stream_duration_s,
    decode_sample_frames,
    iter_sample_frames,
    probe_video,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_decode_sample_frames_normalizes_non_zero_start_time() -> None:
    video_path = FIXTURES / "videos" / "offset-start-64x64.mp4"
    samples = [
        _sample(timestamp_s=0.0, sample_index=0, video_path=video_path),
        _sample(timestamp_s=1.0, sample_index=1, video_path=video_path),
    ]

    decoded = decode_sample_frames(video_path, samples, case_name="case")

    assert decoded[0].frame_index == 0
    assert decoded[1].frame_index == 2


def test_container_duration_uses_microsecond_time_base() -> None:
    class Container:
        duration = 2_000_000

    class Stream:
        duration = None
        time_base = None
        frames = None
        average_rate = None

    assert _stream_duration_s(Container(), Stream()) == 2.0


def test_probe_video_reads_committed_portrait_fixture_dimensions() -> None:
    metadata = probe_video(FIXTURES / "videos" / "portrait-96x128.mp4")

    assert metadata.width == 96
    assert metadata.height == 128


def test_decode_sample_frames_uses_committed_fixture() -> None:
    video_path = FIXTURES / "videos" / "two-state-64x64.mp4"
    samples = [
        _sample(timestamp_s=0.0, sample_index=0, video_path=video_path),
        _sample(timestamp_s=1.0, sample_index=1, video_path=video_path),
    ]

    decoded = decode_sample_frames(video_path, samples, case_name="case")

    assert decoded[0].image.size == (64, 64)
    assert decoded[1].image.size == (64, 64)


def test_decode_sample_frames_stops_after_final_requested_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "long-video.mp4"
    container = _CountingContainer(frame_count=10)
    monkeypatch.setattr("glasskit.eval.video.av.open", lambda path: container)
    samples = [
        _sample(timestamp_s=0.0, sample_index=0, video_path=video_path),
        _sample(timestamp_s=1.0, sample_index=1, video_path=video_path),
    ]

    decoded = decode_sample_frames(video_path, samples, case_name="case")

    assert list(decoded) == [0, 1]
    assert container.decoded_frame_count == 2


def test_iter_sample_frames_decodes_lazily_and_closes_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "long-video.mp4"
    container = _CountingContainer(frame_count=10)
    monkeypatch.setattr("glasskit.eval.video.av.open", lambda path: container)
    frames = iter_sample_frames(
        video_path,
        [
            _sample(timestamp_s=0.0, sample_index=0, video_path=video_path),
            _sample(timestamp_s=5.0, sample_index=1, video_path=video_path),
        ],
        case_name="case",
    )

    assert container.decoded_frame_count == 0
    first = next(frames)
    assert first.sample_index == 0
    assert container.decoded_frame_count == 1
    assert not container.closed

    first.image.close()
    frames.close()

    assert container.decoded_frame_count == 1
    assert container.closed


def test_decode_sample_frames_enables_auto_decoder_threading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "video.mp4"
    container = _CountingContainer(frame_count=1)
    monkeypatch.setattr("glasskit.eval.video.av.open", lambda path: container)

    decode_sample_frames(
        video_path,
        [_sample(timestamp_s=0.0, sample_index=0, video_path=video_path)],
        case_name="case",
    )

    assert container.streams[0].thread_type == "AUTO"


def test_decode_sample_frames_can_stop_on_first_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "long-video.mp4"
    container = _CountingContainer(frame_count=10)
    monkeypatch.setattr("glasskit.eval.video.av.open", lambda path: container)

    decoded = decode_sample_frames(
        video_path,
        [_sample(timestamp_s=0.0, sample_index=0, video_path=video_path)],
        case_name="case",
    )

    assert decoded[0].frame_index == 0
    assert container.decoded_frame_count == 1


def _sample(
    *, timestamp_s: float, sample_index: int, video_path: Path
) -> SampleExpectation:
    return SampleExpectation(
        case_name="case",
        target_id="target",
        target_index=0,
        target_label=None,
        target_config={},
        video_path=video_path,
        timestamp_s=timestamp_s,
        sample_index=sample_index,
        expected=True,
        compare=ComparisonConfig(),
    )


class _CountingContainer:
    def __init__(self, *, frame_count: int) -> None:
        self.frame_count = frame_count
        self.decoded_frame_count = 0
        self.closed = False
        self.streams = [_FakeStream()]

    def __enter__(self) -> _CountingContainer:
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True
        return None

    def decode(self, stream: object):
        for frame_index in range(self.frame_count):
            self.decoded_frame_count += 1
            yield _FakeFrame(timestamp_s=float(frame_index))


class _FakeStream:
    type = "video"
    average_rate = 1.0
    thread_type = "SLICE"


class _FakeFrame:
    pts = None
    time_base = None

    def __init__(self, *, timestamp_s: float) -> None:
        self.time = timestamp_s

    def to_image(self) -> Image.Image:
        return Image.new("RGB", (2, 2), "white")
