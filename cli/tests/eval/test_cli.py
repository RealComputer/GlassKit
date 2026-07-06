from __future__ import annotations

from pathlib import Path

from glasskit.cli import _default_adapter_target


def test_default_adapter_target_follows_eval_dir() -> None:
    assert (
        _default_adapter_target(Path("custom-eval"))
        == "custom-eval/adapter.py:create_evaluator"
    )
