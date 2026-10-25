"""多源合并的优先级：官方 > 聚合源；官方自己矛盾时不猜。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model_sync import merge  # noqa: E402
from model_sync.sources import SourceModel  # noqa: E402


def candidate(source, context_length=0, max_output_tokens=0, name="gemini-x"):
    return SourceModel(
        vendor_key="google",
        source=source,
        source_id=name,
        model_name=name,
        vendor_name="Google",
        icon="",
        context_length=context_length,
        max_output_tokens=max_output_tokens,
    )


class OfficialPriorityTest(unittest.TestCase):
    def test_official_beats_aggregators(self):
        values, conflicts, resolved = merge.resolve_values(
            [
                candidate("models.dev", 65536, 32768),
                candidate("openrouter", 65536, 32768),
                candidate("official:google", 131072, 65536),
            ],
            tie_break="openrouter",
        )
        self.assertEqual(values["context_length"], 131072)
        self.assertEqual(values["max_output_tokens"], 65536)
        self.assertEqual(resolved["context_length"], "official:google")
        self.assertEqual(conflicts, set())

    def test_agreement_still_wins(self):
        values, conflicts, resolved = merge.resolve_values(
            [
                candidate("models.dev", 131072, 32768),
                candidate("openrouter", 131072, 32768),
                candidate("official:google", 131072, 32768),
            ]
        )
        self.assertEqual(values["context_length"], 131072)
        self.assertEqual(resolved, {})

    def test_official_self_disagreement_falls_back_to_tie_break(self):
        values, conflicts, resolved = merge.resolve_values(
            [
                candidate("models.dev", 65536, 32768),
                candidate("official:google", 131072, 32768),
                candidate("official:anthropic", 262144, 0),
            ],
            tie_break="models.dev",
        )
        # 两个官方源互相矛盾 -> 不采信官方，回落到 tie_break
        self.assertEqual(values["context_length"], 65536)
        self.assertEqual(resolved["context_length"], "models.dev")

    def test_no_tie_break_leaves_conflict(self):
        values, conflicts, resolved = merge.resolve_values(
            [candidate("models.dev", 65536, 0), candidate("openrouter", 131072, 0)]
        )
        self.assertIn("context_length", conflicts)
        self.assertEqual(resolved, {})


if __name__ == "__main__":
    unittest.main()
