from __future__ import annotations

import math
import random
import stat
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from glasskit.eval.expectations import load_case
from glasskit.eval.review.models import (
    PointCompare,
    PointOrigin,
    ReviewAPIError,
    ReviewPoint,
)
from glasskit.eval.review.serialization import (
    atomic_replace_text,
    compact_json,
    dump_case_yaml,
    reconstruct_target,
    strict_json_value,
    structurally_equal,
)
from glasskit.eval.schemas import RawCaseYaml


def test_lossless_json_preserves_large_integers_float_forms_and_order() -> None:
    value = strict_json_value(
        '{"large":900719925474099312345,"integer":1,"float":1.0,"zero":-0.0}',
        path="point.expect_json",
    )

    assert compact_json(value) == (
        '{"large":900719925474099312345,"integer":1,"float":1.0,"zero":-0.0}'
    )
    assert not structurally_equal(1, 1.0)
    assert not structurally_equal(False, 0)
    assert structurally_equal({"a": 1, "b": [True]}, {"b": [True], "a": 1})
    assert math.copysign(1, value["zero"]) == -1
    assert not structurally_equal(-0.0, 0.0)


def test_strict_json_rejects_non_finite_values_and_duplicate_keys() -> None:
    with pytest.raises(ReviewAPIError) as nonfinite:
        strict_json_value("NaN", path="expect_json")
    assert "valid JSON" in nonfinite.value.details[0].message
    with pytest.raises(ReviewAPIError) as duplicate:
        strict_json_value('{"a":1,"a":2}', path="expect_json")
    assert "duplicate object key" in duplicate.value.details[0].message
    with pytest.raises(ReviewAPIError) as surrogate:
        strict_json_value(r'"\ud800"', path="expect_json")
    assert "Unicode scalar" in surrogate.value.details[0].message


def test_reconstruction_emits_default_and_custom_ranges_with_exact_groups() -> None:
    default = reconstruct_target(
        "state",
        [_point("a", 0.0), _point("b", 0.5), _point("c", 1.0)],
        default_every_s=0.5,
    )
    custom = reconstruct_target(
        "state",
        [_point("a", 5.0), _point("b", 5.25), _point("c", 5.5)],
        default_every_s=0.5,
    )

    assert default.blocks[0]["range"] == [0.0, 1.5]
    assert "every_s" not in default.blocks[0]
    assert default.groups[0].kind == "range"
    assert default.groups[0].point_ids == ["a", "b", "c"]
    assert custom.blocks[0]["range"] == [5.0, 5.75]
    assert custom.blocks[0]["every_s"] == 0.25


def test_reconstruction_keeps_sparse_pair_at_but_retains_source_range_pair() -> None:
    sparse = reconstruct_target(
        "state",
        [_point("a", 0.0), _point("b", 4.0)],
        default_every_s=0.5,
    )
    origin = PointOrigin(block_index=2, kind="range", every_s=4.0)
    source_range = reconstruct_target(
        "state",
        [_point("a", 0.0, origin=origin), _point("b", 4.0, origin=origin)],
        default_every_s=0.5,
    )

    assert sparse.blocks[0]["at"] == [0.0, 4.0]
    assert source_range.blocks[0]["range"] == [0.0, 8.0]
    assert source_range.blocks[0]["every_s"] == 4.0


def test_range_end_clips_before_next_different_payload() -> None:
    points = [
        _point("a", 0.0, expect_json="false", expect_type="boolean"),
        _point("b", 0.5, expect_json="false", expect_type="boolean"),
        _point("c", 1.0, expect_json="false", expect_type="boolean"),
        _point("d", 1.25, expect_json="true", expect_type="boolean"),
    ]

    reconstructed = reconstruct_target("state", points, default_every_s=0.5)

    assert reconstructed.blocks[0]["range"] == [0.0, 1.25]
    assert reconstructed.blocks[1]["at"] == 1.25


