from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Sequence

_WINDOWS = os.name == "nt"


def split_command(command: str, *, windows: bool | None = None) -> list[str]:
    """Split a direct-execution command using the current platform's rules."""

    use_windows = _WINDOWS if windows is None else windows
    if use_windows:
        return _split_windows_command(command)
    return shlex.split(command, posix=True)


def format_command(argv: Sequence[str], *, windows: bool | None = None) -> str:
    """Format arguments as a copyable command for the current platform."""

    use_windows = _WINDOWS if windows is None else windows
    if use_windows:
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _split_windows_command(command: str) -> list[str]:
    """Parse the quoting emitted by ``subprocess.list2cmdline`` on Windows."""

    arguments: list[str] = []
    index = 0
    while True:
        while index < len(command) and command[index] in " \t":
            index += 1
        if index >= len(command):
            return arguments

        characters: list[str] = []
        quoted = False
        while index < len(command):
            if command[index] in " \t" and not quoted:
                break

            slash_start = index
            while index < len(command) and command[index] == "\\":
                index += 1
            slash_count = index - slash_start

            if index < len(command) and command[index] == '"':
                characters.extend("\\" * (slash_count // 2))
                if slash_count % 2:
                    characters.append('"')
                    index += 1
                elif quoted and index + 1 < len(command) and command[index + 1] == '"':
                    characters.append('"')
                    index += 2
                else:
                    quoted = not quoted
                    index += 1
                continue

            characters.extend("\\" * slash_count)
            if index >= len(command) or command[index] in " \t" and not quoted:
                break
            characters.append(command[index])
            index += 1

        arguments.append("".join(characters))
