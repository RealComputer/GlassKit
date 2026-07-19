from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import patch

from PIL import Image

from eval.gemini import GeminiResult
from eval.label_adapter import Evaluator


class EvaluatorTests(TestCase):
    def test_labels_seed_sample_with_target_reference(self) -> None:
        step = SimpleNamespace(id="step_1", criteria="Match the reference.")
        reference = Image.new("RGB", (4, 4), "white")
        camera = Image.new("RGB", (4, 4), "black")
        captured: dict[str, Any] = {}
        client = object()

        def fake_label_camera_image(
            received_client: object,
            **kwargs: Any,
        ) -> GeminiResult:
            captured["client"] = received_client
            captured.update(kwargs)
            return GeminiResult(
                value=True,
                response_text="true",
                interaction_id="interaction-1",
            )

        with (
            patch(
                "eval.label_adapter.load_fold_check_steps",
                return_value=[step],
            ),
            patch(
                "eval.label_adapter.load_fold_check_reference_images",
                return_value={"step_1": reference},
            ),
            patch("eval.label_adapter.genai.Client", return_value=client),
            patch(
                "eval.label_adapter.label_camera_image",
                side_effect=fake_label_camera_image,
            ),
        ):
            evaluator = Evaluator(steps_path=Path("steps.json"))
            result = evaluator.evaluate(
                SimpleNamespace(
                    image=camera,
                    case_name="draft-case",
                    sample_index=3,
                ),
                SimpleNamespace(id="step_1"),
            )

        self.assertIs(result, True)
        self.assertIs(captured["client"], client)
        self.assertIs(captured["camera_image"], camera)
        self.assertIsNot(captured["reference_image"], reference)
        self.assertEqual(captured["prompt"], "Match the reference.")
        self.assertEqual(captured["log_context"], "seed=draft-case/step_1/3")

    def test_rejects_unknown_target(self) -> None:
        with (
            patch("eval.label_adapter.load_fold_check_steps", return_value=[]),
            patch(
                "eval.label_adapter.load_fold_check_reference_images",
                return_value={},
            ),
        ):
            evaluator = Evaluator(steps_path=Path("steps.json"))

        with self.assertRaisesRegex(
            RuntimeError,
            "unknown origami target id: step_9",
        ):
            evaluator.evaluate(
                SimpleNamespace(image=Image.new("RGB", (1, 1))),
                SimpleNamespace(id="step_9"),
            )
