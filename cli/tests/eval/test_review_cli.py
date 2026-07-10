from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

import glasskit.cli as cli_module
from glasskit.cli import app

FIXTURES = Path(__file__).parents[1] / "fixtures"


class FakeServer:
    url = "http://127.0.0.1:43210/"

    def __init__(self) -> None:
        self.served = False
        self.closed = False

    def serve_forever(self) -> None:
        self.served = True

    def shutdown(self) -> None:
        return

    def server_close(self) -> None:
        self.closed = True


def test_review_help_lists_context_and_lifecycle_options() -> None:
    result = CliRunner().invoke(app, ["eval", "review", "--help"])

    assert result.exit_code == 0
    for option in ("--eval-dir", "--case", "--target", "--time", "--port", "--no-open"):
        assert option in result.output
    assert "Initially open this case" in result.output


def test_review_rejects_dependent_and_non_finite_options() -> None:
    runner = CliRunner()

    target = runner.invoke(app, ["eval", "review", "--target", "state"])
    time = runner.invoke(app, ["eval", "review", "--time", "1"])
    nan = runner.invoke(app, ["eval", "review", "--case", "assembly", "--time", "nan"])

    assert target.exit_code == 2
    assert "--target requires --case" in target.output
    assert time.exit_code == 2
    assert "--time requires --case" in time.output
    assert nan.exit_code == 2
    assert "finite, nonnegative" in nan.output


def test_review_resolves_initial_context_and_no_open(
    tmp_path: Path, monkeypatch
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    fake = FakeServer()
    opened: list[str] = []
    monkeypatch.setattr(
        cli_module, "create_review_server", lambda *args, **kwargs: fake
    )
    monkeypatch.setattr(cli_module.webbrowser, "open", opened.append)

    result = CliRunner().invoke(
        app,
        [
            "eval",
            "review",
            "--eval-dir",
            str(eval_dir),
            "--case",
            "assembly",
            "--target",
            "bracket_seated",
            "--time",
            "1.25",
            "--no-open",
        ],
    )

    assert result.exit_code == 0
    assert (
        "http://127.0.0.1:43210/?case=assembly.yaml&target=bracket_seated&time=1.25"
    ) in result.output
    assert fake.served
    assert fake.closed
    assert opened == []


def test_browser_open_failure_is_nonfatal(tmp_path: Path, monkeypatch) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    fake = FakeServer()
    monkeypatch.setattr(
        cli_module, "create_review_server", lambda *args, **kwargs: fake
    )
    monkeypatch.setattr(cli_module.webbrowser, "open", lambda _url: False)

    result = CliRunner().invoke(
        app,
        ["eval", "review", "--eval-dir", str(eval_dir), "--case", "inspection.yml"],
    )

    assert result.exit_code == 0
    assert "Could not open browser automatically" in result.output
    assert fake.served
    assert fake.closed


def test_invalid_initial_selectors_fail_before_server_creation(
    tmp_path: Path, monkeypatch
) -> None:
    eval_dir = _copy_fixtures(tmp_path)
    created = False

    def fail_if_created(*args, **kwargs):
        nonlocal created
        created = True
        raise AssertionError("server must not be created")

    monkeypatch.setattr(cli_module, "create_review_server", fail_if_created)

    result = CliRunner().invoke(
        app,
        [
            "eval",
            "review",
            "--eval-dir",
            str(eval_dir),
            "--case",
            "assembly",
            "--target",
            "missing",
        ],
    )

    assert result.exit_code == 2
    assert "has no target matching" in result.output
    assert not created


def _copy_fixtures(tmp_path: Path) -> Path:
    destination = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, destination)
    return destination / "eval_suites" / "review"
