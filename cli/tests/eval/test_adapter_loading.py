from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from glasskit.eval.adapters import load_evaluator
from glasskit.eval.models import AdapterConfig, FrameSample, TargetContext


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

    result = await evaluator.evaluate(_sample(), TargetContext(id="step_1", index=0))
    assert result is True


def test_loads_import_path_factory_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asyncio.run(_run_import_path_factory_adapter_test(tmp_path, monkeypatch))


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

    result = await evaluator.evaluate(_sample(), TargetContext(id="step_2", index=1))
    assert result == {"target": "step_2", "time": 0.0}


def _sample() -> FrameSample:
    return FrameSample(
        image=Image.new("RGB", (4, 4), "white"),
        timestamp_s=0.0,
        frame_index=0,
        sample_index=0,
        video_path="video.mp4",
        case_name="case",
    )
