from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eval.suggest_criteria import (
    CaseExample,
    _load_case,
    _parse_suggestion,
    _select_examples,
)


class LoadCaseTests(unittest.TestCase):
    def test_expands_ranges_and_excludes_ignored_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video_path = root / "video.mp4"
            video_path.touch()
            case_path = root / "case.yaml"
            case_path.write_text(
                """video: video.mp4
sampling:
  every_s: 0.5
targets:
  step_5:
    samples:
    - range: [1.0, 2.0]
      expect: false
    - at: [2.0, 2.5]
      expect: true
    - at: 3.0
      expect: true
      ignore: unstable
""",
                encoding="utf-8",
            )

            loaded = _load_case(case_path, target_id="step_5")

            self.assertEqual(
                loaded.examples,
                [
                    CaseExample(1.0, False, 1),
                    CaseExample(1.5, False, 1),
                    CaseExample(2.0, True, 2),
                    CaseExample(2.5, True, 2),
                ],
            )


class SelectExamplesTests(unittest.TestCase):
    def test_spreads_each_class_across_label_blocks(self) -> None:
        examples = [
            *[CaseExample(float(index), False, 1) for index in range(8)],
            *[CaseExample(float(index), False, 2) for index in range(8, 11)],
            *[CaseExample(float(index), True, 3) for index in range(11, 15)],
            *[CaseExample(float(index), True, 4) for index in range(15, 17)],
        ]

        selected = _select_examples(examples, per_class=4)

        false_samples = [example for example in selected if not example.expected]
        true_samples = [example for example in selected if example.expected]
        self.assertEqual(len(false_samples), 4)
        self.assertEqual(len(true_samples), 4)
        self.assertEqual({example.block_index for example in false_samples}, {1, 2})
        self.assertEqual({example.block_index for example in true_samples}, {3, 4})
        self.assertEqual(selected, _select_examples(examples, per_class=4))


class ParseSuggestionTests(unittest.TestCase):
    def test_accepts_fenced_generalized_criteria(self) -> None:
        response = """```json
{
  "visual_analysis": "A broad foreground triangle crosses the center.",
  "generalization_notes": ["Uses topology rather than appearance."],
  "criteria": "## Required Features\\n\\n- A broad foreground triangle.\\n\\n## Acceptable Variations\\n\\n- Modest rotation.\\n\\n## Reject If\\n\\n- The foreground triangle is absent."
}
```"""

        suggestion = _parse_suggestion(response)

        self.assertIn("broad foreground triangle", suggestion.criteria)

    def test_rejects_video_specific_criteria(self) -> None:
        response = """{
  "visual_analysis": "The target is layered.",
  "generalization_notes": ["Supposedly general."],
  "criteria": "## Required Features\\n\\n- A pink triangle.\\n\\n## Acceptable Variations\\n\\n- Rotation.\\n\\n## Reject If\\n\\n- The triangle is absent."
}"""

        with self.assertRaisesRegex(RuntimeError, "exact colors"):
            _parse_suggestion(response)


if __name__ == "__main__":
    unittest.main()
