"""快照比对：清洗后再比，避免 `token` 过度声明造成假差异。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.ops import compare_snapshot as cs  # noqa: E402


def local(**overrides):
    base = {
        "model_name": "m-1",
        "context_length": 128000,
        "max_output_tokens": 32768,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "capabilities": ["reasoning", "tools"],
    }
    base.update(overrides)
    return base


def raw(**overrides):
    base = {
        "id": "m-1",
        "type": "text",
        "contextLength": 128000,
        "maxOutputTokens": 32768,
        "vision": False,
        "reasoning": True,
        "capabilities": ["reasoning", "tool-use", "image-input"],
        "detail_Input": "text",
        "detail_Output": "text",
        "detail_VisionInput": "Not supported",
        "detail_Reasoning": "Supported",
        "detail_SupportedParameters": "tools, tool_choice, max_tokens",
        "detail_Endpoints": "/v1/chat/completions",
    }
    base.update(overrides)
    return base


class CompareSnapshotTest(unittest.TestCase):
    def test_raw_snapshot_is_normalized_before_diff(self):
        """token 说 image-input、但原文说 Not supported -> 不该报模态差异。"""
        _, _, diffs = cs.compare([local()], [raw()])
        self.assertEqual([d for d in diffs if d["field"] == "input_modalities"], [])

    def test_modality_diff_reported_as_set(self):
        _, _, diffs = cs.compare(
            [local(input_modalities=["text"])],
            [raw(detail_Input="image, text", vision=True, detail_VisionInput="Supported")],
        )
        modal = [d for d in diffs if d["field"] == "input_modalities"][0]
        self.assertEqual(modal["snapshot"], ["image", "text"])
        self.assertEqual(modal["ours"], ["text"])
        self.assertFalse(modal["low"])

    def test_capability_diff_marks_low_confidence_when_from_tokens(self):
        _, _, diffs = cs.compare(
            [local(capabilities=["reasoning"])],
            [raw(detail_SupportedParameters="Not reported", capabilities=["reasoning", "tool-use"])],
        )
        cap = [d for d in diffs if d["field"] == "capabilities"][0]
        self.assertEqual(cap["snapshot"], ["reasoning", "tools"])
        self.assertTrue(cap["low"])

    def test_already_normalized_snapshot_is_accepted(self):
        item = {
            "id": "m-1",
            "context_length": 128000,
            "max_output_tokens": 32768,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "capabilities": ["reasoning", "tools"],
        }
        matched, unmatched, diffs = cs.compare([local()], [item])
        self.assertEqual(matched, ["m-1"])
        self.assertEqual(diffs, [])


if __name__ == "__main__":
    unittest.main()
