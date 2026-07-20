from __future__ import annotations

import pytest

from glasskit.eval.commands import format_command, serialize_command, split_command


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
    command = serialize_command(argv, windows=True)

    assert split_command(command, windows=True) == argv


def test_windows_command_parsing_accepts_quoted_executable_path() -> None:
    command = r'"C:\Program Files\Python\python.exe" "C:\eval adapter.py" --verbose'

    assert split_command(command, windows=True) == [
        r"C:\Program Files\Python\python.exe",
        r"C:\eval adapter.py",
        "--verbose",
    ]


def test_command_serialization_uses_platform_specific_quoting() -> None:
    argv = ["glasskit", "eval", "run", "--resume", "eval dir/checkpoint"]

    assert serialize_command(argv, windows=False) == (
        "glasskit eval run --resume 'eval dir/checkpoint'"
    )
    assert serialize_command(argv, windows=True) == (
        'glasskit eval run --resume "eval dir/checkpoint"'
    )


def test_command_formatting_uses_shell_safe_quoting() -> None:
    argv = [
        "glasskit",
        "eval",
        "review",
        "--eval-dir",
        r"C:\eval&old",
        "--case",
        "Ada's $case",
    ]

    assert format_command(argv, windows=False) == (
        "glasskit eval review --eval-dir 'C:\\eval&old' --case 'Ada'\"'\"'s $case'"
    )
    assert format_command(argv, windows=True) == (
        "& 'glasskit' 'eval' 'review' '--eval-dir' 'C:\\eval&old' "
        "'--case' 'Ada''s $case'"
    )


@pytest.mark.parametrize("quote", ["'", "\u2018", "\u2019", "\u201a", "\u201b"])
def test_powershell_formatting_escapes_every_single_quote_delimiter(
    quote: str,
) -> None:
    case_name = f"Ada{quote}; Write-Output injected; {quote}case"

    command = format_command(["glasskit", "--case", case_name], windows=True)

    assert command == (
        f"& 'glasskit' '--case' "
        f"'Ada{quote}{quote}; Write-Output injected; {quote}{quote}case'"
    )


def test_posix_command_parsing_still_rejects_unclosed_quotes() -> None:
    with pytest.raises(ValueError, match="No closing quotation"):
        split_command("python 'adapter.py", windows=False)
