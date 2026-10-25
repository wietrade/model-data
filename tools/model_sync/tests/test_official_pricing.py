"""官方定价页 Markdown 解析的回归测试（fixture 为真实页面的片段）。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model_sync import official_pricing  # noqa: E402
from model_sync.normalize import normalize_key  # noqa: E402

CLAUDE = """
| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Sonnet 4.1 ([retired](https://example.com)) | $15 / MTok | $18.75 / MTok | - | $1.50 / MTok | $75 / MTok |
"""

OPENAI = """
| Model | Short context input | Short context output | Short context cached input | Short context 30m write | Short context 12h write | Long context input | Long context output | Long context cached input | Long context 30m write | Long context 12h write |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6-sol | $2.00 | $10.00 | $0.20 | $2.50 | $5.00 | $4.00 | $15.00 | $0.40 | $5.00 | $10.00 |
| gpt-5.5 (<272K context length) | $5.00 | $30.00 | $0.50 | - | - | $10.00 | $45.00 | $1.00 | - | - |

| Model | Input | Output | Cached input |
| --- | --- | --- | --- |
| gpt-5.4-mini | $0.75 | $4.50 | $0.075 |
"""


class ClaudePricingTest(unittest.TestCase):
    def test_parses_main_table(self):
        parsed = official_pricing.parse_claude(CLAUDE)
        opus = parsed[normalize_key("claude-opus-5-5")]
        self.assertEqual(opus["prices"]["input"], 4.0)
        self.assertEqual(opus["prices"]["output"], 20.0)
        self.assertEqual(opus["prices"]["cache_read"], 0.2)
        self.assertEqual(opus["prices"]["cache_write"], 5.0)
        self.assertEqual(opus["prices"]["cache_write_1h"], 8.0)

    def test_keeps_context_hint_and_strips_annotation(self):
        parsed = official_pricing.parse_claude(CLAUDE)
        haiku = parsed[normalize_key("claude-haiku-5-5")]
        self.assertEqual(haiku["context_limit_hint"], 100000)
        self.assertEqual(haiku["base"], "Claude Haiku 5.5")
        self.assertEqual(haiku["prices"]["input"], 0.1)

    def test_dash_cell_is_absent(self):
        parsed = official_pricing.parse_claude(CLAUDE)
        sonnet = parsed[normalize_key("claude-sonnet-4-1")]
        self.assertNotIn("cache_write_1h", sonnet["prices"])

    def test_later_tables_do_not_override_main(self):
        duplicated = CLAUDE + "\n" + CLAUDE.replace("$4 / MTok", "$99 / MTok")
        parsed = official_pricing.parse_claude(duplicated)
        self.assertEqual(parsed[normalize_key("claude-opus-5-5")]["prices"]["input"], 4.0)


class OpenAIPricingTest(unittest.TestCase):
    def test_short_and_long_context_columns(self):
        parsed = official_pricing.parse_openai(OPENAI)
        sol = parsed[normalize_key("gpt-6-sol")]
        self.assertEqual(sol["prices"]["input"], 2.0)
        self.assertEqual(sol["prices"]["cache_write"], 2.5)
        self.assertEqual(sol["prices"]["cache_write_12h"], 5.0)
        self.assertEqual(sol["long_context"]["prices"]["input"], 4.0)

    def test_threshold_extracted_from_label(self):
        parsed = official_pricing.parse_openai(OPENAI)
        gpt55 = parsed[normalize_key("gpt-5.5")]
        self.assertEqual(gpt55["long_context"]["prompt_tokens_at_least"], 272000)

    def test_simple_table_shape(self):
        parsed = official_pricing.parse_openai(OPENAI)
        mini = parsed[normalize_key("gpt-5.4-mini")]
        self.assertEqual(mini["prices"]["input"], 0.75)
        self.assertEqual(mini["prices"]["cache_read"], 0.075)
        self.assertNotIn("long_context", mini)


IMAGE = """
## Standard

### Grouped Pricing Table data

| Model | Modality | Input | Output | Cached input |
| --- | --- | --- | --- | --- |
| gpt-image-2.5-sunburst | Image | $8.00 | $30.00 | $2.00 |
| gpt-image-2.5-sunburst | Text | $5.00 | - | $1.25 |

## Batch

### Grouped Pricing Table data

| Model | Modality | Input | Output | Cached input |
| --- | --- | --- | --- | --- |
| gpt-image-2.5-sunburst | Image | $4.00 | $15.00 | $1.00 |
| gpt-image-2.5-sunburst | Text | $2.50 | - | $0.625 |
"""


class ModalityTableTest(unittest.TestCase):
    def test_image_rows_become_image_fields(self):
        parsed = official_pricing.parse_openai(IMAGE)
        sunburst = parsed[normalize_key("gpt-image-2.5-sunburst")]
        self.assertEqual(sunburst["prices"]["input_image"], 8.0)
        self.assertEqual(sunburst["prices"]["output_image"], 30.0)
        self.assertEqual(sunburst["prices"]["cache_read_image"], 2.0)
        self.assertEqual(sunburst["prices"]["input"], 5.0)
        self.assertEqual(sunburst["prices"]["cache_read"], 1.25)

    def test_batch_section_is_ignored(self):
        parsed = official_pricing.parse_openai(IMAGE)
        sunburst = parsed[normalize_key("gpt-image-2.5-sunburst")]
        self.assertNotEqual(sunburst["prices"]["input_image"], 4.0)


class CompareTest(unittest.TestCase):
    def test_reports_value_and_missing_fields(self):
        official = [
            {"model_name": "claude-opus-5-5", "input": 4.0, "output": 20.0},
            {"model_name": "claude-unknown-1", "input": 1.0},
        ]
        parsed = official_pricing.parse_claude(CLAUDE)
        result = official_pricing.compare(official, parsed, ("claude-",))
        self.assertIn("claude-opus-5-5", result["matched"])
        # cache_read / cache_write / cache_write_1h 在目录里缺失 -> 记为差异
        fields = {(d["model"], d["field"]) for d in result["diffs"]}
        self.assertIn(("claude-opus-5-5", "cache_read"), fields)
        self.assertEqual(result["only_in_catalog"], ["claude-unknown-1"])


if __name__ == "__main__":
    unittest.main()
