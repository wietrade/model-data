"""渠道别名：官方没有、上游在卖的那几个 id。

背景：`gpt-image-2.5` / `gpt-image-medium` 不在 OpenAI 官方模型列表里
（https://developers.openai.com/api/docs/models/all），但上游渠道按「组」售卖、
客户也可能在调用。所以目录里不建条目，改用别名借官方模型的计费表达式。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.model_sync import export_billing as eb  # noqa: E402
from tools.model_sync import validate as vd  # noqa: E402


class AliasFileTest(unittest.TestCase):
    def test_repo_alias_file_loads(self):
        aliases = eb.load_aliases()
        self.assertTrue(aliases, "reference-data/metadata/aliases.json 应存在且非空")
        for alias, target in aliases.items():
            self.assertNotEqual(alias, target)

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(eb.load_aliases("/nonexistent/aliases.json"), {})

    def test_alias_targets_exist_in_catalog(self):
        models = json.loads((ROOT / "api" / "newapi" / "models.json").read_text(encoding="utf-8"))["data"]
        names = {m["model_name"] for m in models}
        for alias, target in eb.load_aliases().items():
            self.assertIn(target, names, f"{alias} 指向的 {target} 不在目录里")
            self.assertNotIn(alias, names, f"{alias} 不应该同时是目录条目")

    def test_validate_reports_dangling_target(self):
        report = vd.Report()
        real = json.loads

        def fake_loads(text, *a, **kw):
            return {"aliases": {"ghost": "not-a-model"}}

        vd.json.loads = fake_loads
        try:
            vd.check_aliases([{"model_name": "gpt-image-2"}], report)
        finally:
            vd.json.loads = real
        self.assertTrue(any("not-a-model" in e for e in report.errors))


class AliasExpressionTest(unittest.TestCase):
    def test_alias_reuses_source_expression(self):
        prices = {"data": [
            {"model_name": "official-a", "price_kind": "vendor_official",
             "currency": "USD", "unit": "per_1m_tokens", "input": 2.0, "output": 4.0},
        ]}
        payload = eb.build_payload(prices, {"upstream-alias": "official-a"}, None)
        exprs = payload["billing_setting.billing_expr"]
        self.assertEqual(exprs["upstream-alias"], exprs["official-a"])
        modes = payload["billing_setting.billing_mode"]
        self.assertEqual(modes["upstream-alias"], "tiered_expr")

    def test_alias_without_source_raises(self):
        prices = {"data": [
            {"model_name": "official-a", "price_kind": "vendor_official",
             "currency": "USD", "unit": "per_1m_tokens", "input": 2.0, "output": 4.0},
        ]}
        with self.assertRaises(SystemExit):
            eb.build_payload(prices, {"upstream-alias": "nope"}, None)


if __name__ == "__main__":
    unittest.main()
