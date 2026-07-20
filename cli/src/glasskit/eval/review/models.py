from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

type ExpectType = Literal["null", "boolean", "number", "string", "array", "object"]
type GroupKind = Literal["at", "range"]
type CaseStatus = Literal["ready", "repairable", "blocked"]
type SummaryStatus = Literal["ready", "blocked"]
type IssueSeverity = Literal["error", "warning"]


def _validate_unicode_scalar(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("must contain valid Unicode scalar values") from error
    return value


class ReviewAPIError(Exception):
    """An expected operation failure that maps to a structured HTTP response."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []


class TransportModel(BaseModel):
    """Strict base model for the private browser/server transport."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ErrorDetail(TransportModel):
    path: str | None = None
    message: str


class ErrorContent(TransportModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(TransportModel):
    error: ErrorContent


class LoadError(TransportModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ValidationIssue(TransportModel):
    code: str
    message: str
    path: str | None = None
    severity: IssueSeverity = "error"
    repairable: bool = False


class SampleCompare(TransportModel):
    mode: str | None = None
    tolerance: float | None = None

    @field_validator("mode")
    @classmethod
    def _normalize_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return _validate_unicode_scalar(normalized)

    @field_validator("tolerance")
    @classmethod
    def _validate_tolerance(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or value < 0:
            raise ValueError("must be a finite, nonnegative number")
        return value


class ReviewSampleDefaults(TransportModel):
    field: str | None = None
    compare: SampleCompare = Field(default_factory=SampleCompare)


class SampleOrigin(TransportModel):
    block_index: Annotated[int, Field(ge=1)]
    kind: GroupKind
    every_s: float | None = None

    @field_validator("every_s")
    @classmethod
    def _validate_every_s(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or value <= 0:
            raise ValueError("must be a finite number greater than zero")
        return value

    @model_validator(mode="after")
    def _validate_shape(self) -> SampleOrigin:
        if self.kind == "range" and self.every_s is None:
            raise ValueError("range origins require every_s")
        if self.kind == "at" and self.every_s is not None:
            raise ValueError("at origins cannot contain every_s")
        return self


class ReviewSample(TransportModel):
    id: str
    timestamp_s: float
    has_expectation: bool = True
    expect_type: ExpectType
    expect_json: str
    field: str | None = None
    compare: SampleCompare = Field(default_factory=SampleCompare)
    comment: str | None = None
    ignore: str | None = None
    origin: SampleOrigin | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return _validate_unicode_scalar(value)

    @field_validator("timestamp_s")
    @classmethod
    def _canonicalize_timestamp(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("must be a finite, nonnegative number")
        return round(value, 9)

    @field_validator("expect_json")
    @classmethod
    def _validate_expect_json(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain one JSON value")
        return _validate_unicode_scalar(value)

    @field_validator("field", "comment", "ignore")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank; use null to omit it")
        return _validate_unicode_scalar(normalized)


class DisplayGroup(TransportModel):
    id: str
    kind: GroupKind
    sample_ids: list[str]
    start_s: float | None = None
    end_s: float | None = None
    every_s: float | None = None
    timestamps_s: list[float]

    @model_validator(mode="after")
    def _validate_shape(self) -> DisplayGroup:
        if len(self.sample_ids) != len(self.timestamps_s) or not self.sample_ids:
            raise ValueError(
                "sample_ids and timestamps_s must have equal nonzero length"
            )
        range_fields = (self.start_s, self.end_s, self.every_s)
        if self.kind == "range" and any(value is None for value in range_fields):
            raise ValueError("range groups require start_s, end_s, and every_s")
        if self.kind == "at" and any(value is not None for value in range_fields):
            raise ValueError("at groups cannot contain range fields")
        return self


class TargetDocument(TransportModel):
    id: str
    label: str | None = None
    details_yaml: str
    sample_defaults: ReviewSampleDefaults = Field(default_factory=ReviewSampleDefaults)
    samples: list[ReviewSample]
    display_groups: list[DisplayGroup]


class VideoDocument(TransportModel):
    url: str | None = None
    display_path: str
    content_type: str | None = None
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    frame_count: int | None = None

    @field_validator("display_path")
    @classmethod
    def _validate_display_path(cls, value: str) -> str:
        return _validate_unicode_scalar(value)


class CaseFileDocument(TransportModel):
    id: str
    name: str
    revision: str
    status: CaseStatus
    editing_enabled: bool
    load_error: LoadError | None = None
    description: str | None = None
    case_file_source: str
    video: VideoDocument | None = None
    targets: list[TargetDocument]
    validation_issues: list[ValidationIssue]


class CaseFileSummary(TransportModel):
    id: str
    name: str
    file_name: str
    description: str | None = None
    target_count: int | None = None
    sample_count: int | None = None
    status: SummaryStatus
    error: LoadError | None = None


class EvalDirectoryDocument(TransportModel):
    eval_dir: str
    write_token: str
    eval_config_source: str | None = None
    cases: list[CaseFileSummary]


class TargetReplacement(TransportModel):
    samples: list[ReviewSample]


class ReplaceSamplesRequest(TransportModel):
    targets: dict[str, TargetReplacement]

    @field_validator("targets")
    @classmethod
    def _validate_targets(
        cls, value: dict[str, TargetReplacement]
    ) -> dict[str, TargetReplacement]:
        if not value:
            raise ValueError("must contain at least one target")
        if any(not target_id for target_id in value):
            raise ValueError("target ids must not be empty")
        for target_id in value:
            _validate_unicode_scalar(target_id)
        return value
