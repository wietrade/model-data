"""官方页解析的回归测试（fixture 取自真实页面片段）。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model_sync import official_meta  # noqa: E402

OPENAI_MD = """
# GPT-5.5

- 1,050,000 context window
- 128,000 max output tokens
- Sep 30, 2025 knowledge cutoff
"""

CLAUDE_MD = """
---
title: Claude Haiku 4.5 overview
---

Context window: 200K tokens · Max output: 64K tokens · Input pricing: $1 / MTok · Output pricing: $5 / MTok
"""

CLAUDE_MD_MILLION = """
Context window: 1M tokens · Max output: 128K tokens · Input pricing: $2 / MTok
"""

GEMINI_HTML = """
<div class="model-card">
  <span>Token limits</span>
  <div>Input token limit</div><div>65,536</div>
  <div>Output token limit</div><div>32,768</div>
</div>
"""


class OpenAITest(unittest.TestCase):
    def test_reads_both_limits(self):
        parsed = official_meta.parse_openai(OPENAI_MD)
        self.assertEqual(parsed["context_length"], 1050000)
        self.assertEqual(parsed["max_output_tokens"], 128000)

    def test_missing_page_yields_nothing(self):
        self.assertEqual(official_meta.parse_openai("404 page not found"), {})


class ClaudeTest(unittest.TestCase):
    def test_k_suffix(self):
        parsed = official_meta.parse_claude(CLAUDE_MD)
        self.assertEqual(parsed["context_length"], 200000)
        self.assertEqual(parsed["max_output_tokens"], 64000)

    def test_m_suffix(self):
        parsed = official_meta.parse_claude(CLAUDE_MD_MILLION)
        self.assertEqual(parsed["context_length"], 1000000)
        self.assertEqual(parsed["max_output_tokens"], 128000)


class GeminiTest(unittest.TestCase):
    def test_page_html(self):
        parsed = official_meta.parse_gemini_page(GEMINI_HTML)
        self.assertEqual(parsed["context_length"], 65536)
        self.assertEqual(parsed["max_output_tokens"], 32768)

    def test_list_api(self):
        payload = {
            "models": [
                {"name": "models/gemini-4-argon", "inputTokenLimit": 1048576, "outputTokenLimit": 32768}
            ]
        }
        parsed = official_meta.parse_gemini_api(payload)
        self.assertEqual(parsed["gemini-4-argon"]["context_length"], 1048576)
        self.assertEqual(parsed["gemini-4-argon"]["max_output_tokens"], 32768)


class MergeTest(unittest.TestCase):
    def test_page_wins_and_conflict_recorded(self):
        merged = official_meta.merge_sources(
            {"context_length": 65536, "max_output_tokens": 32768},
            {"context_length": 131072, "max_output_tokens": 32768},
        )
        self.assertEqual(merged["context_length"], 65536)
        self.assertEqual(merged["conflicts"], [{"field": "context_length", "doc": 65536, "api": 131072}])

    def test_api_fills_missing_field(self):
        merged = official_meta.merge_sources({"context_length": 65536}, {"max_output_tokens": 65536})
        self.assertEqual(merged["max_output_tokens"], 65536)


class HarvestDiffTest(unittest.TestCase):
    """快照 → 差异的取用规则：只有逐模型页给出的值才能驱动自动校正。"""

    def setUp(self):
        from tools.ops import harvest_official as harvest

        self.harvest = harvest

    def _row(self, **overrides):
        row = {
            "model": "m",
            "vendor": "Google",
            "basis": "page",
            "context_length": 131072,
            "max_output_tokens": 32768,
            "catalog_context_length": 65536,
            "catalog_max_output_tokens": 32768,
            "source_url": "https://example.com",
        }
        row.update(overrides)
        return row

    def test_page_value_becomes_diff(self):
        diffs = self.harvest.diff_rows([self._row()])
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["field"], "context_length")
        self.assertEqual(diffs[0]["official"], 131072)

    def test_api_only_never_becomes_diff(self):
        row = self._row(basis="api_only")
        self.assertEqual(self.harvest.diff_rows([row]), [])

    def test_missing_official_value_is_skipped(self):
        row = self._row(context_length=None, max_output_tokens=None)
        self.assertEqual(self.harvest.diff_rows([row]), [])


if __name__ == "__main__":
    unittest.main()
