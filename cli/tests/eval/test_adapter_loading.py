from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from PIL import Image

from glasskit.eval.adapters import load_evaluator
from glasskit.eval.models import (
    AdapterConfig,
    AdapterLoadError,
    FrameSample,
    TargetContext,
)


def test_loads_simple_file_function_adapter(tmp_path: Path) -> None:
    asyncio.run(_run_file_function_adapter_test(tmp_path))


async def _run_file_function_adapter_test(tmp_path: Path) -> None:
    adapter_path = tmp_path / "eval_adapter.py"
    adapter_path.write_text(
        """
def evaluate_frame(image, target_id):
    return target_id == "step_1"
        """,
        encoding="utf-8",
    )

    evaluator = await load_evaluator(
        f"{adapter_path}:evaluate_frame",
        AdapterConfig(eval_dir=tmp_path),
    )

    assert evaluator.supports_individual_evaluation
    assert not evaluator.supports_batch_evaluation
    result = await evaluator.evaluate(_sample(), TargetContext(id="step_1", index=0))
    assert result is True


def test_loads_import_path_factory_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_run_import_path_factory_adapter_test(tmp_path, monkeypatch))


def test_file_adapter_can_import_app_root_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_run_app_root_import_test(tmp_path, monkeypatch))


def test_file_adapter_path_may_contain_colons(tmp_path: Path) -> None:
    asyncio.run(_run_colon_path_adapter_test(tmp_path))


def test_detects_native_batch_evaluator(tmp_path: Path) -> None:
    asyncio.run(_run_native_batch_evaluator_test(tmp_path))


def test_keyword_only_factory_receives_config(tmp_path: Path) -> None:
    asyncio.run(_run_keyword_only_factory_test(tmp_path))


def test_factory_with_extra_keyword_only_arguments_error_names_them(
    tmp_path: Path,
) -> None:
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text(
        "def create_evaluator(*, config, api_key): pass\n",
        encoding="utf-8",
    )

    with pytest.raises(AdapterLoadError) as exc_info:
        asyncio.run(
            load_evaluator(
                f"{adapter_path}:create_evaluator",
                AdapterConfig(eval_dir=tmp_path),
            )
        )

    message = str(exc_info.value)
    assert "must accept the factory config as its only required argument" in message
    assert "config, api_key" in message


def test_missing_adapter_callable_error_distinguishes_it_from_eval_targets(
    tmp_path: Path,
) -> None:
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text("def existing(): pass\n", encoding="utf-8")

    with pytest.raises(
        AdapterLoadError,
        match=r"adapter callable 'missing' was not found in .*adapter\.py",
    ):
        asyncio.run(
            load_evaluator(
                f"{adapter_path}:missing",
                AdapterConfig(eval_dir=tmp_path),
            )
        )


def test_invalid_factory_result_error_lists_supported_shapes(tmp_path: Path) -> None:
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text(
        "def create_evaluator(): return object()\n",
        encoding="utf-8",
    )

    with pytest.raises(AdapterLoadError) as exc_info:
        asyncio.run(
            load_evaluator(
                f"{adapter_path}:create_evaluator",
                AdapterConfig(eval_dir=tmp_path),
            )
        )

    message = str(exc_info.value)
    assert "evaluate(...) or evaluate_many(...)" in message
    assert "(image, target_id) or (sample, target)" in message


def test_non_callable_adapter_attribute_error_identifies_the_attribute(
    tmp_path: Path,
) -> None:
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text("evaluator = None\n", encoding="utf-8")

    with pytest.raises(AdapterLoadError) as exc_info:
        asyncio.run(
            load_evaluator(
                f"{adapter_path}:evaluator",
                AdapterConfig(eval_dir=tmp_path),
            )
        )

    message = str(exc_info.value)
    assert "adapter attribute 'evaluator'" in message
    assert "is not callable" in message


