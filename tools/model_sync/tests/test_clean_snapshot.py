"""清洗（站点口径）的回归测试：只去冗余/矛盾，不引入我们自己的词表。"""

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
        "type": "text",
        "kind": "text",
        "group": "text",
        "contextLength": 128000,
        "maxOutputTokens": 32768,
        "vision": False,
        "reasoning": False,
        "imageEdit": False,
        "capabilities": ["reasoning", "tool-use"],
        "detail_Input": "text",
        "detail_Output": "text",
        "detail_VisionInput": "Not supported",
        "detail_Reasoning": "Supported",
        "detail_ContextWindow": "128,000 tokens",
        "detail_MaximumOutput": "32,768 tokens",
        "detail_Endpoints": "/v1/chat/completions",
    }
    base.update(overrides)
    return base


class CleanTest(unittest.TestCase):
    def test_context_token_is_dropped_and_recorded(self):
        record = cs.clean_item(item(capabilities=["reasoning", "context-128k", "context-1m"]))
        self.assertNotIn("context-128k", record["capabilities"])
        self.assertNotIn("context-1m", record["capabilities"])
        self.assertEqual(
            [x["value"] for x in record["removed"]], ["context-128k", "context-1m"]
        )

    def test_site_vocabulary_is_preserved(self):
        """不把 tool-use 改成 tools，也不把 pdf 改成 file。"""
        record = cs.clean_item(item(capabilities=["tool-use"], detail_Input="image, pdf, text"))
        self.assertEqual(record["capabilities"], ["tool-use"])
        self.assertEqual(record["input"], ["image", "pdf", "text"])

    def test_image_input_kept_when_vision_supported(self):
        """能输文本也能输截图：detail_Input 只写 text，但视觉支持 -> 保留 token。"""
        record = cs.clean_item(item(detail_Input="text", vision=True, detail_VisionInput="Supported",
                                    capabilities=["image-input"]))
        self.assertIn("image-input", record["capabilities"])
        self.assertEqual([c["reason"] for c in record["conflicts"]], ["not_listed_in_detail_Input"])

    def test_image_input_removed_only_with_double_contradiction(self):
        record = cs.clean_item(item(vision=False, detail_VisionInput="Not supported",
                                    capabilities=["image-input"]))
        self.assertNotIn("image-input", record["capabilities"])
        self.assertIn("contradicts_detail_VisionInput", [c["reason"] for c in record["conflicts"]])

    def test_reasoning_token_removed_only_when_detail_says_no(self):
        record = cs.clean_item(item(reasoning=False, detail_Reasoning="Not supported",
                                    capabilities=["reasoning"]))
        self.assertNotIn("reasoning", record["capabilities"])

    def test_type_aliases_only_when_different(self):
        same = cs.clean_item(item())
        self.assertNotIn("type_aliases", same)
        different = cs.clean_item(item(kind="retrieval", group="multimodal"))
        self.assertEqual(different["type_aliases"], {"kind": "retrieval", "group": "multimodal"})

    def test_missing_uses_site_field_names(self):
        record = cs.clean_item(item(contextLength=0, maxOutputTokens=0,
                                    detail_ContextWindow="Not reported",
                                    detail_MaximumOutput="Not reported",
                                    detail_Input="Not reported", detail_Output="Not reported"))
        self.assertEqual(record["missing"], ["contextLength", "maxOutputTokens", "detail_Input", "detail_Output"])
        self.assertEqual(record["context_source"], "none")

    def test_max_output_greater_than_context_is_flagged(self):
        record = cs.clean_item(item(contextLength=100000, maxOutputTokens=128000,
                                    detail_ContextWindow="100,000 tokens",
                                    detail_MaximumOutput="128,000 tokens"))
        self.assertEqual(record["conflicts"][0]["reason"], "greater_than_contextWindow")
        self.assertEqual(record["max_output_tokens"], 128000)


if __name__ == "__main__":
    unittest.main()
