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
type ResultStatus = Literal["passed", "failed", "error", "ignored"]
type EvaluationTimingMode = Literal["individual", "batch_amortized"]

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

    checkpoint_path: Path | None = None


class EvalConfigError(EvalError):
    """Raised when an eval directory, case, or CLI option is invalid."""


class VideoStoreError(EvalConfigError):
    """Raised when a remote eval video cannot be transferred or cached."""


class AdapterLoadError(EvalError):
    """Raised when an adapter target cannot be imported or constructed."""


class AdapterRuntimeError(EvalError):
    """Raised when an adapter fails while evaluating samples."""


class CaseWriteError(EvalError):
    """Raised when an eval case cannot be persisted."""


class SeedIncompleteError(EvalError):
    """Raised when keep-going seeding finishes with unseeded expectations."""


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
class SampleDefaults:
    field: str | None = None
    compare: ComparisonConfig = dc_field(default_factory=ComparisonConfig)


@dataclass(frozen=True)
class TargetThreshold:
    min_pass_rate: float | None = None


@dataclass(frozen=True)
class Thresholds:
    min_pass_rate: float | None = None
    max_failures: int | None = None
    per_target: Mapping[str, TargetThreshold] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class VideoStore:
    name: str
    bucket: str
    endpoint_url: str | None = None
    region: str = "us-east-1"
    public_base_url: str | None = None
    access_key_id_env: str | None = None
    secret_access_key_env: str | None = None
    session_token_env: str | None = None


@dataclass(frozen=True)
class RemoteVideo:
    store: str
    key: str
    sha256: str

    @property
    def display_name(self) -> str:
        return f"{self.store}:{self.key}"


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
    has_expectation: bool = True
    field: str | None = None
    compare: ComparisonConfig = dc_field(default_factory=ComparisonConfig)
    source: str = ""
    comment: str | None = None
    ignore: str | None = None


@dataclass(frozen=True)
class TargetSpec:
    id: str
    index: int
    label: str | None
    config: Mapping[str, Any]
    samples: list[SampleExpectation]
    sample_defaults: SampleDefaults = dc_field(default_factory=SampleDefaults)


@dataclass(frozen=True)
class EvalCase:
    name: str
    path: Path
    video_path: Path
    description: str | None
    targets: list[TargetSpec]
    thresholds: Thresholds = dc_field(default_factory=Thresholds)
    remote_video: RemoteVideo | None = None

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
class SeededExpectation:
    sample: SampleExpectation
    expected: Any
    evaluation_duration_s: float
    evaluation_timing_mode: EvaluationTimingMode


@dataclass(frozen=True)
class SeedReport:
    eval_dir: Path
    case_names: list[str]
    seeded: list[SeededExpectation]
    preserved_count: int
    duration_s: float
    directory_sync_warnings: tuple[Path, ...] = ()

    @property
    def seeded_count(self) -> int:
        return len(self.seeded)


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
    evaluation_duration_s: float | None = None
    evaluation_timing_mode: EvaluationTimingMode | None = None
    artifact_image: str | None = None
    artifact_json: str | None = None


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class EvalTrialReport:
    index: int
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
    def ignored_count(self) -> int:
        return sum(1 for result in self.results if result.status == "ignored")

    @property
    def evaluated_count(self) -> int:
        return len(self.results) - self.ignored_count

    @property
    def pass_rate(self) -> float:
        if self.evaluated_count == 0:
            return 0.0
        return self.passed_count / self.evaluated_count

    @property
    def average_evaluation_duration_s(self) -> float | None:
        durations = [
            result.evaluation_duration_s
            for result in self.results
            if result.status != "ignored" and result.evaluation_duration_s is not None
        ]
        if not durations:
            return None
        return sum(durations) / len(durations)

    @property
    def evaluation_timing_mode(
        self,
    ) -> EvaluationTimingMode | Literal["mixed"] | None:
        modes = {
            result.evaluation_timing_mode
            for result in self.results
            if result.status != "ignored" and result.evaluation_timing_mode is not None
        }
        if not modes:
            return None
        if len(modes) == 1:
            return next(iter(modes))
        return "mixed"

    @property
    def throughput_samples_per_s(self) -> float:
        if self.evaluated_count == 0 or self.duration_s <= 0:
            return 0.0
        return self.evaluated_count / self.duration_s

    @property
    def success(self) -> bool:
        return all(gate.passed for gate in self.gate_results)


@dataclass(frozen=True)
class SampleStability:
    case_name: str
    target_id: str
    target_label: str | None
    sample_index: int
    timestamp_s: float
    expected: Any
    source: str
    statuses: tuple[ResultStatus, ...]

    @property
    def evaluated_count(self) -> int:
        return sum(status != "ignored" for status in self.statuses)

    @property
    def passed_count(self) -> int:
        return self.statuses.count("passed")

    @property
    def failed_count(self) -> int:
        return self.statuses.count("failed")

    @property
    def error_count(self) -> int:
        return self.statuses.count("error")

    @property
    def pass_rate(self) -> float | None:
        if self.evaluated_count == 0:
            return None
        return self.passed_count / self.evaluated_count

    @property
    def ignored(self) -> bool:
        return all(status == "ignored" for status in self.statuses)

    @property
    def consistently_passed(self) -> bool:
        return bool(self.statuses) and all(
            status == "passed" for status in self.statuses
        )

    @property
    def consistently_failed(self) -> bool:
        return bool(self.statuses) and all(
            status == "failed" for status in self.statuses
        )

    @property
    def flaky(self) -> bool:
        return not self.ignored and len(set(self.statuses)) > 1

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0


