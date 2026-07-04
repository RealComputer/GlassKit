from __future__ import annotations

from pathlib import Path

from glasskit.eval.models import ComparisonConfig, SampleExpectation
from glasskit.eval.video import _stream_duration_s, decode_sample_frames, probe_video

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
