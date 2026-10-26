"""汇率只在一处：`reference-data/price/fx.json`。数据行存原币，换算发生在构建期。

背景：2026-10-26 核对时发现同一批数据里同时存在 6.6667 / 6.8182 / 6.677446
三个隐含汇率（basellm 那套也一样）。根因是数据行直接写了换算后的 USD。
这里锁住「行里只准出现原币」这条规矩。
"""

import unittest

from tools.model_sync import merge

FX = {"units_per_usd": {"USD": 1.0, "CNY": 6.677446}}


class ConvertToUsdTest(unittest.TestCase):
    def test_usd_rows_pass_through_untouched(self):
        row = {"currency": "USD", "input": 2.0, "output": 8.0}
        self.assertEqual(merge.convert_to_usd(dict(row), FX), row)

    def test_cny_row_is_converted(self):
        row = {"model_name": "m", "currency": "CNY", "input": 9.0, "output": 27.0}
        out = merge.convert_to_usd(row, FX)
        self.assertEqual(out["currency"], "USD")
        self.assertEqual(out["fx_to_usd"], 6.677446)
        self.assertAlmostEqual(out["input"], 9 / 6.677446, places=5)
        self.assertAlmostEqual(out["output"], 27 / 6.677446, places=5)

    def test_nested_tiers_and_time_windows_are_converted(self):
        """漏掉任何一层都会得到一半 USD 一半原币的脏数据。"""
        row = {
            "model_name": "m",
            "currency": "CNY",
            "input": 1.0,
            "tiers": [{"prompt_tokens_at_least": 200000, "input": 2.0, "output": 4.0}],
            "time_tiers": {"peak": {"input": 3.0, "output": 6.0}, "off_peak_multiplier": 0.5},
            "meters": [{"dim": "output_image", "price": 4.0, "unit": "image"}],
        }
        out = merge.convert_to_usd(row, FX)
        self.assertAlmostEqual(out["tiers"][0]["input"], 2 / 6.677446, places=5)
        self.assertAlmostEqual(out["time_tiers"]["peak"]["output"], 6 / 6.677446, places=5)
        self.assertAlmostEqual(out["meters"][0]["price"], 4 / 6.677446, places=5)

    def test_source_row_is_not_mutated(self):
        row = {"model_name": "m", "currency": "CNY", "input": 1.0, "tiers": [{"input": 2.0}]}
        merge.convert_to_usd(row, FX)
        self.assertEqual(row["currency"], "CNY")
        self.assertEqual(row["input"], 1.0)
        self.assertEqual(row["tiers"][0]["input"], 2.0)

    def test_unknown_currency_fails_loudly(self):
        with self.assertRaises(ValueError):
            merge.convert_to_usd({"model_name": "m", "currency": "JPY", "input": 1.0}, FX)


class FxFileTest(unittest.TestCase):
    def test_repo_fx_file_is_readable(self):
        document = merge.load_fx()
        rates = document["units_per_usd"]
        self.assertEqual(rates["USD"], 1.0)
        self.assertGreater(rates.get("CNY", 0), 5)
        self.assertTrue(document.get("as_of"), "缺 as_of 就无法追溯用的是哪天的汇率")

    def test_missing_file_falls_back_to_usd_only(self):
        document = merge.load_fx("/nonexistent/fx.json")
        self.assertEqual(document["units_per_usd"], {"USD": 1.0})


if __name__ == "__main__":
    unittest.main()
