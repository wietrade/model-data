"""Expression generation must match the presets the admin UI ships.

The presets in ``web/src/features/system-settings/models/tiered-pricing-editor.tsx``
are the reference spelling for tier names, ``len`` boundaries and variable use.
Any drift between our generated expressions and those presets is a billing bug,
so they are asserted literally.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model_sync import expr  # noqa: E402


class ExpressionTest(unittest.TestCase):
    def test_gpt_5_4_matches_admin_preset(self):
        row = {
            "input": 2.5,
            "output": 15,
            "cache_read": 0.25,
            "tiers": [
                {"prompt_tokens_at_least": 272000, "input": 5, "output": 22.5, "cache_read": 0.5}
            ],
        }
        self.assertEqual(
            expr.build(row)[0],
            'len <= 272000 ? tier("standard", p * 2.5 + c * 15 + cr * 0.25)'
            ' : tier("long_context", p * 5 + c * 22.5 + cr * 0.5)',
        )

    def test_claude_sonnet_matches_admin_preset(self):
        row = {
            "input": 3,
            "output": 15,
            "cache_read": 0.3,
            "cache_write": 3.75,
            "cache_write_1h": 6,
            "tiers": [
                {
                    "prompt_tokens_at_least": 200000,
                    "input": 6,
                    "output": 22.5,
                    "cache_read": 0.6,
                    "cache_write": 7.5,
                    "cache_write_1h": 12,
                }
            ],
        }
        self.assertEqual(
            expr.build(row)[0],
            'len <= 200000 ? tier("standard", p * 3 + c * 15 + cr * 0.3 + cc * 3.75 + cc1h * 6)'
            ' : tier("long_context", p * 6 + c * 22.5 + cr * 0.6 + cc * 7.5 + cc1h * 12)',
        )

    def test_three_tiers_nest_on_len(self):
        row = {
            "input": 1.2,
            "output": 6,
            "tiers": [
                {"prompt_tokens_at_least": 32000, "input": 2.4, "output": 12},
                {"prompt_tokens_at_least": 128000, "input": 3, "output": 15},
            ],
        }
        self.assertEqual(
            expr.build(row)[0],
            'len <= 32000 ? tier("standard", p * 1.2 + c * 6)'
            ' : len <= 128000 ? tier("long_context", p * 2.4 + c * 12)'
            ' : tier("long_context_2", p * 3 + c * 15)',
        )

    def test_split_output_uses_img_o_and_drops_aggregate(self):
        row = {
            "input": 5,
            "output": 32,
            "output_text": 10,
            "output_image": 32,
            "cache_read": 1.25,
            "cache_read_image": 2,
            "input_image": 8,
        }
        self.assertEqual(
            expr.build(row)[0],
            'tier("standard", p * 5 + c * 10 + img_o * 32 + cr * 1.25'
            " + img_cr * 2 + img * 8)",
        )

    def test_deepseek_peak_halves_off_peak(self):
        row = {
            "input": 0.3,
            "output": 1.2,
            "cache_read": 0.006,
            "time_tiers": {
                "rule": "deepseek_peak",
                "peak": {"input": 0.3, "output": 1.2, "cache_read": 0.006},
                "off_peak_multiplier": 0.5,
            },
        }
        expression = expr.build(row)[0]
        self.assertTrue(expression.startswith(expr.PEAK_TERM + " ? "))
        self.assertIn('tier("peak", p * 0.3 + c * 1.2 + cr * 0.006)', expression)
        self.assertIn('tier("off_peak", p * 0.15 + c * 0.6 + cr * 0.003)', expression)

    def test_unknown_time_rule_is_not_priced_at_peak(self):
        row = {
            "input": 1,
            "output": 2,
            "time_tiers": {"rule": "something_else", "peak": {"input": 1}},
        }
        self.assertEqual(expr.build(row)[0], 'tier("standard", p * 1 + c * 2)')

    def test_free_model_is_explicit_zero(self):
        self.assertEqual(
            expr.build({"price_kind": "free", "input": 0, "output": 0})[0],
            'tier("free", p * 0 + c * 0)',
        )

    def test_number_avoids_exponent_and_trailing_zeros(self):
        self.assertEqual(expr.number(0.0000006), "0.0000006")
        self.assertEqual(expr.number(1.50), "1.5")
        self.assertEqual(expr.number(120.0), "120")

    def test_unpriced_meter_is_reported_not_guessed(self):
        row = {
            "per_image": 0.134,
            "meters": [
                {
                    "dim": "output_image",
                    "price": 0.134,
                    "unit": "image",
                    "when": {"resolution": "1K-2K"},
                },
                {"dim": "output_image", "price": 0.24, "unit": "image", "when": {"resolution": "4K"}},
            ],
        }
        expression, skipped = expr.build(row)
        self.assertEqual(expression, 'tier("image", fixed(0.134)) * image_count')
        self.assertTrue(any("resolution=4K" in item for item in skipped))


if __name__ == "__main__":
    unittest.main()
