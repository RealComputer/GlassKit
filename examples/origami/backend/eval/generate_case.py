from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import os
import secrets
import sys
import time
from collections import defaultdict
from collections.abc import Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import av
import yaml
from av import VideoFrame
from av.error import FFmpegError
from google import genai
from PIL import Image

from src.fold_check import (
    compose_fold_check_image,
    load_fold_check_reference_images,
    load_fold_check_steps,
    parse_fold_check_result,
)
from src.fold_check_prompts import (
    FOLD_CHECK_CRITERIA_PREFIX,
    FOLD_CHECK_SYSTEM_PROMPT,
    fold_check_criteria_text,
)
from src.origami_config import OrigamiStep

BACKEND_DIR = Path(__file__).resolve().parents[1]

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_SERVICE_TIER = "flex"
GEMINI_IMAGE_RESOLUTION = "high"
GEMINI_THINKING_LEVEL = "medium"
JPEG_QUALITY = 90
CACHE_VERSION = 1
DEFAULT_EVERY_S = 0.5
DEFAULT_CONCURRENCY = 8
TIME_EPSILON = 1e-9


@dataclass(frozen=True)
class TargetRange:
    start_s: float
    end_s: float


@dataclass(frozen=True)
class TargetPlan:
    id: str
    label: str | None
    ranges: list[TargetRange]


@dataclass(frozen=True)
class LabelPlan:
    path: Path
    video_path: Path
    description: str | None
    every_s: float
    targets: list[TargetPlan]


@dataclass(frozen=True)
class SampleRequest:
    target_id: str
    timestamp_s: float
    interval_end_s: float
    next_grid_timestamp_s: float
    cache_key: str


@dataclass(frozen=True)
class GeminiResult:
    value: bool
    response_text: str
    interaction_id: str | None


@dataclass(frozen=True)
class LabeledSample:
    request: SampleRequest
    result: GeminiResult
    elapsed_s: float


@dataclass(frozen=True)
class ExistingCase:
    raw: dict[str, Any]
    source_text: str


class _FlowList(list[float]):
    pass


class _CaseYamlDumper(yaml.SafeDumper):
    """Dumper with compact ranges matching the review UI's case output."""


def _represent_flow_list(
    dumper: yaml.SafeDumper,
    data: _FlowList,
) -> yaml.SequenceNode:
    return dumper.represent_sequence(
        "tag:yaml.org,2002:seq",
        data,
        flow_style=True,
    )


_CaseYamlDumper.add_representer(_FlowList, _represent_flow_list)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    output_path = _resolve_cli_path(args.output)
    cache_path = _default_cache_path(output_path)
    try:
        _run_generation(
            plan_path=_resolve_cli_path(args.plan),
            output_path=output_path,
            target_ids=set(args.target or []),
            cache_path=cache_path,
            concurrency=args.concurrency,
        )
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr, flush=True)
        _print_resume_cache_hint(cache_path)
        return 130
    except Exception as error:
        print(f"error: {error}", file=sys.stderr, flush=True)
        _print_resume_cache_hint(cache_path)
        return 1
    return 0


