"""快照清洗的回归测试：冗余字段合并、过度声明的 token 降级。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.ops import normalize_snapshot as ns  # noqa: E402


def item(**overrides):
    base = {
        "id": "m-1",
        "providerLabel": "Acme",
        "type": "text",
        "contextLength": 128000,
        "maxOutputTokens": 32768,
        "vision": False,
        "reasoning": False,
        "imageEdit": False,
        "capabilities": [],
        "detail_Input": "text",
        "detail_Output": "text",
        "detail_VisionInput": "Not supported",
        "detail_Reasoning": "Not supported",
        "detail_ImageEditing": "Not supported",
        "detail_ContextWindow": "128,000 tokens",
        "detail_MaximumOutput": "32,768 tokens",
        "detail_SupportedParameters": "max_tokens, tools, tool_choice, response_format",
        "detail_Endpoints": "/v1/chat/completions",
    }
    base.update(overrides)
    return base


class NormalizeTest(unittest.TestCase):
    def test_context_tokens_are_dropped(self):
        """context-128k / context-1m 与 contextLength 重复，不应留下。"""
        record = ns.normalize_item(item(capabilities=["context-128k", "context-1m"]))
        self.assertEqual(record["context_length"], 128000)
        self.assertNotIn("context-128k", record["capabilities"])
        self.assertNotIn("context-1m", record["capabilities"])

    def test_token_overclaim_is_ignored(self):
        """token 说能看图、但 vision=false 且原文 Not supported -> 不写 image。"""
        record = ns.normalize_item(item(capabilities=["image-input"], detail_Input="text"))
        self.assertEqual(record["input_modalities"], ["text"])

    def test_detail_input_wins_and_pdf_maps_to_file(self):
        record = ns.normalize_item(item(detail_Input="image, pdf, text", vision=True))
        self.assertEqual(record["input_modalities"], ["file", "image", "text"])

    def test_missing_modalities_fall_back_to_type(self):
        record = ns.normalize_item(
            item(type="image", detail_Input="Not reported", detail_Output="Not reported", capabilities=["image-input"])
        )
        self.assertEqual(record["output_modalities"], ["image"])
        self.assertEqual(record["modalities_source"], "type")
        self.assertIn("output_modalities", record["unknown"])

    def test_capabilities_from_params_preferred(self):
        record = ns.normalize_item(item(capabilities=["tool-use", "structured-output"]))
        self.assertEqual(record["capabilities_source"], "params")
        self.assertEqual(record["capabilities"], ["structured_output", "tools"])

    def test_capabilities_fall_back_to_tokens(self):
        record = ns.normalize_item(
            item(capabilities=["tool-use", "web-search"], detail_SupportedParameters="Not reported")
        )
        self.assertEqual(record["capabilities_source"], "tokens")
        self.assertEqual(record["capabilities"], ["tools", "web_search"])
        self.assertIn("supported_parameters", record["unknown"])

    def test_reasoning_and_cache_from_bool_and_tokens(self):
        record = ns.normalize_item(item(reasoning=True, capabilities=["implicit-caching"]))
        self.assertIn("reasoning", record["capabilities"])
        self.assertIn("cache_implicit", record["capabilities"])

    def test_embedding_from_type(self):
        record = ns.normalize_item(item(type="embedding", detail_Input="text", detail_Output="Not reported"))
        self.assertIn("embedding", record["capabilities"])
        self.assertEqual(ns.model_type(record), "embedding")

    def test_missing_numbers_backfilled_from_detail(self):
        record = ns.normalize_item(item(contextLength=None, maxOutputTokens=None))
        self.assertEqual(record["context_length"], 128000)
        self.assertEqual(record["max_output_tokens"], 32768)


class TypeDerivationTest(unittest.TestCase):
    def test_speech_and_transcription(self):
        self.assertEqual(ns.model_type({"input_modalities": ["text"], "output_modalities": ["audio"]}), "speech")
        self.assertEqual(ns.model_type({"input_modalities": ["audio"], "output_modalities": ["text"]}), "transcription")

    def test_realtime_needs_bidirectional_audio(self):
        self.assertEqual(
            ns.model_type({"input_modalities": ["audio", "text"], "output_modalities": ["audio", "text"]}),
            "realtime",
        )

    def test_image_and_video(self):
        self.assertEqual(ns.model_type({"output_modalities": ["image"]}), "image")
        self.assertEqual(ns.model_type({"output_modalities": ["text", "video"]}), "video")


if __name__ == "__main__":
    unittest.main()
