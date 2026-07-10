from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_STATIC_PATH = Path("src/glasskit/eval/review/static")
_ASSET_REFERENCE = re.compile(r'(?:src|href)="([^"]+)"')


class CustomBuildHook(BuildHookInterface):
    """Build and embed the review UI in release distributions."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version == "editable" or self.target_name not in {"sdist", "wheel"}:
            return

        root = Path(self.root)
        frontend = root / "review-ui"
        static = root / _STATIC_PATH
        if frontend.is_dir():
            _build_frontend(frontend)

        _verify_static_bundle(static)
        destination = (
            "glasskit/eval/review/static"
            if self.target_name == "wheel"
            else _STATIC_PATH.as_posix()
        )
        build_data["force_include"][str(static)] = destination


def _build_frontend(frontend: Path) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "Building GlassKit from a source checkout requires Node.js and npm."
        )
    subprocess.run([npm, "ci"], cwd=frontend, check=True)
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)


def _verify_static_bundle(static: Path) -> None:
    index = static / "index.html"
    if not index.is_file():
        raise RuntimeError(
            "The GlassKit review UI bundle is missing. Build from the source checkout "
            "or use an intact source distribution."
        )
    references = _ASSET_REFERENCE.findall(index.read_text(encoding="utf-8"))
    if not references:
        raise RuntimeError("The GlassKit review UI index references no bundled assets.")
    missing = [
        reference
        for reference in references
        if not _resolve_asset_reference(static, reference).is_file()
    ]
    if missing:
        raise RuntimeError(
            "The GlassKit review UI bundle has missing assets: " + ", ".join(missing)
        )


def _resolve_asset_reference(static: Path, reference: str) -> Path:
    path = PurePosixPath(reference.partition("?")[0].partition("#")[0].lstrip("/"))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        return static / "__invalid_asset_reference__"
    return static.joinpath(*path.parts)
