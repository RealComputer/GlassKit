from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text
from typer.core import TyperGroup, TyperOption
from typer.main import get_command
from typer.testing import CliRunner

from glasskit.cli import _default_adapter_target, app


def test_eval_help_lists_current_commands() -> None:
    result = CliRunner().invoke(app, ["eval", "--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "validate" in result.output
    assert "list-samples" in result.output
    assert "init-case" not in result.output


def test_eval_commands_define_target_filter() -> None:
    root_command = get_command(app)
    assert isinstance(root_command, TyperGroup)
    eval_command = root_command.commands["eval"]
    assert isinstance(eval_command, TyperGroup)

    for command in ("run", "validate", "list-samples"):
        command_options = eval_command.commands[command].params

        assert any(
            isinstance(option, TyperOption) and "--target" in option.opts
            for option in command_options
        )


def test_eval_run_defines_serial_concurrency_default() -> None:
    root_command = get_command(app)
    assert isinstance(root_command, TyperGroup)
    eval_command = root_command.commands["eval"]
    assert isinstance(eval_command, TyperGroup)

    concurrency = next(
        option
        for option in eval_command.commands["run"].params
        if isinstance(option, TyperOption) and "--concurrency" in option.opts
    )

    assert concurrency.default == 1
    assert concurrency.help is not None
    assert "ignored when the adapter uses evaluate_many" in concurrency.help


def test_eval_run_and_list_samples_define_time_window_filters() -> None:
    root_command = get_command(app)
    assert isinstance(root_command, TyperGroup)
    eval_command = root_command.commands["eval"]
    assert isinstance(eval_command, TyperGroup)

    for command in ("run", "list-samples"):
        options = eval_command.commands[command].params
        option_names = {
            option_name
            for option in options
            if isinstance(option, TyperOption)
            for option_name in option.opts
        }

        assert {"--from", "--until"} <= option_names


def test_eval_run_rejects_non_positive_concurrency() -> None:
    result = CliRunner().invoke(app, ["eval", "run", "--concurrency", "0"])

    assert result.exit_code == 2
    assert "Invalid value for '--concurrency'" in Text.from_ansi(result.output).plain


@pytest.mark.parametrize("command", ["run", "list-samples"])
def test_eval_time_window_filters_require_case(command: str) -> None:
    result = CliRunner().invoke(app, ["eval", command, "--from", "1.0"])

    assert result.exit_code == 2
    assert "--from and --until require --case" in Text.from_ansi(result.output).plain


def test_eval_time_window_rejects_reversed_bounds() -> None:
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "run",
            "--case",
            "case-001",
            "--from",
            "2.0",
            "--until",
            "1.0",
        ],
    )

    assert result.exit_code == 2
    assert "must be greater than --from" in Text.from_ansi(result.output).plain


@pytest.mark.parametrize(("option", "value"), [("--from", "nan"), ("--until", "inf")])
def test_eval_time_window_rejects_nonfinite_bounds(option: str, value: str) -> None:
    result = CliRunner().invoke(
        app,
        ["eval", "run", "--case", "case-001", option, value],
    )

    assert result.exit_code == 2
    assert "must be a finite, nonnegative number" in Text.from_ansi(result.output).plain


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
