from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any, Literal, Protocol

from PIL import Image

type JSONValue = (
    None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
)
type ResultStatus = Literal["passed", "failed", "error"]

SUPPORTED_COMPARE_MODES = frozenset(
    {
        "exact",
        "numeric",
        "json_subset",
        "set_equals",
        "set_contains_any",
        "set_contains_all",
    }
)


class EvalError(Exception):
    """Base exception for user-facing eval failures."""


class EvalConfigError(EvalError):
    """Raised when an eval directory, case, or CLI option is invalid."""


class AdapterLoadError(EvalError):
    """Raised when an adapter target cannot be imported or constructed."""


class AdapterRuntimeError(EvalError):
    """Raised when an adapter fails while evaluating samples."""


@dataclass(frozen=True)
class AdapterConfig:
    eval_dir: Path
    config: Mapping[str, Any] = dc_field(default_factory=dict)
    artifacts_dir: Path | None = None
    verbose: bool = False


@dataclass(frozen=True)
class FrameSample:
    image: Image.Image
    timestamp_s: float
    frame_index: int
    sample_index: int
    video_path: str
    case_name: str


@dataclass(frozen=True)
class TargetContext:
    id: str
    index: int
    label: str | None = None
    config: Mapping[str, Any] = dc_field(default_factory=dict)


class FrameEvaluator(Protocol):
    def evaluate(
        self, sample: FrameSample, target: TargetContext
    ) -> JSONValue | Awaitable[JSONValue]: ...


class BatchFrameEvaluator(Protocol):
    def evaluate_many(
        self, samples: list[FrameSample], target: TargetContext
    ) -> list[JSONValue] | Awaitable[list[JSONValue]]: ...


@dataclass(frozen=True)
class ComparisonConfig:
    mode: str | None = None
    tolerance: float | None = None
    raw: Mapping[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class TargetThreshold:
    min_pass_rate: float | None = None


@dataclass(frozen=True)
class Thresholds:
    min_pass_rate: float | None = None
    max_failures: int | None = None
    per_target: Mapping[str, TargetThreshold] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class SampleExpectation:
    case_name: str
    target_id: str
    target_index: int
    target_label: str | None
    target_config: Mapping[str, Any]
    video_path: Path
    timestamp_s: float
    sample_index: int
    expected: Any
    field: str | None = None
    compare: ComparisonConfig = dc_field(default_factory=ComparisonConfig)
    source: str = ""
    comment: str | None = None


@dataclass(frozen=True)
class TargetSpec:
    id: str
    index: int
    label: str | None
    config: Mapping[str, Any]
    samples: list[SampleExpectation]


@dataclass(frozen=True)
class EvalCase:
    name: str
    path: Path
    video_path: Path
    description: str | None
    targets: list[TargetSpec]
    thresholds: Thresholds = dc_field(default_factory=Thresholds)

    @property
    def samples(self) -> list[SampleExpectation]:
        return [sample for target in self.targets for sample in target.samples]


@dataclass(frozen=True)
class EvalDirectory:
    path: Path
    cases: list[EvalCase]
    thresholds: Thresholds = dc_field(default_factory=Thresholds)

    @property
    def samples(self) -> list[SampleExpectation]:
        return [sample for case in self.cases for sample in case.samples]


@dataclass(frozen=True)
class VideoMetadata:
    path: Path
    duration_s: float
    width: int
    height: int
    frame_count: int | None = None


@dataclass(frozen=True)
class ValidationIssue:
    message: str
    severity: Literal["error", "warning"] = "error"
    path: Path | None = None


@dataclass(frozen=True)
class ValidationReport:
    eval_directory: EvalDirectory | None
    issues: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True)
class CompareOutcome:
    passed: bool
    reason: str
    observed_value: Any
    mode: str


@dataclass(frozen=True)
class SampleResult:
    case_name: str
    target_id: str
    target_label: str | None
    sample_index: int
    timestamp_s: float
    status: ResultStatus
    expected: Any
    observed: Any
    observed_value: Any
    compare_mode: str | None
    field: str | None
    reason: str
    source: str
    artifact_image: str | None = None
    artifact_json: str | None = None


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class EvalRunReport:
    eval_dir: Path
    case_names: list[str]
    results: list[SampleResult]
    gate_results: list[GateResult]
    duration_s: float

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.results if result.status == "passed")

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.results if result.status == "failed")

    @property
    def error_count(self) -> int:
        return sum(1 for result in self.results if result.status == "error")

    @property
    def evaluated_count(self) -> int:
        return len(self.results)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return self.passed_count / len(self.results)

    @property
    def success(self) -> bool:
        return all(gate.passed for gate in self.gate_results)


@dataclass(frozen=True)
class RunOptions:
    eval_dir: Path
    adapter: str | None = None
    case_filter: str | None = None
    target_filter: str | None = None
    adapter_config: Mapping[str, Any] = dc_field(default_factory=dict)
    concurrency: int = 1
    min_pass_rate: float | None = None
    min_target_pass_rate: float | None = None
    max_failures: int | None = None
    keep_going: bool = False
    verbose: bool = False
    output_json: Path | None = None
    artifacts_dir: Path | None = None
    save_failures: bool = False
    max_failures_to_print: int = 20
    allow_empty: bool = False
