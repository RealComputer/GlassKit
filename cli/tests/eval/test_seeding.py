from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from glasskit.eval.adapters import LoadedEvaluator
from glasskit.eval.expectations import load_eval_directory
from glasskit.eval.models import (
    AdapterRuntimeError,
    CaseWriteError,
    EvalConfigError,
    EvalDirectory,
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
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(PROCESS_ADAPTER))}"

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
