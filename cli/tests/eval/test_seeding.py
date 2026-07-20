from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from glasskit.eval.adapters import LoadedEvaluator
from glasskit.eval.commands import serialize_command
from glasskit.eval.expectations import load_eval_directory
from glasskit.eval.models import (
    AdapterLoadError,
    AdapterRuntimeError,
    CaseWriteError,
    EvalConfigError,
    EvalDirectory,
    SeedIncompleteError,
    SeedOptions,
)
from glasskit.eval.seeding import seed_eval

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TWO_STATE_VIDEO = (FIXTURES / "videos" / "two-state-64x64.mp4").as_posix()
PROCESS_ADAPTER = FIXTURES / "adapters" / "process_adapter.py"


def test_seed_fills_missing_expectations_and_preserves_existing_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
sampling:
  every_s: 0.5
targets:
  state:
    config:
      threshold: 1.0
    samples:
      - range: [0.0, 2.0]
        field: result.matches
        comment: Proposed by the adapter.
  manual:
    samples:
      - at: 0.0
        expect: manual
        """,
    )
    labeler = BatchLabeler()
    _use_evaluator(
        monkeypatch, evaluate_many=labeler.evaluate_many, close=labeler.close
    )

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
                concurrency=4,
            )
        )
    )

    assert report.seeded_count == 4
    assert report.preserved_count == 1
    assert report.case_names == ["case"]
    assert labeler.calls == [("state", [0.0, 0.5, 1.0, 1.5], {"threshold": 1.0})]
    assert labeler.closed
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["targets"]["state"]["samples"] == [
        {
            "range": [0.0, 1.0],
            "field": "result.matches",
            "expect": False,
            "comment": "Proposed by the adapter.",
        },
        {
            "range": [1.0, 2.0],
            "field": "result.matches",
            "expect": True,
            "comment": "Proposed by the adapter.",
        },
    ]
    assert raw["targets"]["manual"]["samples"] == [{"at": 0.0, "expect": "manual"}]
    assert [sample.expected for sample in load_eval_directory(eval_dir).samples] == [
        False,
        False,
        True,
        True,
        "manual",
    ]


def test_seed_preserves_sample_defaults_without_expanding_them_into_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
sample_defaults:
  field: result
  compare:
    mode: json_subset
targets:
  state:
    sample_defaults:
      field: result.matches
      compare:
        mode: exact
    samples:
      - range: [0.0, 2.0]
        """,
    )
    labeler = BatchLabeler()
    _use_evaluator(monkeypatch, evaluate_many=labeler.evaluate_many)

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
            )
        )
    )

    assert report.seeded_count == 4
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["sample_defaults"] == {
        "field": "result",
        "compare": {"mode": "json_subset"},
    }
    assert raw["targets"]["state"]["sample_defaults"] == {
        "field": "result.matches",
        "compare": {"mode": "exact"},
    }
    assert raw["targets"]["state"]["samples"] == [
        {"range": [0.0, 1.0], "expect": False},
        {"range": [1.0, 2.0], "expect": True},
    ]


def test_seed_reconstructs_ranges_before_adjacent_sample_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
sampling:
  every_s: 0.5
targets:
  state:
    samples:
      - range: [0.0, 0.7]
      - at: 0.8
        """,
    )

    async def evaluate(_sample: Any, _target: Any) -> bool:
        return True

    _use_evaluator(monkeypatch, evaluate=evaluate)

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
            )
        )
    )

    assert report.seeded_count == 3
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["targets"]["state"]["samples"] == [
        {"range": [0.0, 0.7], "expect": True},
        {"at": 0.8, "expect": True},
    ]
    assert [sample.timestamp_s for sample in load_eval_directory(eval_dir).samples] == [
        0.0,
        0.5,
        0.8,
    ]


def test_seed_keeps_adjacent_at_blocks_from_becoming_overlapping_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
sampling:
  every_s: 0.5
targets:
  state:
    samples:
      - at: [0.0, 0.5]
      - at: 0.8
        """,
    )

    async def evaluate(_sample: Any, _target: Any) -> bool:
        return True

    _use_evaluator(monkeypatch, evaluate=evaluate)

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
            )
        )
    )

    assert report.seeded_count == 3
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["targets"]["state"]["samples"] == [
        {"at": [0.0, 0.5], "expect": True},
        {"at": 0.8, "expect": True},
    ]
    assert [sample.timestamp_s for sample in load_eval_directory(eval_dir).samples] == [
        0.0,
        0.5,
        0.8,
    ]