def _print_resume_cache_hint(cache_path: Path) -> None:
    if not cache_path.exists():
        return
    print(f"partial cache kept at {cache_path}", file=sys.stderr, flush=True)
    print(
        "rerun the same command to resume; delete this file to start over",
        file=sys.stderr,
        flush=True,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a glasskit eval case by labeling planned origami target ranges "
            f"with {GEMINI_MODEL}."
        )
    )
    parser.add_argument(
        "--plan",
        required=True,
        type=Path,
        help="YAML file with video, sampling.every_s, and targets.<id>.range.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help=(
            "Case YAML to create or overwrite, usually under eval/cases/. With "
            "--target, an existing case is updated only for the selected targets."
        ),
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help=(
            "Target id to label or update. Repeat to select multiple targets. "
            "Defaults to regenerating the whole case."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int_arg,
        default=DEFAULT_CONCURRENCY,
        help=f"Maximum concurrent Gemini calls. Defaults to {DEFAULT_CONCURRENCY}.",
    )
    return parser.parse_args(argv)


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _run_generation(
    *,
    plan_path: Path,
    output_path: Path,
    target_ids: set[str],
    cache_path: Path,
    concurrency: int,
) -> None:
    run_start_s = time.monotonic()
    plan = _load_label_plan(plan_path, target_ids=target_ids)
    existing_case = (
        _load_existing_case_for_target_update(output_path, plan=plan)
        if target_ids and output_path.exists()
        else None
    )
    steps = {
        step.id: step
        for step in load_fold_check_steps(BACKEND_DIR / "assets" / "origami_steps.json")
    }
    _validate_targets(plan, steps)
    reference_images = load_fold_check_reference_images(steps.values())
    requests_by_target = _build_requests(plan, steps=steps)
    requests = [
        request for target in plan.targets for request in requests_by_target[target.id]
    ]
    if not requests:
        raise RuntimeError("plan produced no sample requests")

    expected_cache_keys = {request.cache_key for request in requests}
    results = _load_cached_results(cache_path, expected_cache_keys)
    missing_requests = [
        request for request in requests if request.cache_key not in results
    ]
    call_text = f"{len(missing_requests)} Gemini calls"
    if missing_requests:
        call_text += f", concurrency {concurrency}"
    print(
        f"labeling {len(requests)} samples ({len(results)} cached, {call_text})",
        flush=True,
    )

    gemini_durations: list[float] = []
    gemini_wall_s = 0.0
    if missing_requests:
        gemini_start_s = time.monotonic()
        gemini_durations = _label_missing_requests(
            plan=plan,
            steps=steps,
            reference_images=reference_images,
            requests=requests,
            missing_requests=missing_requests,
            results=results,
            cache_path=cache_path,
            concurrency=concurrency,
        )
        gemini_wall_s = time.monotonic() - gemini_start_s

    missing_keys = expected_cache_keys - set(results)
    if missing_keys:
        raise RuntimeError(f"missing {len(missing_keys)} sample results")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_case_yaml(
        output_path,
        plan=plan,
        requests_by_target=requests_by_target,
        results=results,
        existing_case=existing_case,
    )
    if cache_path.exists():
        cache_path.unlink()
    print(f"wrote {output_path}", flush=True)
    print(
        _format_completion_summary(
            total_samples=len(requests),
            cached_samples=len(requests) - len(gemini_durations),
            gemini_durations=gemini_durations,
            gemini_wall_s=gemini_wall_s,
            total_elapsed_s=time.monotonic() - run_start_s,
        ),
        flush=True,
    )


def _load_label_plan(path: Path, *, target_ids: set[str]) -> LabelPlan:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("plan YAML must be an object")

    video_raw = _required_string(raw, "video")
    video_path = _resolve_plan_path(path.parent, video_raw)
    if not video_path.exists():
        raise RuntimeError(f"video not found: {video_path}")

    sampling = raw.get("sampling")
    every_s = DEFAULT_EVERY_S
    if sampling is not None:
        if not isinstance(sampling, dict):
            raise RuntimeError("sampling must be an object")
        every_s = _positive_number(sampling.get("every_s", DEFAULT_EVERY_S), "every_s")

    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, dict) or not targets_raw:
        raise RuntimeError("targets must be a non-empty object")

    targets: list[TargetPlan] = []
    for target_id, target_raw in targets_raw.items():
        if not isinstance(target_id, str) or not target_id.strip():
            raise RuntimeError("target ids must be non-empty strings")
        clean_id = target_id.strip()
        if target_ids and clean_id not in target_ids:
            continue
        targets.append(_parse_target_plan(clean_id, target_raw))

    if target_ids:
        found_ids = {target.id for target in targets}
        missing_ids = sorted(target_ids - found_ids)
        if missing_ids:
            raise RuntimeError(f"target not found in plan: {', '.join(missing_ids)}")
    if not targets:
        raise RuntimeError("target filter selected no targets")

    description = raw.get("description")
    return LabelPlan(
        path=path,
        video_path=video_path,
        description=_optional_string(description, "description"),
        every_s=every_s,
        targets=targets,
    )