def test_reconstruction_splits_payload_changes_and_rejects_near_duplicates() -> None:
    split = reconstruct_target(
        "state",
        [
            _point("a", 0.0, field="left"),
            _point("b", 0.5, field="right"),
            _point("c", 1.0, field="left"),
        ],
        default_every_s=0.5,
    )
    assert [block["at"] for block in split.blocks] == [0.0, 0.5, 1.0]

    with pytest.raises(ReviewAPIError) as duplicate:
        reconstruct_target(
            "state",
            [_point("a", 1.0), _point("b", 1.000000001)],
            default_every_s=0.5,
        )
    assert "within 1e-9" in duplicate.value.details[0].message


def test_point_rejects_present_blank_optional_text() -> None:
    with pytest.raises(ValidationError, match="use null"):
        _point("a", 0.0, field="   ")
    with pytest.raises(ValidationError, match="use null"):
        _point("a", 0.0, comment="\n")


def test_atomic_replace_preserves_mode_and_removes_temporary_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "case.yaml"
    path.write_text("old\n", encoding="utf-8")
    path.chmod(0o640)

    sync_failed = atomic_replace_text(path, "new\n")

    assert not sync_failed
    assert path.read_text(encoding="utf-8") == "new\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert list(tmp_path.iterdir()) == [path]


def test_reconstructed_yaml_timestamps_use_flow_style() -> None:
    reconstructed = reconstruct_target(
        "state",
        [_point("a", 0.0), _point("b", 0.5), _point("c", 1.0)],
        default_every_s=0.5,
    )

    rendered = dump_case_yaml({"targets": {"state": {"samples": reconstructed.blocks}}})

    # Ordinary SafeDumper does not know the marker; this assertion protects the
    # semantic data while document-level tests cover the custom flow-style dumper.
    assert "range: [0.0, 1.5]" in rendered
    assert yaml.safe_load(rendered)["targets"]["state"]["samples"][0]["range"] == [
        0.0,
        1.5,
    ]


def test_seeded_reconstruction_round_trips_through_shared_case_loader() -> None:
    randomizer = random.Random(20260710)
    payloads: list[tuple[str, str]] = [
        ("false", "boolean"),
        ("true", "boolean"),
        ("1", "number"),
        ("1.0", "number"),
        ('{"value":9007199254740993}', "object"),
        ("[1,2]", "array"),
    ]
    for schedule_index in range(80):
        ticks = sorted(randomizer.sample(range(0, 160), randomizer.randint(1, 20)))
        points: list[ReviewPoint] = []
        for point_index, tick in enumerate(ticks):
            expect_json, expect_type = randomizer.choice(payloads)
            points.append(
                _point(
                    f"p-{point_index}",
                    tick / 8,
                    expect_json=expect_json,
                    expect_type=expect_type,
                    field=("result" if randomizer.randrange(4) == 0 else None),
                    comment=("note" if randomizer.randrange(5) == 0 else None),
                )
            )
        reconstructed = reconstruct_target("state", points, default_every_s=0.5)
        raw_case = RawCaseYaml.model_validate(
            {
                "video": "unused.mp4",
                "sampling": {"every_s": 0.5},
                "targets": {"state": {"samples": reconstructed.blocks}},
            }
        )
        loaded = load_case(
            Path(f"generated-{schedule_index}.yaml"),
            raw_case=raw_case,
            resolve_video=False,
        )
        accepted = loaded.targets[0].samples

        assert [sample.timestamp_s for sample in accepted] == [
            point.timestamp_s for point in reconstructed.points
        ]
        assert len(accepted) == len(reconstructed.points)
        for sample, point in zip(accepted, reconstructed.points, strict=True):
            assert structurally_equal(sample.expected, point.expected)
            assert sample.field == point.field
            assert sample.compare.mode == point.mode
            assert sample.compare.tolerance == point.tolerance
            assert sample.comment == point.comment


def _point(
    point_id: str,
    timestamp_s: float,
    *,
    expect_json: str = "true",
    expect_type: str = "boolean",
    field: str | None = None,
    comment: str | None = None,
    origin: PointOrigin | None = None,
) -> ReviewPoint:
    return ReviewPoint.model_validate(
        {
            "id": point_id,
            "timestamp_s": timestamp_s,
            "expect_type": expect_type,
            "expect_json": expect_json,
            "field": field,
            "compare": PointCompare().model_dump(),
            "comment": comment,
            "origin": origin.model_dump() if origin else None,
        }
    )