async def _run_import_path_factory_adapter_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_dir = tmp_path / "modules"
    module_dir.mkdir()
    (module_dir / "my_adapter.py").write_text(
        """
class Evaluator:
    async def evaluate(self, sample, target):
        return {"target": target.id, "time": sample.timestamp_s}

    async def close(self):
        return None

def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(module_dir))

    evaluator = await load_evaluator(
        "my_adapter:create_evaluator",
        AdapterConfig(eval_dir=tmp_path),
    )

    assert evaluator.supports_individual_evaluation
    assert not evaluator.supports_batch_evaluation
    result = await evaluator.evaluate(_sample(), TargetContext(id="step_2", index=1))
    assert result == {"target": "step_2", "time": 0.0}


async def _run_app_root_import_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    (tmp_path / "app_logic.py").write_text(
        """
def check_target(target_id):
    return target_id == "step_1"
        """,
        encoding="utf-8",
    )
    adapter_path = eval_dir / "adapter.py"
    adapter_path.write_text(
        """
from app_logic import check_target


class Evaluator:
    async def evaluate(self, sample, target):
        return check_target(target.id)


def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", _without_import_paths(sys.path, tmp_path))

    evaluator = await load_evaluator(
        "eval/adapter.py:create_evaluator",
        AdapterConfig(eval_dir=eval_dir),
    )

    result = await evaluator.evaluate(_sample(), TargetContext(id="step_1", index=0))
    assert result is True


async def _run_colon_path_adapter_test(tmp_path: Path) -> None:
    eval_dir = tmp_path / "repo:with-colon" / "eval"
    eval_dir.mkdir(parents=True)
    adapter_path = eval_dir / "adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate(self, sample, target):
        return target.id


def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )

    evaluator = await load_evaluator(
        f"{adapter_path}:create_evaluator",
        AdapterConfig(eval_dir=eval_dir),
    )

    result = await evaluator.evaluate(_sample(), TargetContext(id="step_1", index=0))
    assert result == "step_1"


async def _run_keyword_only_factory_test(tmp_path: Path) -> None:
    adapter_path = tmp_path / "kw_only_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    def __init__(self, config):
        self._config = config

    async def evaluate(self, sample, target):
        return self._config.verbose


def create_evaluator(*, config):
    return Evaluator(config)
        """,
        encoding="utf-8",
    )

    evaluator = await load_evaluator(
        f"{adapter_path}:create_evaluator",
        AdapterConfig(eval_dir=tmp_path, verbose=True),
    )

    result = await evaluator.evaluate(_sample(), TargetContext(id="step_1", index=0))
    assert result is True


async def _run_native_batch_evaluator_test(tmp_path: Path) -> None:
    adapter_path = tmp_path / "batch_adapter.py"
    adapter_path.write_text(
        """
class Evaluator:
    async def evaluate_many(self, samples, target):
        return [sample.timestamp_s for sample in samples]


def create_evaluator(config):
    return Evaluator()
        """,
        encoding="utf-8",
    )
    evaluator = await load_evaluator(
        f"{adapter_path}:create_evaluator",
        AdapterConfig(eval_dir=tmp_path),
    )
    sample = _sample()
    target = TargetContext(id="step_1", index=0)

    assert not evaluator.supports_individual_evaluation
    assert evaluator.supports_batch_evaluation
    assert await evaluator.evaluate_many([sample, sample], target) == [0.0, 0.0]


def _without_import_paths(paths: list[str], root: Path) -> list[str]:
    blocked = {root.resolve(), (root / "eval").resolve()}
    filtered: list[str] = []
    for entry in paths:
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            filtered.append(entry)
            continue
        if resolved not in blocked:
            filtered.append(entry)
    return filtered


def _sample() -> FrameSample:
    return FrameSample(
        image=Image.new("RGB", (4, 4), "white"),
        timestamp_s=0.0,
        frame_index=0,
        sample_index=0,
        video_path="video.mp4",
        case_name="case",
    )
