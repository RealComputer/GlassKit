from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .json_values import json_value_error
from .models import SUPPORTED_COMPARE_MODES, EvalConfigError

DEFAULT_EVERY_S = 0.5


class _SchemaModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        loc_by_alias=True,
        populate_by_name=True,
    )


class RawCompare(_SchemaModel):
    mode: str | None = None
    tolerance: float | None = None

    @field_validator("mode")
    @classmethod
    def _strip_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        if stripped not in SUPPORTED_COMPARE_MODES:
            supported = ", ".join(sorted(SUPPORTED_COMPARE_MODES))
            raise ValueError(
                f"unsupported compare mode {stripped!r}; expected one of: {supported}"
            )
        return stripped

    @field_validator("tolerance", mode="before")
    @classmethod
    def _validate_tolerance(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _number(value, label="tolerance", minimum=0.0)


class RawSampling(_SchemaModel):
    every_s: float = DEFAULT_EVERY_S

    @field_validator("every_s", mode="before")
    @classmethod
    def _validate_every_s(cls, value: Any) -> float:
        return _number(value, label="every_s", minimum=0.0, exclusive_minimum=True)


class RawSampleBlock(_SchemaModel):
    range_: list[float] | None = Field(default=None, alias="range")
    at: float | list[float] | None = None
    expect: Any
    every_s: float | None = None
    field: str | None = None
    compare: RawCompare | None = None

    @field_validator("expect")
    @classmethod
    def _validate_expect(cls, value: Any) -> Any:
        if error := json_value_error(value, label="expect"):
            raise ValueError(error)
        return value

    @field_validator("range_", mode="before")
    @classmethod
    def _validate_range(cls, value: Any) -> list[float] | None:
        if value is None:
            return None
        if not isinstance(value, list | tuple) or len(value) != 2:
            raise ValueError("must be [start, end]")
        start = _number(value[0], label="range start", minimum=0.0)
        end = _number(value[1], label="range end", minimum=0.0)
        if end <= start:
            raise ValueError("end must be greater than start")
        return [start, end]

    @field_validator("at", mode="before")
    @classmethod
    def _validate_at(cls, value: Any) -> float | list[float] | None:
        if value is None:
            return None
        if isinstance(value, list | tuple):
            if not value:
                raise ValueError("must contain at least one timestamp")
            return [_number(item, label="at", minimum=0.0) for item in value]
        return _number(value, label="at", minimum=0.0)

    @field_validator("every_s", mode="before")
    @classmethod
    def _validate_every_s(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _number(value, label="every_s", minimum=0.0, exclusive_minimum=True)

    @field_validator("field")
    @classmethod
    def _strip_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @model_validator(mode="after")
    def _validate_sample_location(self) -> RawSampleBlock:
        if (self.range_ is None) == (self.at is None):
            raise ValueError("must contain exactly one of range or at")
        return self


class RawTarget(_SchemaModel):
    label: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    samples: list[RawSampleBlock]

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class RawWorkflowTarget(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        loc_by_alias=True,
        populate_by_name=True,
    )

    id: str
    label: str | None = None

    @field_validator("id", "label")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class RawWorkflow(_SchemaModel):
    targets: list[RawWorkflowTarget] = Field(default_factory=list)


class RawTargetThreshold(_SchemaModel):
    min_pass_rate: float | None = None

    @field_validator("min_pass_rate", mode="before")
    @classmethod
    def _validate_min_pass_rate(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _number(value, label="min_pass_rate", minimum=0.0, maximum=1.0)


class RawThresholds(_SchemaModel):
    min_pass_rate: float | None = None
    max_failures: int | None = None
    per_target: dict[str, RawTargetThreshold] = Field(default_factory=dict)

    @field_validator("min_pass_rate", mode="before")
    @classmethod
    def _validate_min_pass_rate(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _number(value, label="min_pass_rate", minimum=0.0, maximum=1.0)

    @field_validator("max_failures", mode="before")
    @classmethod
    def _validate_max_failures(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be an integer")
        if value < 0:
            raise ValueError("must be greater than or equal to 0")
        return value

    @field_validator("per_target")
    @classmethod
    def _validate_per_target_ids(
        cls, value: dict[str, RawTargetThreshold]
    ) -> dict[str, RawTargetThreshold]:
        _validate_mapping_keys(value, label="per_target")
        return value


class RawCaseYaml(_SchemaModel):
    version: int = 1
    video: str
    description: str | None = None
    sampling: RawSampling = Field(default_factory=RawSampling)
    workflow: RawWorkflow = Field(default_factory=RawWorkflow)
    targets: dict[str, RawTarget]
    thresholds: RawThresholds = Field(default_factory=RawThresholds)

    @field_validator("version", mode="before")
    @classmethod
    def _validate_version(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be 1")
        if value != 1:
            raise ValueError("must be 1")
        return value

    @field_validator("video", "description")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @field_validator("targets")
    @classmethod
    def _validate_targets(cls, value: dict[str, RawTarget]) -> dict[str, RawTarget]:
        if not value:
            raise ValueError("must contain at least one target")
        _validate_mapping_keys(value, label="targets")
        return value


class RawEvalConfigYaml(_SchemaModel):
    thresholds: RawThresholds = Field(default_factory=RawThresholds)


def parse_case_yaml(raw: Any, *, label: str) -> RawCaseYaml:
    return _parse_model(RawCaseYaml, raw, label=label)


def parse_eval_config_yaml(raw: Any, *, label: str) -> RawEvalConfigYaml:
    return _parse_model(RawEvalConfigYaml, raw, label=label)


def workflow_target_metadata(target: RawWorkflowTarget) -> dict[str, Any]:
    data = target.model_dump(exclude={"id", "label"}, by_alias=True)
    extra = target.__pydantic_extra__ or {}
    data.update(extra)
    if target.label is not None:
        data["label"] = target.label
    return data


def _validate_mapping_keys(value: Mapping[str, Any], *, label: str) -> None:
    for key in value:
        if not isinstance(key, str):
            raise ValueError(f"{label} keys must be strings")
        if not key.strip():
            raise ValueError(f"{label} keys must not be empty")
        if key != key.strip():
            raise ValueError(f"{label} keys must not have surrounding whitespace")


def _parse_model[T: BaseModel](model_type: type[T], raw: Any, *, label: str) -> T:
    try:
        return model_type.model_validate(raw)
    except ValidationError as error:
        raise EvalConfigError(
            f"{label}: invalid schema: {_format_errors(error)}"
        ) from error


def _format_errors(error: ValidationError) -> str:
    parts: list[str] = []
    for item in error.errors():
        loc = ".".join(str(part) for part in item["loc"])
        message = str(item["msg"])
        parts.append(f"{loc}: {message}" if loc else message)
    return "; ".join(parts)


def _number(
    value: Any,
    *,
    label: str,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a number") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    if minimum is not None:
        if exclusive_minimum and parsed <= minimum:
            raise ValueError(f"{label} must be greater than {minimum:g}")
        if not exclusive_minimum and parsed < minimum:
            raise ValueError(f"{label} must be greater than or equal to {minimum:g}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{label} must be less than or equal to {maximum:g}")
    return parsed
