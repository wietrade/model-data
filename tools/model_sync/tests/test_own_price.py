"""价格分两层：官方价（公开）+ 自己的价（私有，只写差异字段）。

规则：两条记录按**字段**合并——自己的价写了哪个字段就覆盖哪个，没写就继承官方。
两个例外（否则会把价格算飞）：

* 自己的价改成按张（`per_image` / `meters`）时，官方的 token 价与档位整套不适用；
* 只改基础价、没给自己的档位时，不继承官方 `tiers`（官方档位是按官方基础价算的）。

另外固化 new-api 的单位换算：`ModelRatio = 官方输入价($/1M) / 2`。
"""

import unittest

from tools.model_sync import expr
from tools.model_sync.merge import attach_newapi_ratios

OFFICIAL = {
    "model_name": "demo",
    "input": 5.0,
    "output": 25.0,
    "cache_read": 0.5,
    "cache_write": 6.25,
    "tiers": [{"prompt_tokens_at_least": 200000, "input": 10.0, "output": 37.5}],
}


def merged(own):
    return expr.apply_billing_basis({**OFFICIAL, "billing_basis": own})


class FieldLevelOverrideTest(unittest.TestCase):
    def test_unlisted_fields_inherit_official(self):
        row = merged({"input": 2.0})
        self.assertEqual(row["input"], 2.0)     # 覆盖
        self.assertEqual(row["output"], 25.0)   # 继承
        self.assertEqual(row["cache_read"], 0.5)

    def test_all_listed_fields_override(self):
        row = merged({"input": 2.0, "output": 6.0, "cache_read": 0.2})
        self.assertEqual((row["input"], row["output"], row["cache_read"]), (2.0, 6.0, 0.2))

    def test_official_tiers_not_inherited_when_base_price_changes(self):
        """只改基础价却继承官方档位，会在线上下文档按官方原价收，必须丢掉。"""
        self.assertNotIn("tiers", merged({"input": 2.0}))

    def test_own_tiers_are_used(self):
        own_tiers = [{"prompt_tokens_at_least": 200000, "input": 4.0}]
        self.assertEqual(merged({"input": 2.0, "tiers": own_tiers})["tiers"], own_tiers)

    def test_shape_switch_drops_token_prices_and_tiers(self):
        row = merged({"per_image": 0.0117, "meters": [{"dim": "output_image", "price": 0.0117}]})
        self.assertEqual(row["per_image"], 0.0117)
        for field in ("input", "output", "cache_read", "cache_write", "tiers"):
            self.assertNotIn(field, row, field)

    def test_no_own_price_keeps_official_untouched(self):
        self.assertEqual(expr.apply_billing_basis(dict(OFFICIAL)), OFFICIAL)


class NewapiRatioTest(unittest.TestCase):
    """new-api「同步价格」吃的倍率：ratio 1 = $2/1M。"""

    def test_token_ratios(self):
        row = attach_newapi_ratios(OFFICIAL)
        self.assertEqual(row["quota_type"], 0)
        self.assertEqual(row["model_ratio"], 2.5)          # 5.0 / 2
        self.assertEqual(row["completion_ratio"], 5.0)     # 25 / 5
        self.assertEqual(row["cache_ratio"], 0.1)          # 0.5 / 5
        self.assertEqual(row["create_cache_ratio"], 1.25)  # 6.25 / 5

    def test_per_image_becomes_fixed_price(self):
        row = attach_newapi_ratios({"model_name": "img", "per_image": 0.0117})
        self.assertEqual(row["quota_type"], 1)
        self.assertEqual(row["model_price"], 0.0117)
        self.assertNotIn("model_ratio", row)

    def test_stale_ratios_are_recomputed(self):
        row = attach_newapi_ratios({**OFFICIAL, "model_ratio": 99.0})
        self.assertEqual(row["model_ratio"], 2.5)

    def test_unpriced_row_gets_no_ratio_fields(self):
        row = attach_newapi_ratios({"model_name": "x", "price_kind": "unpriced"})
        self.assertEqual(row, {"model_name": "x", "price_kind": "unpriced"})


if __name__ == "__main__":
    unittest.main()
