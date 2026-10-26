"""抓取器拼官方 URL 时的模型名退化规则。

背景：`page_url()` 是拿**我们的模型名**去拼厂商文档地址的，而我们的命名里混了
官方不存在的东西。直接拼会 404 —— 但那**不等于「官方没有这个模型」**。
2026-10-26 那次抓取 39 个模型里有 9 个 404，其中 5 个是命名导致、退化后拿到
正确页面（还由此纠出 1 处真错：gemini-3.8-flash-tiered 输出上限）。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.ops.harvest_official import name_variants, page_url  # noqa: E402


class NameVariantsTest(unittest.TestCase):
    def test_date_snapshot_is_stripped(self):
        """Anthropic 的日期快照 id，官方 slug 是不带日期的。"""
        self.assertEqual(
            name_variants("claude-haiku-4-5-20251001"),
            ["claude-haiku-4-5-20251001", "claude-haiku-4-5"],
        )
        self.assertEqual(
            name_variants("gpt-image-2.5-sunburst-2026-09-08"),
            ["gpt-image-2.5-sunburst-2026-09-08", "gpt-image-2.5-sunburst"],
        )

    def test_free_suffix_is_stripped(self):
        self.assertEqual(
            name_variants("gemma-4-26b-a4b-it:free"),
            ["gemma-4-26b-a4b-it:free", "gemma-4-26b-a4b-it"],
        )

    def test_platform_tiered_suffix_is_stripped(self):
        self.assertEqual(
            name_variants("gemini-3.8-flash-tiered"),
            ["gemini-3.8-flash-tiered", "gemini-3.8-flash"],
        )

    def test_preview_is_never_degraded(self):
        """preview 是另一个 SKU，借用非 preview 页会把数值污染进目录。"""
        self.assertEqual(name_variants("gemini-3-pro-image-preview"), ["gemini-3-pro-image-preview"])

    def test_plain_name_has_single_candidate(self):
        self.assertEqual(name_variants("claude-opus-5"), ["claude-opus-5"])

    def test_suffixes_combine(self):
        """`-tiered` 与日期同时出现时逐级去掉，且不重复。"""
        got = name_variants("gemini-3.8-flash-tiered-20260908")
        self.assertEqual(got[0], "gemini-3.8-flash-tiered-20260908")
        self.assertIn("gemini-3.8-flash", got)
        self.assertEqual(len(got), len(set(got)))


class PageUrlTest(unittest.TestCase):
    def test_anthropic_slug_rule(self):
        self.assertEqual(
            page_url("Anthropic", "claude-opus-4.5"),
            "https://platform.claude.com/docs/en/models/opus-4-5/overview.md",
        )

    def test_google_and_openai(self):
        self.assertTrue(page_url("Google", "gemini-3.8-flash").startswith("https://ai.google.dev/"))
        self.assertTrue(page_url("OpenAI", "gpt-5.5").endswith("/gpt-5.5.md"))

    def test_unknown_vendor_returns_none(self):
        self.assertIsNone(page_url("SomeVendor", "whatever"))


if __name__ == "__main__":
    unittest.main()


class FetcherCacheTest(unittest.TestCase):
    """瞬时网络错误不能被当成结论缓存下来。"""

    def test_transient_error_is_not_cached(self):
        import tempfile
        from pathlib import Path

        from tools.ops.harvest_official import Fetcher

        with tempfile.TemporaryDirectory() as tmp:
            fetcher = Fetcher(Path(tmp), refresh=True, retries=1)
            # 不存在的本地文件 → urllib 立刻抛错，走 ERR 分支
            status, _ = fetcher.get("file:///nonexistent-for-test/model.md")
            self.assertEqual(status, "ERR")
            self.assertEqual(list(Path(tmp).iterdir()), [], "ERR 不应写缓存文件")

    def test_http_status_is_cached(self):
        import tempfile
        from pathlib import Path

        from tools.ops.harvest_official import Fetcher

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "page.md"
            target.write_text("hello", encoding="utf-8")
            cache = Path(tmp) / "cache"
            fetcher = Fetcher(cache, refresh=True, retries=1)
            status, body = fetcher.get(target.as_uri())
            self.assertEqual(status, "200")
            self.assertEqual(body, "hello")
            self.assertEqual(len(list(cache.iterdir())), 1, "200 应写缓存")
