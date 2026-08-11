from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from struct import pack
from typing import Any, cast

import pytest
from PIL import Image

import glasskit.eval.video as video_module
from glasskit.eval.models import ComparisonConfig, SampleExpectation
from glasskit.eval.video import (
    FrameSelectionCancelled,
    _stream_duration_s,
    decode_sample_frames,
    iter_frames_at,
    iter_sample_frames,
    probe_video,
    select_frame_at,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ANISOTROPIC_REFLECTED_MATRIX = (
    -92682,
    -46341,
    0,
    -92682,
    46341,
    0,
    0,
    0,
    1 << 30,
)


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


def test_probe_video_applies_display_rotation_to_dimensions() -> None:
    metadata = probe_video(FIXTURES / "videos" / "rotated-quadrants-96x64.mp4")

    assert metadata.width == 64
    assert metadata.height == 96


def test_probe_dimensions_match_expanded_non_quarter_turn_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "rotated.mp4"
    monkeypatch.setattr(
        "glasskit.eval.video.av.open",
        lambda path: _SingleFrameContainer(rotation=2),
    )

    metadata = probe_video(video_path)
    decoded = decode_sample_frames(
        video_path,
        [_sample(timestamp_s=0.0, sample_index=0, video_path=video_path)],
        case_name="case",
    )

    assert (metadata.width, metadata.height) == (100, 68)
    assert decoded[0].image.size == (metadata.width, metadata.height)


def test_reflected_display_rotation_normalizes_anisotropic_scale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "scaled-reflection.mp4"
    monkeypatch.setattr(
        "glasskit.eval.video.av.open",
        lambda path: _SingleFrameContainer(
            rotation=27,
            display_matrix=ANISOTROPIC_REFLECTED_MATRIX,
        ),
    )

    metadata = probe_video(video_path)
    decoded = decode_sample_frames(
        video_path,
        [_sample(timestamp_s=0.0, sample_index=0, video_path=video_path)],
        case_name="case",
    )

    assert (metadata.width, metadata.height) == (114, 114)
    assert decoded[0].image.size == (metadata.width, metadata.height)


def test_decode_sample_frames_uses_committed_fixture() -> None:
    video_path = FIXTURES / "videos" / "two-state-64x64.mp4"
    samples = [
        _sample(timestamp_s=0.0, sample_index=0, video_path=video_path),
        _sample(timestamp_s=1.0, sample_index=1, video_path=video_path),
    ]

    decoded = decode_sample_frames(video_path, samples, case_name="case")

    assert decoded[0].image.size == (64, 64)
    assert decoded[1].image.size == (64, 64)


def test_decode_sample_frames_applies_display_rotation_to_pixels() -> None:
    video_path = FIXTURES / "videos" / "rotated-quadrants-96x64.mp4"

    decoded = decode_sample_frames(
        video_path,
        [_sample(timestamp_s=0.0, sample_index=0, video_path=video_path)],
        case_name="case",
    )

    image = decoded[0].image
    assert image.size == (64, 96)
    _assert_color(_rgb_pixel(image, (16, 24)), "green")
    _assert_color(_rgb_pixel(image, (48, 24)), "yellow")
    _assert_color(_rgb_pixel(image, (16, 72)), "red")
    _assert_color(_rgb_pixel(image, (48, 72)), "blue")


def test_decode_sample_frames_applies_display_reflection_to_pixels() -> None:
    video_path = FIXTURES / "videos" / "reflected-quadrants-96x64.mp4"

    decoded = decode_sample_frames(
        video_path,
        [_sample(timestamp_s=0.0, sample_index=0, video_path=video_path)],
        case_name="case",
    )

    image = decoded[0].image
    assert image.size == (96, 64)
    _assert_color(_rgb_pixel(image, (24, 16)), "green")
    _assert_color(_rgb_pixel(image, (72, 16)), "red")
    _assert_color(_rgb_pixel(image, (24, 48)), "yellow")
    _assert_color(_rgb_pixel(image, (72, 48)), "blue")


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


def test_iter_frames_at_reports_selected_media_times_and_request_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "video.mp4"
    container = _CountingContainer(frame_count=3)
    monkeypatch.setattr("glasskit.eval.video.av.open", lambda path: container)

    selected = list(iter_frames_at(video_path, [1.2, 0.5]))

    try:
        assert [frame.request_index for frame in selected] == [1, 0]
        assert [frame.requested_timestamp_s for frame in selected] == [0.5, 1.2]
        assert [frame.media_timestamp_s for frame in selected] == [0.0, 1.0]
        assert [frame.frame_index for frame in selected] == [0, 1]
    finally:
        for frame in selected:
            frame.image.close()


@pytest.mark.parametrize(
    ("fixture_name", "timestamp_s"),
    [
        ("two-state-64x64.mp4", 0.125),
        ("two-state-64x64.mp4", 1.2),
        ("offset-start-64x64.mp4", 1.25),
        ("rotated-quadrants-96x64.mp4", 0.7),
        ("reflected-quadrants-96x64.mp4", 0.7),
    ],
)
def test_random_access_selection_matches_sequential_eval_selection(
    fixture_name: str, timestamp_s: float
) -> None:
    video_path = FIXTURES / "videos" / fixture_name
    selected_frames = iter_frames_at(video_path, [timestamp_s])
    expected = next(selected_frames)
    selected_frames.close()

    actual = select_frame_at(video_path, timestamp_s)

    try:
        assert actual.requested_timestamp_s == expected.requested_timestamp_s
        assert actual.media_timestamp_s == expected.media_timestamp_s
        assert actual.image.mode == expected.image.mode
        assert actual.image.size == expected.image.size
        assert actual.image.tobytes() == expected.image.tobytes()
    finally:
        expected.image.close()
        actual.image.close()


def test_random_access_selection_seeks_instead_of_decoding_from_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_path = FIXTURES / "videos" / "two-state-64x64.mp4"
    original_open = video_module.av.open
    opened: list[_TrackingContainer] = []

    def tracked_open(path: str) -> _TrackingContainer:
        container = _TrackingContainer(original_open(path))
        opened.append(container)
        return container

    monkeypatch.setattr(video_module.av, "open", tracked_open)

    selected = select_frame_at(video_path, 1.2)

    selected.image.close()
    assert len(opened) == 1
    assert opened[0].seek_count == 1
    assert opened[0].decoded_frame_count < 6


def test_random_access_selection_falls_back_when_seek_lands_after_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "open-gop.mp4"
    seek_container = _ForwardLandingContainer()
    sequential_container = _TimestampContainer(
        [
            _TimestampFrame(timestamp_s=0.0, pts=0, color="black"),
            _TimestampFrame(timestamp_s=3.933, pts=3933, color="green"),
            _TimestampFrame(timestamp_s=4.0, pts=4000, color="red"),
        ]
    )
    containers = iter([seek_container, sequential_container])
    monkeypatch.setattr(video_module.av, "open", lambda _path: next(containers))

    selected = select_frame_at(video_path, 3.946)

    try:
        assert selected.media_timestamp_s == 3.933
        assert selected.frame_index == 1
        assert selected.image.getpixel((0, 0)) == (0, 128, 0)
        assert seek_container.seek_count == 1
        assert seek_container.decoded_timestamps == [0.0, 4.0]
        assert sequential_container.decoded_timestamps == [0.0, 3.933, 4.0]
    finally:
        selected.image.close()


def test_random_access_selection_stops_when_request_is_cancelled() -> None:
    callback_calls = 0

    def should_cancel() -> bool:
        nonlocal callback_calls
        callback_calls += 1
        return callback_calls >= 3

    with pytest.raises(FrameSelectionCancelled):
        select_frame_at(
            FIXTURES / "videos" / "two-state-64x64.mp4",
            1.2,
            should_cancel=should_cancel,
        )

    assert callback_calls == 3


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


def _assert_color(pixel: tuple[int, int, int], expected: str) -> None:
    red, green, blue = pixel
    if expected == "red":
        assert red > 180 and green < 80 and blue < 80
    elif expected == "green":
        assert red < 80 and green > 180 and blue < 80
    elif expected == "blue":
        assert red < 80 and green < 80 and blue > 180
    else:
        assert expected == "yellow"
        assert red > 180 and green > 180 and blue < 80


def _rgb_pixel(image: Image.Image, position: tuple[int, int]) -> tuple[int, int, int]:
    return cast(tuple[int, int, int], image.getpixel(position))


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


class _TrackingContainer:
    def __init__(self, container: Any) -> None:
        self.container = container
        self.streams = container.streams
        self.decoded_frame_count = 0
        self.seek_count = 0

    def __enter__(self) -> _TrackingContainer:
        return self

    def __exit__(self, *args: object) -> None:
        self.container.close()

    def decode(self, stream: object):
        for frame in self.container.decode(stream):
            self.decoded_frame_count += 1
            yield frame

    def seek(self, *args: object, **kwargs: object) -> None:
        self.seek_count += 1
        self.container.seek(*args, **kwargs)


class _TimestampContainer:
    def __init__(self, frames: list[_TimestampFrame]) -> None:
        self.frames = frames
        self.streams = [_TimestampStream()]
        self.decoded_timestamps: list[float] = []

    def __enter__(self) -> _TimestampContainer:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def decode(self, stream: object):
        for frame in self.frames:
            self.decoded_timestamps.append(frame.time)
            yield frame


class _ForwardLandingContainer(_TimestampContainer):
    def __init__(self) -> None:
        super().__init__([])
        self.decode_count = 0
        self.seek_count = 0

    def decode(self, stream: object):
        self.decode_count += 1
        frame = (
            _TimestampFrame(timestamp_s=0.0, pts=0, color="black")
            if self.decode_count == 1
            else _TimestampFrame(timestamp_s=4.0, pts=4000, color="red")
        )
        self.decoded_timestamps.append(frame.time)
        yield frame

    def seek(self, *args: object, **kwargs: object) -> None:
        self.seek_count += 1


class _TimestampStream:
    type = "video"
    average_rate = 30.0
    thread_type = "SLICE"
    time_base = Fraction(1, 1000)


class _TimestampFrame:
    time_base = Fraction(1, 1000)
    rotation = 0

    def __init__(self, *, timestamp_s: float, pts: int, color: str) -> None:
        self.time = timestamp_s
        self.pts = pts
        self.color = color

    def to_image(self) -> Image.Image:
        return Image.new("RGB", (2, 2), self.color)


class _FakeStream:
    type = "video"
    average_rate = 1.0
    thread_type = "SLICE"


class _FakeFrame:
    pts = None
    time_base = None
    rotation = 0

    def __init__(self, *, timestamp_s: float) -> None:
        self.time = timestamp_s

    def to_image(self) -> Image.Image:
        return Image.new("RGB", (2, 2), "white")


class _SingleFrameContainer:
    duration = None

    def __init__(
        self,
        *,
        rotation: int,
        display_matrix: tuple[int, ...] | None = None,
    ) -> None:
        self.streams = [_SingleFrameStream()]
        self.frame = _SingleFrame(
            rotation=rotation,
            display_matrix=display_matrix,
        )

    def __enter__(self) -> _SingleFrameContainer:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def decode(self, stream: object):
        yield self.frame


class _SingleFrameStream:
    type = "video"
    width = 96
    height = 64
    frames = 1
    duration = 1
    time_base = 1
    average_rate = 1.0
    thread_type = "SLICE"


class _SingleFrame:
    pts = None
    time_base = None
    time = 0.0

    def __init__(
        self,
        *,
        rotation: int,
        display_matrix: tuple[int, ...] | None,
    ) -> None:
        self.rotation = rotation
        self.side_data = (
            [] if display_matrix is None else [_DisplayMatrixSideData(display_matrix)]
        )

    def to_image(self) -> Image.Image:
        return Image.new("RGB", (96, 64), "white")


class _DisplayMatrixSideData:
    class Type:
        name = "DISPLAYMATRIX"

    type = Type()

    def __init__(self, matrix: tuple[int, ...]) -> None:
        self.matrix = matrix

    def __bytes__(self) -> bytes:
        return pack("=9i", *self.matrix)
