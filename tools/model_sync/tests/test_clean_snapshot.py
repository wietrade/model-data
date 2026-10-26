"""清洗的回归测试：只保留一组事实，其余字段原样保留。"""

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
    def test_only_the_merged_detail_keys_are_dropped(self):
        record, _ = cs.clean_item(item())
        merged = {
            "detail_ContextWindow",
            "detail_MaximumOutput",
            "detail_Type",
            "detail_Reasoning",
            "detail_VisionInput",
            "detail_ImageEditing",
            "label",
        }
        expected = [k for k in item() if k not in merged]
        self.assertEqual(list(record), expected)

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
        self.assertIn("detail_ContextWindow", original)


class ValueCleaningTest(unittest.TestCase):
    def test_context_token_removed(self):
        record, changes = cs.clean_item(item(capabilities=["reasoning", "context-128k", "context-1m"]))
        self.assertEqual(record["capabilities"], ["reasoning"])
        self.assertEqual(sum(1 for c in changes if c["reason"] == "duplicate_of_contextLength"), 2)

    def test_site_vocabulary_preserved(self):
        record, _ = cs.clean_item(item(capabilities=["tool-use"], detail_Input="image, pdf, text"))
        self.assertEqual(record["capabilities"], ["tool-use"])
        self.assertEqual(record["detail_Input"], "image, pdf, text")

    def test_image_input_kept_when_vision_supported(self):
        record, changes = cs.clean_item(
            item(detail_Input="text", vision=True, detail_VisionInput="Supported", capabilities=["image-input"])
        )
        self.assertIn("image-input", record["capabilities"])
        self.assertEqual([c for c in changes if c["field"] == "capabilities"], [])

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
        reasons = [c["reason"] for c in changes]
        self.assertEqual(reasons.count("从 detail_ContextWindow 回填"), 1)
        self.assertEqual(reasons.count("从 detail_MaximumOutput 回填"), 1)

    def test_backfill_does_not_override_existing_values(self):
        record, changes = cs.clean_item(
            item(contextLength=100000, maxOutputTokens=32768, detail_ContextWindow="200,000 tokens")
        )
        self.assertEqual(record["contextLength"], 100000)
        self.assertEqual(
            [c["reason"] for c in changes],
            [
                "merged_into_contextLength",
                "merged_into_maxOutputTokens",
                "merged_into_type",
                "merged_into_reasoning",
                "merged_into_vision",
                "merged_into_imageEdit",
                "merged_into_id",
            ],
        )

    def test_all_duplicate_pairs_are_merged(self):
        record, _ = cs.clean_item(
            item(label="m-1", vision=True, detail_VisionInput="Supported", imageEdit=False)
        )
        self.assertEqual(record["id"], "m-1")
        self.assertIs(record["vision"], True)
        self.assertIs(record["imageEdit"], False)
        for key in ("label", "detail_VisionInput", "detail_ImageEditing"):
            self.assertNotIn(key, record)

    def test_detail_reasoning_is_merged_into_reasoning(self):
        record, _ = cs.clean_item(item(reasoning=True, detail_Reasoning="Supported"))
        self.assertIs(record["reasoning"], True)
        self.assertNotIn("detail_Reasoning", record)

    def test_type_detail_is_merged_into_type(self):
        record, _ = cs.clean_item(item(type="embedding", detail_Type="Embeddings"))
        self.assertEqual(record["type"], "embedding")
        self.assertNotIn("detail_Type", record)

    def test_merge_is_lossless(self):
        record, _ = cs.clean_item(item())
        self.assertNotIn("detail_ContextWindow", record)
        self.assertNotIn("detail_MaximumOutput", record)
        self.assertEqual(record["contextLength"], 128000)
        self.assertEqual(record["maxOutputTokens"], 32768)

    def test_detail_without_number_is_dropped_as_well(self):
        # "Not reported" 解析不出数字、数值字段也是空 -> 删掉不丢信息
        record, changes = cs.clean_item(
            item(contextLength=None, detail_ContextWindow="Not reported", detail_MaximumOutput="Not reported")
        )
        self.assertIsNone(record["contextLength"])
        self.assertNotIn("detail_ContextWindow", record)
        self.assertNotIn("detail_MaximumOutput", record)
        reasons = [c["reason"] for c in changes]
        self.assertIn("merged_into_contextLength", reasons)
        self.assertIn("merged_into_maxOutputTokens", reasons)


class BoolValueTest(unittest.TestCase):
    def test_supported_becomes_true_and_not_supported_false(self):
        record, changes = cs.clean_item(item())
        cs.normalize_detail_values(record, changes)
        self.assertIs(record["detail_Streaming"], True)
        self.assertIs(record["detail_VideoInput"], False)
        self.assertIn("Not supported -> false", [c["reason"] for c in changes])

    def test_not_reported_becomes_null(self):
        record, changes = cs.clean_item(
            item(detail_Input="Not reported", detail_Output="Not reported", detail_SupportedParameters="Not reported")
        )
        cs.normalize_detail_values(record, changes)
        self.assertIsNone(record["detail_Input"])
        self.assertIsNone(record["detail_Output"])
        self.assertIsNone(record["detail_SupportedParameters"])
        self.assertIn("Not reported -> null", [c["reason"] for c in changes])

    def test_empty_endpoint_sentence_becomes_null(self):
        record, changes = cs.clean_item(item(detail_Endpoints="None has passed a live request yet"))
        cs.normalize_detail_values(record, changes)
        self.assertIsNone(record["detail_Endpoints"])

    def test_null_is_kept_as_unknown(self):
        record, changes = cs.clean_item(item(detail_VideoInput=None, detail_Streaming=None))
        cs.normalize_detail_values(record, changes)
        self.assertIsNone(record["detail_VideoInput"])
        self.assertIsNone(record["detail_Streaming"])

    def test_modality_and_endpoint_lists_are_left_alone(self):
        record, changes = cs.clean_item(
            item(
                detail_Input="image, pdf, text",
                detail_Endpoints="/v1/embeddings",
                detail_VideoInput=None,
                detail_Streaming=None,
            )
        )
        cs.normalize_detail_values(record, changes)
        self.assertEqual(record["detail_Input"], "image, pdf, text")
        self.assertEqual(record["detail_Endpoints"], "/v1/embeddings")
        self.assertEqual([c for c in changes if "->" in c["reason"]], [])


if __name__ == "__main__":
    unittest.main()