def test_seed_preserves_out_of_time_order_sample_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
sampling:
  every_s: 0.5
targets:
  state:
    samples:
      - at: 1.5
      - range: [0.0, 0.7]
        """,
    )
    calls: list[list[float]] = []

    async def evaluate_many(samples: list[Any], _target: Any) -> list[bool]:
        calls.append([sample.timestamp_s for sample in samples])
        return [True] * len(samples)

    _use_evaluator(monkeypatch, evaluate_many=evaluate_many)

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
            )
        )
    )

    assert report.seeded_count == 3
    assert calls == [[1.5, 0.0, 0.5]]
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["targets"]["state"]["samples"] == [
        {"at": 1.5, "expect": True},
        {"range": [0.0, 0.7], "expect": True},
    ]
    reloaded = load_eval_directory(eval_dir).samples
    assert [sample.timestamp_s for sample in reloaded] == [1.5, 0.0, 0.5]
    assert [sample.sample_index for sample in reloaded] == [0, 1, 2]


def test_seed_replace_and_filters_only_relabel_the_selected_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  first:
    samples:
      - at: 0.0
        expect: keep
  second:
    samples:
      - at: [0.0, 1.0]
        expect: false
        """,
    )
    calls: list[tuple[str, float]] = []

    async def evaluate(sample: Any, target: Any) -> bool:
        calls.append((target.id, sample.timestamp_s))
        return True

    _use_evaluator(monkeypatch, evaluate=evaluate)

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
                target_filter="second",
                replace=True,
            )
        )
    )

    assert report.seeded_count == 2
    assert report.preserved_count == 0
    assert calls == [("second", 0.0), ("second", 1.0)]
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["targets"]["first"]["samples"] == [{"at": 0.0, "expect": "keep"}]
    assert raw["targets"]["second"]["samples"] == [{"at": [0.0, 1.0], "expect": True}]


def test_seed_target_filter_excludes_unrelated_case_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: 0.0
        """,
    )
    (eval_dir / "cases" / "unrelated.yaml").write_text(
        """
video: missing.mp4
targets:
  other:
    samples:
      - at: 0.0
        expect: true
        unsupported: true
        """,
        encoding="utf-8",
    )

    async def evaluate(_sample: Any, _target: Any) -> bool:
        return True

    _use_evaluator(monkeypatch, evaluate=evaluate)

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
                target_filter="state",
            )
        )
    )

    assert report.seeded_count == 1
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["targets"]["state"]["samples"] == [{"at": 0.0, "expect": True}]


def test_seed_rejects_case_membership_changes_during_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: 0.0
        """,
    )
    before = case_path.read_text(encoding="utf-8")
    added_path = eval_dir / "cases" / "added.yaml"

    def load_after_case_added(eval_path: Path, **kwargs: Any) -> EvalDirectory:
        added_path.write_text(
            f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: 1.0
            """,
            encoding="utf-8",
        )
        return load_eval_directory(eval_path, **kwargs)

    monkeypatch.setattr(
        "glasskit.eval.seeding.load_eval_directory", load_after_case_added
    )

    with pytest.raises(EvalConfigError, match="case selection changed.*retry seeding"):
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                )
            )
        )

    assert case_path.read_text(encoding="utf-8") == before


def test_seed_with_no_missing_expectations_does_not_construct_adapter(
    tmp_path: Path,
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: 0.0
        expect: null
        """,
    )
    before = case_path.read_text(encoding="utf-8")

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="missing.py:create_evaluator",
            )
        )
    )

    assert report.seeded_count == 0
    assert report.preserved_count == 1
    assert case_path.read_text(encoding="utf-8") == before


def test_seed_field_error_leaves_draft_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: 0.0
        field: result.matches
        """,
    )
    before = case_path.read_text(encoding="utf-8")

    async def evaluate(_sample: Any, _target: Any) -> dict[str, bool]:
        return {"different": True}

    _use_evaluator(monkeypatch, evaluate=evaluate)

    with pytest.raises(AdapterRuntimeError, match="missing configured field"):
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                )
            )
        )

    assert case_path.read_text(encoding="utf-8") == before


def test_seed_refuses_to_overwrite_a_case_changed_during_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: 0.0
        """,
    )

    async def evaluate(_sample: Any, _target: Any) -> bool:
        case_path.write_text(
            case_path.read_text(encoding="utf-8") + "\n# edited concurrently\n",
            encoding="utf-8",
        )
        return True

    _use_evaluator(monkeypatch, evaluate=evaluate)

    with pytest.raises(EvalConfigError, match="case changed while expectations"):
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                )
            )
        )

    assert case_path.read_text(encoding="utf-8").endswith("# edited concurrently\n")


