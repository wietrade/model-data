"""validate.check_metadata 的供应商一致性断言。

背景：vendors.json 是**发布物**，new-api 会 `GET {base}/api/newapi/vendors.json`
写 vendors 表；但它没有任何删除机制（只 Create/Update）。所以一旦把本地运维
遗留的供应商（例如内网的「自建渠道」）写进来，就会永久公开挂在那里、且是空壳。
2026-10-26 真实发生过一次，这里锁住。
"""

import unittest

from tools.model_sync import validate as vd


def _model(name="m1", vendor="OpenAI", **over):
    row = {
        "model_name": name,
        "vendor_name": vendor,
        "description": "d",
        "icon": "i",
        "tags": "t",
        "capabilities": ["chat"],
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "context_length": 128000,
        "max_output_tokens": 8192,
        "lifecycle": "ga",
        "status": 1,
        "name_rule": 0,
    }
    row.update(over)
    return row


class CheckMetadataVendorTest(unittest.TestCase):
    def test_vendor_without_models_is_reported(self):
        report = vd.Report()
        vd.check_metadata(
            [_model()],
            [{"name": "OpenAI"}, {"name": "自建渠道"}],
            report,
        )
        self.assertEqual(report.errors, [])
        self.assertTrue(
            any("自建渠道" in w and "空壳" in w for w in report.warnings),
            report.warnings,
        )

    def test_all_vendors_used_is_clean(self):
        report = vd.Report()
        vd.check_metadata(
            [_model(vendor="OpenAI"), _model(name="m2", vendor="Anthropic")],
            [{"name": "OpenAI"}, {"name": "Anthropic"}],
            report,
        )
        self.assertFalse(any("空壳" in w for w in report.warnings), report.warnings)

    def test_model_vendor_missing_from_vendors_is_error(self):
        report = vd.Report()
        vd.check_metadata([_model(vendor="Ghost")], [{"name": "OpenAI"}], report)
        self.assertTrue(any("Ghost" in e for e in report.errors), report.errors)


if __name__ == "__main__":
    unittest.main()
