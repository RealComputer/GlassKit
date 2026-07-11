from __future__ import annotations

from pathlib import Path

from glasskit.eval.expectations import load_eval_directory

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_review_fixture_loads_through_normal_eval_pipeline() -> None:
    eval_directory = load_eval_directory(FIXTURES / "eval_directories" / "review")

    assert [case.name for case in eval_directory.cases] == ["assembly", "inspection"]
    assert sum(len(case.samples) for case in eval_directory.cases) == 14

    assembly = eval_directory.cases[0]
    bracket = next(
        target for target in assembly.targets if target.id == "bracket_seated"
    )
    evidence = next(target for target in assembly.targets if target.id == "evidence")

    assert bracket.label == "Bracket seated"
    assert bracket.config["prompt_id"] == "workflow.bracket_seated"
    assert bracket.samples[0].comment == "The bracket is not seated in the first state."
    assert [sample.timestamp_s for sample in evidence.samples[:3]] == [0.0, 0.25, 0.5]
    assert (
        evidence.samples[0].comment == "Structured expectation with a custom cadence."
    )
