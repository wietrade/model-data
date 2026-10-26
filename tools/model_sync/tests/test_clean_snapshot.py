"""清洗的回归测试：结构与原文件完全一致，只改有问题的值。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.ops import clean_snapshot as cs  # noqa: E402


def item(**overrides):
    base = {
        "id": "m-1",
        "label": "m-1",
        "providerLabel": "Acme",
        "providerSlug": None,
        "type": "text",
        "group": "text",
        "vision": False,
        "reasoning": False,
        "contextLength": 128000,
        "maxOutputTokens": 32768,
        "imageEdit": False,
        "kind": "text",
        "capabilities": ["reasoning", "tool-use"],
        "free": False,
        "servedAt": "2026-10-21T00:00:00+00:00",
        "detail_Type": "Text generation",
        "detail_Endpoints": "/v1/chat/completions",
        "detail_Input": "text",
        "detail_Output": "text",
        "detail_VisionInput": "Not supported",
        "detail_ImageEditing": "Not supported",
        "detail_VideoInput": "Not supported",
        "detail_Reasoning": "Supported",
        "detail_Streaming": "Supported",
        "detail_ContextWindow": "128,000 tokens",
        "detail_MaximumOutput": "32,768 tokens",
        "detail_SupportedParameters": "tools, max_tokens",
    }
    base.update(overrides)
    return base


class StructureTest(unittest.TestCase):
    def test_keys_and_order_are_untouched(self):
        record, _ = cs.clean_item(item())
        self.assertEqual(list(record), list(item()))

    def test_no_extra_fields(self):
        record, _ = cs.clean_item(item(capabilities=["context-128k"]))
        self.assertNotIn("removed", record)
        self.assertNotIn("conflicts", record)
        self.assertNotIn("missing", record)
        self.assertNotIn("input_source", record)

    def test_input_is_not_mutated(self):
        original = item(capabilities=["context-128k"])
        cs.clean_item(original)
        self.assertIn("context-128k", original["capabilities"])


class ValueCleaningTest(unittest.TestCase):
    def test_context_token_removed(self):
        record, changes = cs.clean_item(item(capabilities=["reasoning", "context-128k", "context-1m"]))
        self.assertEqual(record["capabilities"], ["reasoning"])
        self.assertEqual(len(changes), 2)

    def test_site_vocabulary_preserved(self):
        record, _ = cs.clean_item(item(capabilities=["tool-use"], detail_Input="image, pdf, text"))
        self.assertEqual(record["capabilities"], ["tool-use"])
        self.assertEqual(record["detail_Input"], "image, pdf, text")

    def test_image_input_kept_when_vision_supported(self):
        record, changes = cs.clean_item(
            item(detail_Input="text", vision=True, detail_VisionInput="Supported", capabilities=["image-input"])
        )
        self.assertIn("image-input", record["capabilities"])
        self.assertEqual(changes, [])

    def test_image_input_removed_on_double_contradiction(self):
        record, changes = cs.clean_item(
            item(vision=False, detail_VisionInput="Not supported", capabilities=["image-input"])
        )
        self.assertEqual(record["capabilities"], [])
        self.assertEqual(changes[0]["reason"], "vision=false 且原文 Not supported")

    def test_reasoning_removed_only_when_both_say_no(self):
        removed, _ = cs.clean_item(item(reasoning=False, detail_Reasoning="Not supported", capabilities=["reasoning"]))
        self.assertEqual(removed["capabilities"], [])
        kept, _ = cs.clean_item(item(reasoning=False, detail_Reasoning="Supported", capabilities=["reasoning"]))
        self.assertEqual(kept["capabilities"], ["reasoning"])

    def test_backfill_context_and_max_output(self):
        record, changes = cs.clean_item(item(contextLength=None, maxOutputTokens=None))
        self.assertEqual(record["contextLength"], 128000)
        self.assertEqual(record["maxOutputTokens"], 32768)
        self.assertEqual(len(changes), 2)

    def test_backfill_does_not_override_existing_values(self):
        record, changes = cs.clean_item(
            item(contextLength=100000, maxOutputTokens=32768, detail_ContextWindow="200,000 tokens")
        )
        self.assertEqual(record["contextLength"], 100000)
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
