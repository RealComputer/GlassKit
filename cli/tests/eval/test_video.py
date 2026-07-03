from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
from PIL import Image

from gk.eval.models import ComparisonConfig, SampleExpectation
from gk.eval.video import _stream_duration_s, decode_sample_frames, probe_video

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_decode_sample_frames_normalizes_non_zero_start_time(tmp_path: Path) -> None:
    video_path = tmp_path / "offset.mp4"
    _write_video(video_path, pts_offset=20, fps=2, frames=4)
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


def _write_video(
    path: Path, *, pts_offset: int = 0, fps: int = 4, frames: int = 8
) -> None:
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width = 64
        stream.height = 64
        stream.pix_fmt = "yuv420p"
        for index in range(frames):
            color = "black" if index < frames // 2 else "white"
            image = Image.new("RGB", (64, 64), color)
            frame = av.VideoFrame.from_image(image)
            frame.pts = pts_offset + index
            frame.time_base = Fraction(1, fps)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


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