@dataclass(frozen=True)
class EvalRunReport:
    eval_dir: Path
    case_names: list[str]
    trials: list[EvalTrialReport]
    stability: list[SampleStability]
    gate_results: list[GateResult]
    duration_s: float
    checkpoint_path: Path | None = None
    resumed: bool = False
    resumable_error_count: int = 0

    @property
    def repeat_count(self) -> int:
        return len(self.trials)

    @property
    def successful_trial_count(self) -> int:
        return sum(trial.success for trial in self.trials)

    @property
    def evaluated_sample_count(self) -> int:
        return sum(not sample.ignored for sample in self.stability)

    @property
    def ignored_sample_count(self) -> int:
        return sum(sample.ignored for sample in self.stability)

    @property
    def attempt_results(self) -> list[SampleResult]:
        return [result for trial in self.trials for result in trial.results]

    @property
    def evaluated_attempt_count(self) -> int:
        return sum(trial.evaluated_count for trial in self.trials)

    @property
    def passed_attempt_count(self) -> int:
        return sum(trial.passed_count for trial in self.trials)

    @property
    def failed_attempt_count(self) -> int:
        return sum(trial.failed_count for trial in self.trials)

    @property
    def error_attempt_count(self) -> int:
        return sum(trial.error_count for trial in self.trials)

    @property
    def attempt_pass_rate(self) -> float:
        if self.evaluated_attempt_count == 0:
            return 0.0
        return self.passed_attempt_count / self.evaluated_attempt_count

    @property
    def minimum_trial_pass_rate(self) -> float:
        return min((trial.pass_rate for trial in self.trials), default=0.0)

    @property
    def mean_trial_pass_rate(self) -> float:
        if not self.trials:
            return 0.0
        return sum(trial.pass_rate for trial in self.trials) / len(self.trials)

    @property
    def maximum_trial_pass_rate(self) -> float:
        return max((trial.pass_rate for trial in self.trials), default=0.0)

    @property
    def consistently_passed_sample_count(self) -> int:
        return sum(sample.consistently_passed for sample in self.stability)

    @property
    def consistently_failed_sample_count(self) -> int:
        return sum(sample.consistently_failed for sample in self.stability)

    @property
    def flaky_sample_count(self) -> int:
        return sum(sample.flaky for sample in self.stability)

    @property
    def error_sample_count(self) -> int:
        return sum(sample.has_errors for sample in self.stability)

    @property
    def average_evaluation_duration_s(self) -> float | None:
        durations = [
            result.evaluation_duration_s
            for result in self.attempt_results
            if result.status != "ignored" and result.evaluation_duration_s is not None
        ]
        if not durations:
            return None
        return sum(durations) / len(durations)

    @property
    def evaluation_timing_mode(
        self,
    ) -> EvaluationTimingMode | Literal["mixed"] | None:
        modes = {
            result.evaluation_timing_mode
            for result in self.attempt_results
            if result.status != "ignored" and result.evaluation_timing_mode is not None
        }
        if not modes:
            return None
        if len(modes) == 1:
            return next(iter(modes))
        return "mixed"

    @property
    def throughput_attempts_per_s(self) -> float:
        if self.evaluated_attempt_count == 0 or self.duration_s <= 0:
            return 0.0
        return self.evaluated_attempt_count / self.duration_s

    @property
    def success(self) -> bool:
        return all(trial.success for trial in self.trials) and all(
            gate.passed for gate in self.gate_results
        )


@dataclass(frozen=True)
class RunOptions:
    eval_dir: Path
    adapter: str | None = None
    adapter_command: str | None = None
    case_filter: str | None = None
    target_filter: str | tuple[str, ...] | None = None
    at_times_s: tuple[float, ...] | None = None
    from_time_s: float | None = None
    until_time_s: float | None = None
    adapter_config: Mapping[str, Any] = dc_field(default_factory=dict)
    concurrency: int = 1
    repeat: int = 1
    min_pass_rate: float | None = None
    min_target_pass_rate: float | None = None
    max_failures: int | None = None
    max_flaky_samples: int | None = None
    keep_going: bool = False
    verbose: bool = False
    output_json: Path | None = None
    artifacts_dir: Path | None = None
    save_failures: bool = False
    allow_empty: bool = False
    resume_checkpoint: Path | None = None


@dataclass(frozen=True)
class SeedOptions:
    eval_dir: Path
    adapter: str | None = None
    adapter_command: str | None = None
    case_filter: str | None = None
    target_filter: str | tuple[str, ...] | None = None
    adapter_config: Mapping[str, Any] = dc_field(default_factory=dict)
    concurrency: int = 1
    replace: bool = False
    keep_going: bool = False
    verbose: bool = False
    resume_checkpoint: Path | None = None
