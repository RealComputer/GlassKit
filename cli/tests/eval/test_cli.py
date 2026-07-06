from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from glasskit.cli import _default_adapter_target, app


def test_eval_help_lists_current_commands() -> None:
    result = CliRunner().invoke(app, ["eval", "--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "validate" in result.output
    assert "list-samples" in result.output
    assert "init-case" not in result.output


def test_default_adapter_target_follows_eval_dir() -> None:
    assert (
        _default_adapter_target(Path("custom-eval"))
        == "custom-eval/adapter.py:create_evaluator"
    )


def test_default_adapter_target_preserves_colons_in_eval_dir() -> None:
    assert (
        _default_adapter_target(Path("repo:with-colon/eval"))
        == "repo:with-colon/eval/adapter.py:create_evaluator"
    )