def _parse_target_plan(target_id: str, raw: Any) -> TargetPlan:
    if not isinstance(raw, dict):
        raise RuntimeError(f"targets.{target_id} must be an object")

    ranges_raw = raw.get("ranges")
    range_raw = raw.get("range")
    if (ranges_raw is None) == (range_raw is None):
        raise RuntimeError(
            f"targets.{target_id} must contain exactly one of range or ranges"
        )

    ranges = (
        [_parse_range(range_raw, label=f"targets.{target_id}.range")]
        if range_raw is not None
        else _parse_ranges(ranges_raw, label=f"targets.{target_id}.ranges")
    )
    label = _optional_string(raw.get("label"), f"targets.{target_id}.label")
    return TargetPlan(id=target_id, label=label, ranges=ranges)


def _parse_ranges(raw: Any, *, label: str) -> list[TargetRange]:
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"{label} must be a non-empty list of ranges")
    return [
        _parse_range(item, label=f"{label}[{index}]") for index, item in enumerate(raw)
    ]


def _parse_range(raw: Any, *, label: str) -> TargetRange:
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        raise RuntimeError(f"{label} must be [start, end]")
    start_s = _nonnegative_number(raw[0], f"{label}[0]")
    end_s = _nonnegative_number(raw[1], f"{label}[1]")
    if end_s <= start_s:
        raise RuntimeError(f"{label} end must be greater than start")
    return TargetRange(start_s=start_s, end_s=end_s)


def _validate_targets(plan: LabelPlan, steps: dict[str, OrigamiStep]) -> None:
    unknown_ids = sorted(target.id for target in plan.targets if target.id not in steps)
    if unknown_ids:
        raise RuntimeError(f"unknown origami target id: {', '.join(unknown_ids)}")


def _build_requests(
    plan: LabelPlan,
    *,
    steps: dict[str, OrigamiStep],
) -> dict[str, list[SampleRequest]]:
    requests_by_target: dict[str, list[SampleRequest]] = {}
    for target in plan.targets:
        requests: list[SampleRequest] = []
        for target_range in target.ranges:
            timestamp_s = target_range.start_s
            while timestamp_s < target_range.end_s - TIME_EPSILON:
                interval_end_s = min(
                    target_range.end_s,
                    timestamp_s + plan.every_s,
                )
                requests.append(
                    SampleRequest(
                        target_id=target.id,
                        timestamp_s=_time_value(timestamp_s),
                        interval_end_s=_time_value(interval_end_s),
                        next_grid_timestamp_s=_time_value(timestamp_s + plan.every_s),
                        cache_key=_sample_cache_key(
                            plan=plan,
                            target_id=target.id,
                            step=steps[target.id],
                            timestamp_s=timestamp_s,
                            interval_end_s=interval_end_s,
                        ),
                    )
                )
                timestamp_s += plan.every_s
        requests_by_target[target.id] = requests
    return requests_by_target


