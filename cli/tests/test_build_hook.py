import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

_HOOK_PATH = Path(__file__).parents[1] / "hatch_build.py"
_HOOK_SPEC = importlib.util.spec_from_file_location("glasskit_hatch_build", _HOOK_PATH)
assert _HOOK_SPEC is not None and _HOOK_SPEC.loader is not None
_HOOK_MODULE = importlib.util.module_from_spec(_HOOK_SPEC)
_HOOK_SPEC.loader.exec_module(_HOOK_MODULE)
_build_frontend = cast(Callable[[Path], None], _HOOK_MODULE._build_frontend)
_verify_static_bundle = cast(Callable[[Path], None], _HOOK_MODULE._verify_static_bundle)


def test_source_frontend_build_reinstalls_locked_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frontend = tmp_path / "review-ui"
    (frontend / "node_modules").mkdir(parents=True)
    commands: list[tuple[list[str], Path, bool]] = []

    monkeypatch.setattr(
        _HOOK_MODULE.shutil,
        "which",
        lambda executable: "/toolchain/npm" if executable == "npm" else None,
    )

    def record_run(command: list[str], *, cwd: Path, check: bool) -> None:
        commands.append((command, cwd, check))

    monkeypatch.setattr(_HOOK_MODULE.subprocess, "run", record_run)

    _build_frontend(frontend)

    assert commands == [
        (["/toolchain/npm", "ci"], frontend, True),
        (["/toolchain/npm", "run", "build"], frontend, True),
    ]


def test_review_bundle_verification_requires_every_referenced_asset(
    tmp_path: Path,
) -> None:
    static = tmp_path / "static"
    assets = static / "assets"
    assets.mkdir(parents=True)
    (static / "index.html").write_text(
        '<link href="/assets/app.css"><script src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets / "app.css").write_text("body {}", encoding="utf-8")
    script = assets / "app.js"
    script.write_text("export {}", encoding="utf-8")

    _verify_static_bundle(static)
    script.unlink()

    with pytest.raises(RuntimeError, match="/assets/app.js"):
        _verify_static_bundle(static)
