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

    def test_vision_supported_adds_image_even_when_detail_lists_text(self):
        """能输文本的模型也常能输截图：detail_Input 只写 text，但 vision 说是 -> 两者都要。"""
        record = ns.normalize_item(item(detail_Input="text", vision=True, detail_VisionInput="Supported"))
        self.assertEqual(record["input_modalities"], ["image", "text"])
        self.assertEqual(record["input_source"], "detail+vision")

    def test_vision_flag_alone_is_enough(self):
        record = ns.normalize_item(item(detail_Input="text", vision=True, detail_VisionInput="Not supported"))
        self.assertEqual(record["input_modalities"], ["image", "text"])

    def test_text_to_image_model_keeps_text_only_input(self):
        """文生图：输入就是 text，不能因为 type=image 就给它加 image 输入。"""
        record = ns.normalize_item(item(type="image", detail_Input="text", detail_Output="image"))
        self.assertEqual(record["input_modalities"], ["text"])
        self.assertEqual(record["output_modalities"], ["image"])

    def test_detail_input_wins_and_pdf_maps_to_file(self):
        record = ns.normalize_item(item(detail_Input="image, pdf, text", vision=True))
        self.assertEqual(record["input_modalities"], ["file", "image", "text"])

    def test_missing_modalities_fall_back_to_type(self):
        record = ns.normalize_item(
            item(type="image", detail_Input="Not reported", detail_Output="Not reported", capabilities=["image-input"])
        )
        self.assertEqual(record["output_modalities"], ["image"])
        self.assertEqual(record["output_source"], "type")
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
        self.assertEqual(record["context_source"], "detail")
        self.assertEqual(record["max_output_source"], "detail")

    def test_only_one_context_number_is_kept(self):
        """context-128k / context-1m 与 contextLength 重复，产出的数字只能有一个来源。"""
        record = ns.normalize_item(
            item(
                capabilities=["context-128k", "context-1m"],
                contextLength=1048576,
                detail_ContextWindow="1,048,576 tokens",
            )
        )
        self.assertEqual(record["context_length"], 1048576)
        self.assertEqual(record["context_source"], "numeric")
        self.assertEqual(record["conflicts"], [])
        self.assertNotIn("context-1m", record["capabilities"])

    def test_context_conflict_is_recorded_not_guessed(self):
        record = ns.normalize_item(item(contextLength=128000, detail_ContextWindow="200,000 tokens"))
        self.assertEqual(record["context_length"], 128000)
        self.assertEqual(record["conflicts"][0]["field"], "context_length")
        self.assertEqual(record["conflicts"][0]["detail"], 200000)

    def test_number_parser_handles_suffixes(self):
        self.assertEqual(ns._number("1M tokens"), 1000000)
        self.assertEqual(ns._number("128K"), 128000)
        self.assertEqual(ns._number("1,048,576 tokens"), 1048576)
        self.assertIsNone(ns._number("Not reported"))


class BillingDimensionTest(unittest.TestCase):
    def test_endpoint_decides(self):
        cases = {
            "/v1/images/generations": "image",
            "/v1/images/edits": "image",
            "/v1/videos/generations": "video",
            "/v1/audio/speech": "audio_character",
            "/v1/audio/transcriptions": "audio_second",
            "/v1/realtime": "audio_second",
            "/v1/chat/completions": "tokens",
            "/v1/embeddings": "tokens",
        }
        for endpoint, expected in cases.items():
            self.assertEqual(ns.billing_dimension([endpoint], "text"), expected, endpoint)

    def test_type_fallback_when_endpoints_missing(self):
        self.assertEqual(ns.billing_dimension([], "video"), "video")
        self.assertEqual(ns.billing_dimension([], "speech"), "audio_character")

    def test_junk_endpoints_are_dropped(self):
        record = ns.normalize_item(item(detail_Endpoints="None has passed a live request yet"))
        self.assertEqual(record["endpoints"], [])
        self.assertEqual(record["billing_dimension"], "tokens")


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