def _sample_cache_key(
    *,
    plan: LabelPlan,
    target_id: str,
    step: OrigamiStep,
    timestamp_s: float,
    interval_end_s: float,
) -> str:
    payload = {
        "cache_version": CACHE_VERSION,
        "model": GEMINI_MODEL,
        "service_tier": GEMINI_SERVICE_TIER,
        "image_resolution": GEMINI_IMAGE_RESOLUTION,
        "thinking_level": GEMINI_THINKING_LEVEL,
        "jpeg_quality": JPEG_QUALITY,
        "system_prompt": FOLD_CHECK_SYSTEM_PROMPT,
        "criteria_prefix": FOLD_CHECK_CRITERIA_PREFIX,
        "video": _file_fingerprint(plan.video_path),
        "reference": _file_fingerprint(step.reference_path),
        "code": _code_fingerprint(),
        "target_id": target_id,
        "criteria": step.criteria,
        "timestamp_s": _time_value(timestamp_s),
        "interval_end_s": _time_value(interval_end_s),
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _label_missing_requests(
    *,
    plan: LabelPlan,
    steps: dict[str, OrigamiStep],
    reference_images: dict[str, Image.Image],
    requests: list[SampleRequest],
    missing_requests: list[SampleRequest],
    results: dict[str, GeminiResult],
    cache_path: Path,
    concurrency: int,
) -> list[float]:
    missing_by_time: dict[str, list[SampleRequest]] = defaultdict(list)
    for request in missing_requests:
        missing_by_time[_time_key(request.timestamp_s)].append(request)

    completed = len(results)
    durations: list[float] = []
    pending: set[Future[LabeledSample]] = set()
    submitted = 0
    max_pending = concurrency * 2
    executor = ThreadPoolExecutor(max_workers=concurrency)

    def record_completed(done: set[Future[LabeledSample]]) -> Exception | None:
        nonlocal completed
        first_error: Exception | None = None
        for future in done:
            if future.cancelled():
                continue
            try:
                labeled = future.result()
            except Exception as error:
                if first_error is None:
                    first_error = error
                continue
            results[labeled.request.cache_key] = labeled.result
            _append_cache_result(
                cache_path,
                request=labeled.request,
                result=labeled.result,
                plan=plan,
            )
            completed += 1
            durations.append(labeled.elapsed_s)
            print(
                f"[{completed}/{len(requests)}] {labeled.request.target_id} "
                f"{_format_time(labeled.request.timestamp_s)}s -> "
                f"{str(labeled.result.value).lower()} "
                f"({_format_duration(labeled.elapsed_s)})",
                flush=True,
            )
        return first_error

    def drain_pending(*, cancel_queued: bool = False) -> None:
        nonlocal pending
        if cancel_queued:
            pending = {future for future in pending if not future.cancel()}
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            record_completed(done)

    try:
        for time_key, camera_image in _decode_sample_images(
            plan.video_path,
            [_time_value(request.timestamp_s) for request in missing_requests],
        ):
            for request in missing_by_time.get(time_key, []):
                while len(pending) >= max_pending:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    error = record_completed(done)
                    if error is not None:
                        raise error
                step = steps[request.target_id]
                pending.add(
                    executor.submit(
                        _label_sample,
                        request,
                        camera_image.copy(),
                        reference_images[request.target_id].copy(),
                        step.criteria,
                    )
                )
                submitted += 1

            done, pending = wait(pending, timeout=0, return_when=FIRST_COMPLETED)
            error = record_completed(done)
            if error is not None:
                raise error

        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            error = record_completed(done)
            if error is not None:
                raise error
    except Exception:
        drain_pending(cancel_queued=True)
        raise
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)

    if submitted != len(missing_requests):
        raise RuntimeError(
            f"decoded {submitted} of {len(missing_requests)} requested samples"
        )
    return durations


def _label_sample(
    request: SampleRequest,
    camera_image: Image.Image,
    reference_image: Image.Image,
    prompt: str,
) -> LabeledSample:
    start_s = time.monotonic()
    result = label_camera_image(
        genai.Client(),
        camera_image=camera_image,
        reference_image=reference_image,
        prompt=prompt,
        log_context=f"{request.target_id} at {_format_time(request.timestamp_s)}s",
    )
    return LabeledSample(
        request=request,
        result=result,
        elapsed_s=time.monotonic() - start_s,
    )


def label_camera_image(
    client: genai.Client,
    *,
    camera_image: Image.Image,
    reference_image: Image.Image,
    prompt: str,
    log_context: str,
) -> GeminiResult:
    composite = compose_fold_check_image(camera_image, reference_image)
    return call_gemini(
        client,
        image=composite,
        prompt=prompt,
        log_context=log_context,
    )


