from __future__ import annotations

import subprocess

import pytest

from glasskit.eval.commands import format_command, split_command


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "adapter.py"],
        [r"C:\Program Files\Python\python.exe", r"C:\eval adapter\adapter.py"],
        ["python", "", "two words"],
        ["python", 'say"hello', "C:\\path with space\\"],
        ["glasskit", "eval", "run", "--resume", r"C:\Users\Ada Lovelace\eval"],
    ],
)
def test_windows_command_parsing_round_trips_native_quoting(argv: list[str]) -> None:
    command = subprocess.list2cmdline(argv)

    assert split_command(command, windows=True) == argv


def test_windows_command_parsing_accepts_quoted_executable_path() -> None:
    command = r'"C:\Program Files\Python\python.exe" "C:\eval adapter.py" --verbose'

    assert split_command(command, windows=True) == [
        r"C:\Program Files\Python\python.exe",
        r"C:\eval adapter.py",
        "--verbose",
    ]


def test_command_formatting_uses_platform_specific_quoting() -> None:
    argv = ["glasskit", "eval", "run", "--resume", "eval dir/checkpoint"]

    assert format_command(argv, windows=False) == (
        "glasskit eval run --resume 'eval dir/checkpoint'"
    )
    assert format_command(argv, windows=True) == (
        'glasskit eval run --resume "eval dir/checkpoint"'
    )


def test_posix_command_parsing_still_rejects_unclosed_quotes() -> None:
    with pytest.raises(ValueError, match="No closing quotation"):
        split_command("python 'adapter.py", windows=False)