def test_seed_wraps_case_write_failures_with_the_affected_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: 0.0
        """,
    )
    before = case_path.read_text(encoding="utf-8")

    async def evaluate(_sample: Any, _target: Any) -> bool:
        return True

    def fail_write(_path: Path, _source: str) -> bool:
        raise OSError("read-only file system")

    _use_evaluator(monkeypatch, evaluate=evaluate)
    monkeypatch.setattr("glasskit.eval.seeding.atomic_replace_text", fail_write)

    with pytest.raises(CaseWriteError) as raised:
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                )
            )
        )

    assert str(case_path) in str(raised.value)
    assert "read-only file system" in str(raised.value)
    assert case_path.read_text(encoding="utf-8") == before


def test_seed_supports_process_labeling_adapters(tmp_path: Path) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
sampling:
  every_s: 0.5
targets:
  state:
    samples:
      - range: [0.0, 2.0]
        """,
    )
    command = serialize_command([sys.executable, str(PROCESS_ADAPTER)])

    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter_command=command,
                adapter_config={"booleanByTimestamp": True},
            )
        )
    )

    assert report.seeded_count == 4
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["targets"]["state"]["samples"] == [
        {"range": [0.0, 1.0], "expect": False},
        {"range": [1.0, 2.0], "expect": True},
    ]


def test_seed_resume_reuses_successes_before_a_fail_fast_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
sampling:
  every_s: 0.5
targets:
  state:
    samples:
      - range: [0.0, 2.0]
        """,
    )
    original = case_path.read_text(encoding="utf-8")
    first_calls: list[float] = []

    async def fail_second(sample: Any, _target: Any) -> bool:
        first_calls.append(sample.timestamp_s)
        if sample.timestamp_s == 0.5:
            raise RuntimeError("provider unavailable")
        return sample.timestamp_s >= 1.0

    _use_evaluator(monkeypatch, evaluate=fail_second)
    with pytest.raises(AdapterRuntimeError, match="provider unavailable") as raised:
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                )
            )
        )

    assert first_calls == [0.0, 0.5]
    assert case_path.read_text(encoding="utf-8") == original
    checkpoint_path = raised.value.checkpoint_path
    resumed_calls: list[float] = []

    async def succeed(sample: Any, _target: Any) -> bool:
        resumed_calls.append(sample.timestamp_s)
        return sample.timestamp_s >= 1.0

    _use_evaluator(monkeypatch, evaluate=succeed)
    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
                resume_checkpoint=checkpoint_path,
            )
        )
    )

    assert resumed_calls == [0.5, 1.0, 1.5]
    assert report.seeded_count == 4
    assert [sample.expected for sample in load_eval_directory(eval_dir).samples] == [
        False,
        False,
        True,
        True,
    ]


def test_seed_setup_failure_discards_checkpoint_without_exposing_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, _case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: 0.0
        """,
    )
    callbacks = SeedRecordingCallbacks()

    async def fail_to_load(*args: Any, **kwargs: Any) -> LoadedEvaluator:
        raise AdapterLoadError("provider setup failed")

    monkeypatch.setattr("glasskit.eval.execution.load_evaluator", fail_to_load)
    with pytest.raises(AdapterLoadError, match="provider setup failed") as raised:
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                ),
                callbacks=callbacks,
            )
        )

    assert raised.value.checkpoint_path is None
    assert callbacks.checkpoints == []
    assert list((eval_dir / "runs" / "checkpoints").glob("*")) == []