def call_gemini(
    client: genai.Client,
    *,
    image: Image.Image,
    prompt: str,
    log_context: str,
) -> GeminiResult:
    encoded_image = _jpeg_base64(image)
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            interaction = client.interactions.create(
                model=GEMINI_MODEL,
                system_instruction=FOLD_CHECK_SYSTEM_PROMPT,
                input=[
                    {"type": "text", "text": fold_check_criteria_text(prompt)},
                    {
                        "type": "image",
                        "data": encoded_image,
                        "mime_type": "image/jpeg",
                        "resolution": GEMINI_IMAGE_RESOLUTION,
                    },
                ],
                generation_config={"thinking_level": GEMINI_THINKING_LEVEL},
                service_tier=GEMINI_SERVICE_TIER,
                store=False,
            )
            response_text = str(getattr(interaction, "output_text", "") or "").strip()
            parsed = parse_fold_check_result({"ok": True, "result": response_text})
            if parsed is None:
                raise RuntimeError(
                    f"Gemini returned non-boolean text: {response_text!r}"
                )
            return GeminiResult(
                value=parsed,
                response_text=response_text,
                interaction_id=cast("str | None", getattr(interaction, "id", None)),
            )
        except Exception as error:
            last_error = error
            if attempt == 3:
                break
            delay_s = 5 * (2 ** (attempt - 1))
            print(
                f"Gemini call failed for {log_context}; retrying in {delay_s}s: "
                f"{error}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay_s)
    raise RuntimeError(f"Gemini call failed for {log_context}: {last_error}")


def _load_cached_results(
    cache_path: Path,
    expected_cache_keys: set[str],
) -> dict[str, GeminiResult]:
    if not cache_path.exists():
        return {}

    cached: dict[str, GeminiResult] = {}
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        cache_key = raw.get("cache_key")
        if not isinstance(cache_key, str) or cache_key not in expected_cache_keys:
            continue
        value = raw.get("value")
        if not isinstance(value, bool):
            continue
        response_text = raw.get("response_text")
        interaction_id = raw.get("interaction_id")
        cached[cache_key] = GeminiResult(
            value=value,
            response_text=response_text if isinstance(response_text, str) else "",
            interaction_id=interaction_id if isinstance(interaction_id, str) else None,
        )
    return cached


def _append_cache_result(
    cache_path: Path,
    *,
    request: SampleRequest,
    result: GeminiResult,
    plan: LabelPlan,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "cache_key": request.cache_key,
        "target_id": request.target_id,
        "timestamp_s": request.timestamp_s,
        "interval_end_s": request.interval_end_s,
        "next_grid_timestamp_s": request.next_grid_timestamp_s,
        "value": result.value,
        "response_text": result.response_text,
        "interaction_id": result.interaction_id,
        "model": GEMINI_MODEL,
        "service_tier": GEMINI_SERVICE_TIER,
        "image_resolution": GEMINI_IMAGE_RESOLUTION,
        "thinking_level": GEMINI_THINKING_LEVEL,
        "plan": str(plan.path),
        "video": str(plan.video_path),
    }
    with cache_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def _decode_sample_images(
    video_path: Path,
    timestamps_s: list[float],
) -> Iterator[tuple[str, Image.Image]]:
    if not timestamps_s:
        return

    requested = sorted({_time_value(timestamp_s) for timestamp_s in timestamps_s})
    try:
        with av.open(str(video_path)) as container:
            stream = _video_stream(container)
            frame_rate = _average_rate(stream)
            pending_index = 0
            frame_index = -1
            first_timestamp_s: float | None = None
            previous: tuple[VideoFrame, float, int] | None = None

            for frame in container.decode(stream):
                frame_index += 1
                raw_timestamp_s = _frame_timestamp_s(frame, frame_index, frame_rate)
                if first_timestamp_s is None:
                    first_timestamp_s = raw_timestamp_s
                timestamp_s = max(0.0, raw_timestamp_s - first_timestamp_s)
                current = (frame, timestamp_s, frame_index)
                while (
                    pending_index < len(requested)
                    and requested[pending_index] <= timestamp_s
                ):
                    requested_time_s = requested[pending_index]
                    chosen = _nearest_frame(previous, current, requested_time_s)
                    yield (
                        _time_key(requested_time_s),
                        chosen[0].to_image().convert("RGB"),
                    )
                    pending_index += 1
                previous = current

            if previous is None:
                raise RuntimeError(f"video contains no frames: {video_path}")
            while pending_index < len(requested):
                requested_time_s = requested[pending_index]
                yield (
                    _time_key(requested_time_s),
                    previous[0].to_image().convert("RGB"),
                )
                pending_index += 1
    except FFmpegError as error:
        raise RuntimeError(f"could not decode video {video_path}: {error}") from error


def _write_case_yaml(
    path: Path,
    *,
    plan: LabelPlan,
    requests_by_target: dict[str, list[SampleRequest]],
    results: dict[str, GeminiResult],
    existing_case: ExistingCase | None,
) -> None:
    generated_case: dict[str, Any] = {
        "video": _relative_video_path(plan.video_path, path.parent),
    }
    if plan.description is not None:
        generated_case["description"] = plan.description
    generated_case["sampling"] = {"every_s": _time_value(plan.every_s)}
    raw_targets: dict[str, Any] = {}
    for target in plan.targets:
        raw_target: dict[str, Any] = {}
        if target.label is not None:
            raw_target["label"] = target.label
        raw_target["samples"] = _sample_blocks(
            requests_by_target[target.id],
            results=results,
        )
        raw_targets[target.id] = raw_target
    generated_case["targets"] = raw_targets

    if existing_case is None:
        raw_case = generated_case
    else:
        current_text = path.read_text(encoding="utf-8")
        if current_text != existing_case.source_text:
            raise RuntimeError(
                f"output changed during generation; refusing to overwrite: {path}"
            )
        existing_targets = cast("dict[str, Any]", existing_case.raw["targets"])
        merged_targets = dict(existing_targets)
        merged_targets.update(raw_targets)
        raw_case = dict(existing_case.raw)
        raw_case["targets"] = merged_targets

    _use_flow_style_for_sample_ranges(raw_case)
    rendered = yaml.dump(
        raw_case,
        Dumper=_CaseYamlDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    _write_text_atomically(path, rendered)


def _use_flow_style_for_sample_ranges(raw_case: dict[str, Any]) -> None:
    targets = raw_case.get("targets")
    if not isinstance(targets, dict):
        return
    for raw_target in targets.values():
        if not isinstance(raw_target, dict):
            continue
        samples = raw_target.get("samples")
        if not isinstance(samples, list):
            continue
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            sample_range = sample.get("range")
            if isinstance(sample_range, list):
                sample["range"] = _FlowList(cast("list[float]", sample_range))


def _load_existing_case_for_target_update(
    path: Path,
    *,
    plan: LabelPlan,
) -> ExistingCase:
    source_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(source_text)
    if not isinstance(raw, dict):
        raise RuntimeError("existing output YAML must be an object")

    video_raw = _required_string(raw, "video")
    existing_video_path = _resolve_plan_path(path.parent, video_raw)
    if existing_video_path != plan.video_path.resolve():
        raise RuntimeError(
            "cannot update selected targets because the existing output uses a "
            f"different video: {existing_video_path}"
        )

    sampling = raw.get("sampling")
    if not isinstance(sampling, dict):
        raise RuntimeError(
            "cannot update selected targets because the existing output has no "
            "sampling object"
        )
    existing_every_s = _positive_number(
        sampling.get("every_s"),
        "existing output sampling.every_s",
    )
    if not math.isclose(existing_every_s, plan.every_s, abs_tol=TIME_EPSILON):
        raise RuntimeError(
            "cannot update selected targets because the existing output uses "
            f"sampling.every_s={existing_every_s:g}, not {plan.every_s:g}"
        )

    targets = raw.get("targets")
    if not isinstance(targets, dict):
        raise RuntimeError("existing output targets must be an object")
    return ExistingCase(raw=cast("dict[str, Any]", raw), source_text=source_text)


def _write_text_atomically(path: Path, content: str) -> None:
    output_mode = path.stat().st_mode & 0o777 if path.exists() else None
    temporary_path: Path | None = None
    try:
        while temporary_path is None:
            candidate = path.parent / (f".{path.name}.{secrets.token_hex(8)}.tmp")
            try:
                file_descriptor = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o666,
                )
            except FileExistsError:
                continue
            temporary_path = candidate

        with os.fdopen(file_descriptor, mode="w", encoding="utf-8") as file:
            file.write(content)
        if output_mode is not None:
            temporary_path.chmod(output_mode)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _sample_blocks(
    requests: list[SampleRequest],
    *,
    results: dict[str, GeminiResult],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    previous_request: SampleRequest | None = None
    for request in requests:
        result = results[request.cache_key]
        if (
            previous_request is not None
            and blocks
            and blocks[-1]["expect"] == result.value
            and math.isclose(
                previous_request.next_grid_timestamp_s,
                request.timestamp_s,
                abs_tol=1e-6,
            )
            and math.isclose(
                previous_request.interval_end_s,
                request.timestamp_s,
                abs_tol=1e-6,
            )
        ):
            block = blocks[-1]
            if "at" in block:
                payload = {key: value for key, value in block.items() if key != "at"}
                blocks[-1] = {
                    "range": _FlowList(
                        [cast(float, block["at"]), request.interval_end_s]
                    ),
                    **payload,
                }
            else:
                cast("list[float]", block["range"])[1] = request.interval_end_s
            previous_request = request
            continue
        blocks.append(
            {
                "at": _time_value(request.timestamp_s),
                "expect": result.value,
            }
        )
        previous_request = request
    return blocks


def _video_stream(container: av.container.InputContainer) -> Any:
    stream = next(
        (candidate for candidate in container.streams if candidate.type == "video"),
        None,
    )
    if stream is None:
        raise RuntimeError("video file has no video stream")
    return stream


def _average_rate(stream: Any) -> float:
    if stream.average_rate:
        return float(stream.average_rate)
    return 30.0


def _frame_timestamp_s(frame: VideoFrame, frame_index: int, frame_rate: float) -> float:
    frame_time = cast(float | None, frame.time)
    if frame_time is not None:
        return frame_time
    pts = frame.pts
    time_base = frame.time_base
    if pts is not None and time_base is not None:
        return float(pts * time_base)
    return frame_index / frame_rate


def _nearest_frame(
    previous: tuple[VideoFrame, float, int] | None,
    current: tuple[VideoFrame, float, int],
    timestamp_s: float,
) -> tuple[VideoFrame, float, int]:
    if previous is None:
        return current
    previous_distance = abs(previous[1] - timestamp_s)
    current_distance = abs(current[1] - timestamp_s)
    return previous if previous_distance <= current_distance else current


def _jpeg_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer,
        format="JPEG",
        quality=max(1, min(100, JPEG_QUALITY)),
        optimize=True,
    )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _default_cache_path(output_path: Path) -> Path:
    if output_path.parent.name == "cases":
        base_dir = output_path.parent.parent / "runs" / "generate-case"
    else:
        base_dir = output_path.parent / "runs" / "generate-case"
    return base_dir / f"{output_path.stem}.partial.jsonl"


def _file_fingerprint(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _code_fingerprint() -> list[dict[str, Any]]:
    paths = [
        Path(__file__).resolve(),
        BACKEND_DIR / "src" / "fold_check.py",
        BACKEND_DIR / "src" / "fold_check_prompts.py",
        BACKEND_DIR / "src" / "rendering.py",
    ]
    return [_file_fingerprint(path) for path in paths]


def _relative_video_path(video_path: Path, output_dir: Path) -> str:
    return os.path.relpath(video_path.resolve(), output_dir.resolve()).replace(
        os.sep,
        "/",
    )


def _resolve_cli_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _resolve_plan_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _required_string(raw: dict[Any, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} must be a non-empty string")
    return value.strip()


def _positive_number(value: Any, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise RuntimeError(f"{label} must be greater than 0")
    return number


def _nonnegative_number(value: Any, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise RuntimeError(f"{label} must be greater than or equal to 0")
    return number


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RuntimeError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"{label} must be finite")
    return number


def _time_value(value: float) -> float:
    rounded = round(value, 6)
    return 0.0 if abs(rounded) < TIME_EPSILON else rounded


def _time_key(value: float) -> str:
    return f"{_time_value(value):.6f}"


def _format_time(value: float) -> str:
    return f"{_time_value(value):g}"


def _format_completion_summary(
    *,
    total_samples: int,
    cached_samples: int,
    gemini_durations: list[float],
    gemini_wall_s: float,
    total_elapsed_s: float,
) -> str:
    if not gemini_durations:
        return (
            f"finished {total_samples} samples in "
            f"{_format_duration(total_elapsed_s)}; all samples cached"
        )

    avg_call_s = sum(gemini_durations) / len(gemini_durations)
    wall_avg_s = gemini_wall_s / len(gemini_durations)
    return (
        f"finished {total_samples} samples in {_format_duration(total_elapsed_s)}; "
        f"{cached_samples} cached, {len(gemini_durations)} Gemini calls, "
        f"avg {_format_duration(avg_call_s)}/call "
        f"(wall {_format_duration(wall_avg_s)}/call)"
    )


def _format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes}m{remaining:04.1f}s"


if __name__ == "__main__":
    raise SystemExit(main())
