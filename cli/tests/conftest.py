from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_eval_checkpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkpoint_root = tmp_path / "glasskit-checkpoints"
    monkeypatch.setattr(
        "glasskit.eval.checkpoints._checkpoint_root",
        lambda _eval_dir: checkpoint_root,
    )