def test_seed_keep_going_all_adapter_errors_has_no_resumable_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, _case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: [0.0, 1.0]
        """,
    )
    callbacks = SeedRecordingCallbacks()

    async def fail(_sample: Any, _target: Any) -> bool:
        raise RuntimeError("provider unavailable")

    _use_evaluator(monkeypatch, evaluate=fail)
    with pytest.raises(SeedIncompleteError) as raised:
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                    keep_going=True,
                ),
                callbacks=callbacks,
            )
        )

    assert raised.value.checkpoint_path is None
    assert callbacks.checkpoints == []
    assert list((eval_dir / "runs" / "checkpoints").glob("*")) == []


def test_seed_keep_going_checkpoints_replace_without_partial_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
targets:
  state:
    samples:
      - at: [0.0, 1.0]
        expect: false
        """,
    )
    original = case_path.read_text(encoding="utf-8")
    first_calls: list[float] = []

    async def fail_second(sample: Any, _target: Any) -> bool:
        first_calls.append(sample.timestamp_s)
        if sample.timestamp_s == 1.0:
            raise RuntimeError("provider unavailable")
        return True

    _use_evaluator(monkeypatch, evaluate=fail_second)
    with pytest.raises(
        SeedIncompleteError, match="case YAML was not changed"
    ) as raised:
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                    replace=True,
                    keep_going=True,
                )
            )
        )

    assert first_calls == [0.0, 1.0]
    assert case_path.read_text(encoding="utf-8") == original
    checkpoint_path = raised.value.checkpoint_path
    resumed_calls: list[float] = []

    async def succeed(sample: Any, _target: Any) -> bool:
        resumed_calls.append(sample.timestamp_s)
        return True

    _use_evaluator(monkeypatch, evaluate=succeed)
    report = asyncio.run(
        seed_eval(
            SeedOptions(
                eval_dir=eval_dir,
                adapter="unused:create_evaluator",
                replace=True,
                keep_going=True,
                resume_checkpoint=checkpoint_path,
            )
        )
    )

    assert resumed_calls == [1.0]
    assert report.seeded_count == 2
    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    assert raw["targets"]["state"]["samples"] == [{"at": [0.0, 1.0], "expect": True}]


def test_seed_resume_rejects_changed_case_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir, case_path = _write_case(
        tmp_path,
        f"""
video: "{TWO_STATE_VIDEO}"
sampling:
  every_s: 0.5
targets:
  state:
    samples:
      - range: [0.0, 1.0]
        """,
    )

    async def fail_second(sample: Any, _target: Any) -> bool:
        if sample.timestamp_s == 0.5:
            raise RuntimeError("provider unavailable")
        return False

    _use_evaluator(monkeypatch, evaluate=fail_second)
    with pytest.raises(AdapterRuntimeError) as raised:
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                )
            )
        )

    case_path.write_text(
        case_path.read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )
    with pytest.raises(EvalConfigError, match="checkpoint inputs changed"):
        asyncio.run(
            seed_eval(
                SeedOptions(
                    eval_dir=eval_dir,
                    adapter="unused:create_evaluator",
                    resume_checkpoint=raised.value.checkpoint_path,
                )
            )
        )


class BatchLabeler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[float], dict[str, Any]]] = []
        self.closed = False

    async def evaluate_many(self, samples: list[Any], target: Any) -> list[Any]:
        self.calls.append(
            (
                target.id,
                [sample.timestamp_s for sample in samples],
                dict(target.config),
            )
        )
        return [
            {"result": {"matches": sample.timestamp_s >= 1.0}} for sample in samples
        ]

    async def close(self) -> None:
        self.closed = True


class SeedRecordingCallbacks:
    def __init__(self) -> None:
        self.checkpoints: list[Path] = []

    def on_checkpoint(self, path: Path) -> None:
        self.checkpoints.append(path)

    def on_case_start(self, case: Any, sample_count: int) -> None:
        return None

    def on_target_start(self, case: Any, target_id: str, sample_count: int) -> None:
        return None

    def on_result(self, result: Any) -> None:
        return None

    def on_error(self, sample: Any, error: Exception) -> None:
        return None


def _use_evaluator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    evaluate: Any = None,
    evaluate_many: Any = None,
    close: Any = None,
) -> None:
    async def load_evaluator(_target: str, _config: Any) -> LoadedEvaluator:
        return LoadedEvaluator(
            evaluate=evaluate,
            evaluate_many=evaluate_many,
            close=close,
        )

    monkeypatch.setattr("glasskit.eval.execution.load_evaluator", load_evaluator)


def _write_case(tmp_path: Path, source: str) -> tuple[Path, Path]:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    case_path = cases_dir / "case.yaml"
    case_path.write_text(source, encoding="utf-8")
    return eval_dir, case_path
