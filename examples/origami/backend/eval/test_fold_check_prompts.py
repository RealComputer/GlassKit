from __future__ import annotations

import unittest

from eval.adapter import (
    IMAGE_LAYOUT_COMPOSITE,
    IMAGE_LAYOUT_SEPARATE,
    _image_layout_config,
)
from src.fold_check_prompts import (
    FOLD_CHECK_IMAGE_PAIR_SYSTEM_PROMPT,
    fold_check_image_pair_completion_payload,
)


class FoldCheckImagePairPromptTests(unittest.TestCase):
    def test_payload_assigns_distinct_roles_to_ordered_images(self) -> None:
        payload = fold_check_image_pair_completion_payload(
            model="test-model",
            thread_id="test-thread",
            prompt="Match the fold.",
            camera_image_url="camera-url",
            reference_image_url="reference-url",
        )

        messages = payload["messages"]
        self.assertEqual(messages[0]["content"], FOLD_CHECK_IMAGE_PAIR_SYSTEM_PROMPT)
        self.assertIn(
            "only image that may contain the candidate", messages[0]["content"]
        )
        self.assertIn("Never reverse these roles", messages[0]["content"])

        content = messages[1]["content"]
        self.assertIn("camera/candidate", content[1]["text"])
        self.assertEqual(content[2]["image_url"]["url"], "camera-url")
        self.assertIn("reference/target", content[3]["text"])
        self.assertEqual(content[4]["image_url"]["url"], "reference-url")

    def test_image_layout_defaults_to_composite(self) -> None:
        self.assertEqual(_image_layout_config(None), IMAGE_LAYOUT_COMPOSITE)

    def test_image_layout_accepts_separate(self) -> None:
        self.assertEqual(_image_layout_config("separate"), IMAGE_LAYOUT_SEPARATE)

    def test_image_layout_rejects_unknown_value(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "image_layout must be"):
            _image_layout_config("side-by-side")
