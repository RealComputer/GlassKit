from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.text import Text
from typer.core import TyperGroup, TyperOption
from typer.main import get_command
from typer.testing import CliRunner

from glasskit.cli import _default_adapter_target, app
from glasskit.eval.models import RunOptions


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
        target_option = next(
            option
            for option in command_options
            if isinstance(option, TyperOption) and "--target" in option.opts
        )

        assert target_option.multiple


def test_eval_list_samples_accepts_multiple_target_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_load_eval_directory(eval_dir: Path, **kwargs: object) -> object:
        captured["eval_dir"] = eval_dir
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("glasskit.cli.load_eval_directory", fake_load_eval_directory)
    monkeypatch.setattr("glasskit.cli.print_sample_schedule", lambda loaded: None)

    result = CliRunner().invoke(
        app,
        [
            "eval",
            "list-samples",
            "--target",
            "step_1",
            "--target",
            "step_2",
        ],
    )

    assert result.exit_code == 0
    assert captured["target_filter"] == ("step_1", "step_2")


@pytest.mark.parametrize(
    ("command", "expected_exit_code"),
    [("run", 2), ("validate", 1), ("list-samples", 2)],
)
def test_eval_target_errors_render_rich_markup_as_literal_text(
    tmp_path: Path, command: str, expected_exit_code: int
) -> None:
    eval_dir = tmp_path / "eval"
    cases_dir = eval_dir / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case.yaml").write_text(
        """
video: video.mp4
targets:
  "[/]":
    samples:
      - at: 0.0
        expect: true
        """,
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "eval",
            command,
            "--eval-dir",
            str(eval_dir),
            "--target",
            "missing",
        ],
    )

    assert result.exit_code == expected_exit_code
    output = " ".join(Text.from_ansi(result.output).plain.split())
    assert "requested eval target not found" in output
    assert "available targets: '[/]'" in output


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


def test_eval_run_and_validate_define_adapter_command() -> None:
    root_command = get_command(app)
    assert isinstance(root_command, TyperGroup)
    eval_command = root_command.commands["eval"]
    assert isinstance(eval_command, TyperGroup)

    for command in ("run", "validate"):
        option_names = {
            option_name
            for option in eval_command.commands[command].params
            if isinstance(option, TyperOption)
            for option_name in option.opts
        }
        assert "--adapter-command" in option_names


def test_eval_run_passes_adapter_command_without_python_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_eval(options: object, callbacks: object) -> object:
        captured["options"] = options
        return SimpleNamespace(success=True)

    monkeypatch.setattr("glasskit.cli.run_eval", fake_run_eval)
    monkeypatch.setattr("glasskit.cli.print_run_summary", lambda *args, **kwargs: None)

    result = CliRunner().invoke(
        app,
        ["eval", "run", "--adapter-command", "node eval/adapter.js"],
    )

    assert result.exit_code == 0
    options = captured["options"]
    assert isinstance(options, RunOptions)
    assert options.adapter is None
    assert options.adapter_command == "node eval/adapter.js"


@pytest.mark.parametrize("command", ["run", "validate"])
def test_eval_commands_reject_python_and_process_adapters_together(
    command: str,
) -> None:
    result = CliRunner().invoke(
        app,
        [
            "eval",
            command,
            "--adapter",
            "eval/adapter.py:create_evaluator",
            "--adapter-command",
            "node eval/adapter.js",
        ],
    )

    assert result.exit_code == 2
    output = Text.from_ansi(result.output).plain
    assert "--adapter-command" in output
    assert "cannot be used with --adapter" in output


def test_eval_run_defines_single_trial_default_and_stability_gate() -> None:
    root_command = get_command(app)
    assert isinstance(root_command, TyperGroup)
    eval_command = root_command.commands["eval"]
    assert isinstance(eval_command, TyperGroup)
    options = eval_command.commands["run"].params

    repeat = next(
        option
        for option in options
        if isinstance(option, TyperOption) and "--repeat" in option.opts
    )
    max_flaky = next(
        option
        for option in options
        if isinstance(option, TyperOption) and "--max-flaky-samples" in option.opts
    )

    assert repeat.default == 1
    assert repeat.help is not None
    assert "sequential trials" in repeat.help
    assert max_flaky.default is None
    assert max_flaky.help is not None
    assert "varies across trials" in max_flaky.help


def test_eval_run_does_not_define_failure_table_limit() -> None:
    root_command = get_command(app)
    assert isinstance(root_command, TyperGroup)
    eval_command = root_command.commands["eval"]
    assert isinstance(eval_command, TyperGroup)

    option_names = {
        option_name
        for option in eval_command.commands["run"].params
        if isinstance(option, TyperOption)
        for option_name in option.opts
    }

    assert "--max-failures-to-print" not in option_names


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


def test_eval_run_rejects_non_positive_repeat() -> None:
    result = CliRunner().invoke(app, ["eval", "run", "--repeat", "0"])

    assert result.exit_code == 2
    assert "Invalid value for '--repeat'" in Text.from_ansi(result.output).plain


def test_eval_run_requires_repetition_for_flaky_sample_gate() -> None:
    result = CliRunner().invoke(
        app,
        ["eval", "run", "--max-flaky-samples", "0"],
    )

    assert result.exit_code == 2
    assert (
        "--max-flaky-samples requires --repeat to be at least 2"
        in Text.from_ansi(result.output).plain
    )


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
