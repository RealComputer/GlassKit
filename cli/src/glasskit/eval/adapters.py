from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

from .models import (
    AdapterConfig,
    AdapterLoadError,
    AdapterRuntimeError,
    FrameSample,
    TargetContext,
)


async def load_evaluator(adapter_target: str, config: AdapterConfig) -> LoadedEvaluator:
    target = _load_target(adapter_target, import_roots=_adapter_import_roots(config))
    if _looks_like_frame_function(target):
        return _function_evaluator(target)

    try:
        result = target(config) if _callable_accepts_config(target) else target()
        evaluator = await _maybe_await(result)
    except Exception as error:
        raise AdapterLoadError(
            f"adapter factory {adapter_target!r} failed: {error}"
        ) from error

    if _has_evaluation_method(evaluator):
        return _object_evaluator(evaluator)
    if callable(evaluator) and _looks_like_frame_function(evaluator):
        return _function_evaluator(evaluator)
    raise AdapterLoadError(
        f"adapter {adapter_target!r} did not return an object with "
        "evaluate(...) or evaluate_many(...)"
    )


class LoadedEvaluator:
    def __init__(
        self,
        *,
        evaluate: Callable[[FrameSample, TargetContext], Any] | None,
        evaluate_many: Callable[[list[FrameSample], TargetContext], Any] | None,
        close: Callable[[], Any] | None,
    ) -> None:
        self._evaluate = evaluate
        self._evaluate_many = evaluate_many
        self._close = close

    @property
    def supports_batch_evaluation(self) -> bool:
        return self._evaluate_many is not None

    @property
    def supports_individual_evaluation(self) -> bool:
        return self._evaluate is not None

    async def evaluate(self, sample: FrameSample, target: TargetContext) -> Any:
        if self._evaluate is None:
            raise AdapterRuntimeError("adapter does not implement evaluate(...)")
        return await _invoke_adapter_callable(self._evaluate, sample, target)

    async def evaluate_many(
        self, samples: list[FrameSample], target: TargetContext
    ) -> Any:
        if self._evaluate_many is None:
            raise AdapterRuntimeError("adapter does not implement evaluate_many(...)")
        return await _invoke_adapter_callable(self._evaluate_many, samples, target)

    async def close(self) -> None:
        if self._close is not None:
            await _invoke_adapter_callable(self._close)


def _adapter_import_roots(config: AdapterConfig) -> list[Path]:
    return [
        Path.cwd().resolve(),
        config.eval_dir.expanduser().resolve().parent,
    ]


def _load_target(
    adapter_target: str, *, import_roots: Iterable[Path] = ()
) -> Callable[..., Any]:
    if ":" not in adapter_target:
        raise AdapterLoadError(
            f"adapter must be '<module-or-file>:<callable>', got {adapter_target!r}"
        )
    module_ref, object_ref = adapter_target.rsplit(":", 1)
    module_ref = module_ref.strip()
    object_ref = object_ref.strip()
    if not module_ref or not object_ref:
        raise AdapterLoadError(
            f"adapter must be '<module-or-file>:<callable>', got {adapter_target!r}"
        )

    module = _load_module(module_ref, import_roots=import_roots)
    value: Any = module
    for part in object_ref.split("."):
        if not hasattr(value, part):
            raise AdapterLoadError(f"adapter target not found: {adapter_target}")
        value = getattr(value, part)
    if not callable(value):
        raise AdapterLoadError(f"adapter target is not callable: {adapter_target}")
    return value


def _load_module(module_ref: str, *, import_roots: Iterable[Path] = ()) -> ModuleType:
    path = Path(module_ref)
    if module_ref.endswith(".py") or path.exists():
        path = path.expanduser().resolve()
        if not path.exists():
            raise AdapterLoadError(f"adapter file does not exist: {path}")
        module_name = f"gk_eval_adapter_{abs(hash(path))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise AdapterLoadError(f"could not load adapter file: {path}")
        _prepend_import_roots([path.parent, *import_roots])
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as error:
            raise AdapterLoadError(
                f"adapter import failed for {path}: {error}"
            ) from error
        return module

    try:
        return importlib.import_module(module_ref)
    except Exception as error:
        raise AdapterLoadError(
            f"adapter import failed for module {module_ref!r}: {error}"
        ) from error


def _prepend_import_roots(roots: Iterable[Path]) -> None:
    unique_roots: list[Path] = []
    for root in roots:
        resolved = root.expanduser().resolve()
        if resolved.is_dir() and resolved not in unique_roots:
            unique_roots.append(resolved)
    for root in reversed(unique_roots):
        path = str(root)
        if path not in sys.path:
            sys.path.insert(0, path)


def _looks_like_frame_function(value: Any) -> bool:
    if not callable(value):
        return False
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return False
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    ]
    if len(positional) < 2:
        return False
    first = positional[0].name
    second = positional[1].name
    return (first, second) in {
        ("image", "target_id"),
        ("sample", "target"),
    }


def _callable_accepts_config(value: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return True
    required = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    ]
    return bool(required)


def _has_evaluation_method(value: Any) -> bool:
    return callable(getattr(value, "evaluate", None)) or callable(
        getattr(value, "evaluate_many", None)
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _function_evaluator(function: Callable[..., Any]) -> LoadedEvaluator:
    signature = inspect.signature(function)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    ]
    image_target_style = (positional[0].name, positional[1].name) == (
        "image",
        "target_id",
    )

    async def evaluate(sample: FrameSample, target: TargetContext) -> Any:
        if image_target_style:
            return await _invoke_adapter_callable(function, sample.image, target.id)
        return await _invoke_adapter_callable(function, sample, target)

    return LoadedEvaluator(evaluate=evaluate, evaluate_many=None, close=None)


def _object_evaluator(evaluator: Any) -> LoadedEvaluator:
    return LoadedEvaluator(
        evaluate=_optional_callable(evaluator, "evaluate"),
        evaluate_many=_optional_callable(evaluator, "evaluate_many"),
        close=_optional_callable(evaluator, "close"),
    )


def _optional_callable(value: Any, name: str) -> Callable[..., Any] | None:
    candidate = getattr(value, name, None)
    return candidate if callable(candidate) else None


async def _invoke_adapter_callable(function: Callable[..., Any], *args: Any) -> Any:
    if _is_async_callable(function):
        return await function(*args)
    thread_call = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        result = await asyncio.shield(thread_call)
    except asyncio.CancelledError as cancellation:
        await _drain_thread_call(thread_call)
        try:
            thread_call.result()
        except BaseException as error:
            cancellation.add_note(
                f"synchronous adapter call failed while draining cancellation: {error}"
            )
        raise
    return await _maybe_await(result)


async def _drain_thread_call(thread_call: asyncio.Task[Any]) -> None:
    while not thread_call.done():
        try:
            await asyncio.shield(thread_call)
        except asyncio.CancelledError:
            continue
        except BaseException:
            return


def _is_async_callable(function: Callable[..., Any]) -> bool:
    return inspect.iscoroutinefunction(function) or inspect.iscoroutinefunction(
        type(function).__call__
    )
