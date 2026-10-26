"""核实层应用器的回归测试：只改结构化字段、必须带出处、按置信度分级。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.ops import apply_corrections as ac  # noqa: E402


def record(**overrides):
    base = {
        "id": "m-1",
        "providerLabel": "Acme",
        "type": "text",
        "group": "text",
        "vision": False,
        "reasoning": False,
        "contextLength": 128000,
        "maxOutputTokens": 32768,
        "imageEdit": False,
        "capabilities": ["tool-use"],
        "detail_Input": "Not reported",
        "detail_ContextWindow": "128,000 tokens",
    }
    base.update(overrides)
    return base


def snapshot(*records):
    return {"models": list(records)}


def correction(**overrides):
    base = {
        "id": "m-1",
        "field": "contextLength",
        "value": 1000000,
        "source_url": "https://example.com/doc",
        "quote": "1M token context",
        "confidence": "high",
    }
    base.update(overrides)
    return base


class ValidateTest(unittest.TestCase):
    def test_detail_field_is_rejected(self):
        errors, _ = ac.validate([correction(field="detail_Input", value="text")], {"m-1": record()})
        self.assertTrue(any("detail_" in e or "允许列表" in e for e in errors))

    def test_missing_source_url_is_rejected(self):
        errors, _ = ac.validate([correction(source_url="")], {"m-1": record()})
        self.assertTrue(any("source_url" in e for e in errors))

    def test_unknown_model_is_rejected(self):
        errors, _ = ac.validate([correction(id="nope")], {"m-1": record()})
        self.assertTrue(any("没有这个模型" in e for e in errors))

    def test_unknown_capability_is_warned_not_fatal(self):
        errors, warnings = ac.validate(
            [correction(field=None, add_capabilities=["vision"])], {"m-1": record()}
        )
        self.assertEqual(errors, [])
        self.assertTrue(warnings)


class ApplyTest(unittest.TestCase):
    def test_high_confidence_applied(self):
        data = snapshot(record())
        changes, skipped, _ = ac.apply(data, [correction()])
        self.assertEqual(data["models"][0]["contextLength"], 1000000)
        self.assertEqual(len(changes), 1)
        self.assertEqual(skipped, [])

    def test_medium_skipped_by_default(self):
        data = snapshot(record())
        changes, skipped, _ = ac.apply(data, [correction(confidence="medium")])
        self.assertEqual(data["models"][0]["contextLength"], 128000)
        self.assertEqual(len(changes), 0)
        self.assertEqual(len(skipped), 1)

    def test_medium_applied_when_allowed(self):
        data = snapshot(record())
        ac.apply(data, [correction(confidence="medium")], min_confidence="medium")
        self.assertEqual(data["models"][0]["contextLength"], 1000000)

    def test_capabilities_added_and_sorted(self):
        data = snapshot(record(capabilities=["tool-use"]))
        ac.apply(data, [correction(field=None, add_capabilities=["image-input"])])
        self.assertEqual(data["models"][0]["capabilities"], ["image-input", "tool-use"])

    def test_capabilities_removed(self):
        data = snapshot(record(capabilities=["video-input", "tool-use"]))
        ac.apply(data, [correction(field=None, remove_capabilities=["video-input"])])
        self.assertEqual(data["models"][0]["capabilities"], ["tool-use"])

    def test_detail_fields_are_untouched(self):
        data = snapshot(record())
        before = {k: v for k, v in data["models"][0].items() if k.startswith("detail_")}
        ac.apply(data, [correction()])
        after = {k: v for k, v in data["models"][0].items() if k.startswith("detail_")}
        self.assertEqual(before, after)


class InvariantTest(unittest.TestCase):
    def test_remaining_violation_is_reported(self):
        before = snapshot(record(contextLength=1000, maxOutputTokens=2000))
        after = snapshot(record(contextLength=1000, maxOutputTokens=2000))
        moved, violations = ac.check_invariants(before, after)
        self.assertEqual(moved, [])
        self.assertTrue(violations)

    def test_detail_change_is_detected(self):
        before = snapshot(record())
        after = snapshot(record(detail_Input="text"))
        moved, _ = ac.check_invariants(before, after)
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0][1], "detail_Input")

    def test_non_integer_token_field_is_flagged(self):
        before = snapshot(record())
        after = snapshot(record(maxOutputTokens="32768"))
        _, violations = ac.check_invariants(before, after)
        self.assertTrue(any("非整数" in str(v[1]) for v in violations))


if __name__ == "__main__":
    unittest.main()
