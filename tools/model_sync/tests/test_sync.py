"""Unit tests for the metadata sync helpers (stdlib unittest, no deps)."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model_sync import export_billing, merge  # noqa: E402
from model_sync.normalize import (  # noqa: E402
    capabilities_from_flags,
    is_free_price,
    model_name_from_id,
    normalize_key,
    normalize_modalities,
)
from model_sync.sources import SourceModel  # noqa: E402


class NormalizeTest(unittest.TestCase):
    def test_model_name_from_id(self):
        self.assertEqual(
            model_name_from_id("anthropic/claude-haiku-4-5:free"), "claude-haiku-4-5"
        )
        self.assertEqual(model_name_from_id("gpt-6.1-sol"), "gpt-6.1-sol")

    def test_normalize_key_matches_aliases(self):
        self.assertEqual(
            normalize_key("claude-haiku-4-5-20251001"), normalize_key("anthropic/claude-haiku-4.5")
        )
        self.assertEqual(normalize_key("claude-opus-5-latest"), "claude-opus-5")
        self.assertEqual(normalize_key("gpt-5.6-sol"), "gpt-5-6-sol")

    def test_modalities_map_pdf_to_file(self):
        self.assertEqual(
            normalize_modalities(["text", "image", "pdf", "pdf"]),
            ["text", "image", "file"],
        )

    def test_capabilities_only_keeps_decision_keys(self):
        caps = capabilities_from_flags(
            {"reasoning": True, "tool_call": True, "attachment": True},
            "claude-opus",
        )
        self.assertEqual(caps, ["reasoning", "tools"])
        self.assertEqual(capabilities_from_flags({}, "text-embedding-3"), ["embedding"])
        self.assertEqual(capabilities_from_flags({}, "bge-reranker"), ["rerank"])

    def test_is_free_price(self):
        self.assertTrue(is_free_price({"input": 0, "output": 0}))
        self.assertFalse(is_free_price({"input": 1, "output": 0}))
        self.assertIsNone(is_free_price({}))


def source(model_name, **kwargs):
    payload = {
        "vendor_key": "anthropic",
        "source": "test",
        "source_id": "anthropic/" + model_name,
        "model_name": model_name,
        "vendor_name": "Anthropic",
        "icon": "Claude.Color",
    }
    payload.update(kwargs)
    return SourceModel(**payload)


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.existing = [
            {
                "model_name": "claude-haiku-4-5-20251001",
                "vendor_name": "Anthropic",
                "description": "本地文案",
                "icon": "Claude.Color",
                "name_rule": 0,
                "status": 1,
                "tags": "自定义标签",
                "capabilities": ["reasoning"],
                "input_modalities": ["text"],
                "output_modalities": ["text"],
                "context_length": 200000,
                "max_output_tokens": 0,
                "is_free": False,
                "endpoints": ["anthropic"],
            }
        ]

    def test_excluded_model_is_removed(self):
        records = [{"model_name": "keep"}, {"model_name": "drop"}]
        merge.apply_overrides(records, {"excluded": ["drop"]}, [])
        self.assertEqual([record["model_name"] for record in records], ["keep"])

    def test_refreshes_factual_fields_only(self):
        index, _ = merge.index_incoming(
            [
                source(
                    "claude-haiku-4-5",
                    capabilities=["reasoning", "tools"],
                    input_modalities=["text", "image", "file"],
                    context_length=200000,
                    max_output_tokens=64000,
                )
            ]
        )
        records, changes, added, ambiguous, missing, _tie = merge.merge_metadata(
            self.existing, index
        )
        record = records[0]
        self.assertEqual(record["capabilities"], ["reasoning", "tools"])
        self.assertEqual(record["input_modalities"], ["text", "image", "file"])
        self.assertEqual(record["max_output_tokens"], 64000)
        # local fields survive
        self.assertEqual(record["description"], "本地文案")
        self.assertEqual(record["tags"], "自定义标签")
        self.assertEqual(record["endpoints"], ["anthropic"])
        self.assertEqual(added, [])
        self.assertEqual(ambiguous, [])
        self.assertEqual(missing, [])

    def test_empty_source_values_do_not_wipe_local(self):
        index, _ = merge.index_incoming(
            [source("claude-haiku-4-5", context_length=0, input_modalities=[])]
        )
        records, changes, *_ = merge.merge_metadata(self.existing, index)
        self.assertEqual(records[0]["context_length"], 200000)
        self.assertEqual(records[0]["input_modalities"], ["text"])
        self.assertEqual(changes, [])

    def test_new_models_require_opt_in(self):
        incoming = [source("claude-sonnet-5-new", release_date="2026-05-01")]
        index, _ = merge.index_incoming(incoming)

        records, _, added, *_ = merge.merge_metadata(list(self.existing), index)
        self.assertEqual(added, [])
        self.assertEqual(len(records), 1)

        records, _, added, *_ = merge.merge_metadata(
            list(self.existing), index, allow_new=True, min_release_date="2026-01-01"
        )
        self.assertEqual(added, ["claude-sonnet-5-new"])
        self.assertEqual(records[-1]["tags"], "")
        self.assertEqual(records[-1]["status"], 1)

    def test_max_output_clamped_to_context(self):
        index, _ = merge.index_incoming(
            [source("claude-haiku-4-5", context_length=1000, max_output_tokens=5000)]
        )
        records, *_ = merge.merge_metadata(self.existing, index)
        self.assertEqual(records[0]["max_output_tokens"], 1000)

    def test_price_rows_follow_published_models(self):
        index, _ = merge.index_incoming(
            [
                source(
                    "claude-haiku-4-5",
                    price={"input": 1.0, "output": 5.0, "cache_read": 0.1},
                ),
                source("not-published", price={"input": 9.0, "output": 9.0}),
            ]
        )
        rows = merge.price_records(self.existing, index)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model_name"], "claude-haiku-4-5-20251001")
        self.assertEqual(rows[0]["input"], 1.0)
        self.assertNotIn("cache_write", rows[0])

    def test_official_price_beats_aggregator(self):
        """A reseller price must never replace the vendor list price."""
        index, _ = merge.index_incoming(
            [source("claude-haiku-4-5", price={"input": 0.6, "output": 3.0})]
        )
        official = {
            normalize_key("claude-haiku-4-5-20251001"): {
                "model_name": "claude-haiku-4-5-20251001",
                "vendor_name": "Anthropic",
                "source_kind": "official_doc",
                "source_url": "https://platform.claude.com/docs/en/about-claude/pricing",
                "input": 1.0,
                "output": 5.0,
                "cache_read": 0.1,
                "cache_write": 1.25,
                "cache_write_1h": 2.0,
                "tiers": None,
            }
        }
        rows = merge.price_records(self.existing, index, official)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["price_kind"], "vendor_official")
        self.assertEqual(row["source_kind"], "official_doc")
        self.assertEqual(row["input"], 1.0)
        self.assertEqual(row["output"], 5.0)
        self.assertEqual(row["cache_write_1h"], 2.0)
        self.assertNotIn("tiers", row)  # null values are dropped

    def test_official_price_fills_model_without_aggregator(self):
        """Models the aggregators miss still get a row from the official file."""
        index, _ = merge.index_incoming([])
        official = {
            normalize_key("claude-haiku-4-5-20251001"): {
                "model_name": "claude-haiku-4-5-20251001",
                "input": 1.0,
                "output": 5.0,
            }
        }
        rows = merge.price_records(self.existing, index, official)
        self.assertEqual([row["model_name"] for row in rows], ["claude-haiku-4-5-20251001"])

    def test_aliases_each_get_a_price_row(self):
        """Price lookup is by exact model id, so every published alias needs a row."""
        existing = list(self.existing) + [
            {**self.existing[0], "model_name": "claude-haiku-4.5"}
        ]
        index, _ = merge.index_incoming([])
        official = {
            normalize_key("claude-haiku-4-5-20251001"): {
                "model_name": "claude-haiku-4-5-20251001",
                "input": 1.0,
                "output": 5.0,
            }
        }
        rows = merge.price_records(existing, index, official)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["price_kind"] == "vendor_official" for row in rows))

    def test_load_official_prices_missing_file_is_empty(self):
        self.assertEqual(merge.load_official_prices("/nonexistent/pricing.official.json"), {})

    def test_free_model_without_price_gets_zero_row(self):
        """`:free` models are not billed, so they get an explicit zero row."""
        existing = list(self.existing) + [
            {
                **self.existing[0],
                "model_name": "dots-3-note-preview:free",
                "is_free": True,
            }
        ]
        index, _ = merge.index_incoming([])
        rows = merge.price_records(existing, index, {})
        names = [row["model_name"] for row in rows]
        self.assertIn("dots-3-note-preview:free", names)
        row = next(r for r in rows if r["model_name"] == "dots-3-note-preview:free")
        self.assertEqual(row["price_kind"], "free")
        self.assertEqual(row["source_kind"], "catalog")
        self.assertEqual((row["input"], row["output"], row["cache_read"]), (0.0, 0.0, 0.0))

    def test_official_price_wins_over_free_flag(self):
        """A paid model is never zeroed just because a source lists it as free."""
        index, _ = merge.index_incoming([])
        official = {
            normalize_key("minimax-m3.1-flash:free"): {
                "model_name": "minimax-m3.1-flash:free",
                "input": 0.15,
                "output": 0.6,
            }
        }
        existing = [{**self.existing[0], "model_name": "minimax-m3.1-flash:free", "is_free": True}]
        rows = merge.price_records(existing, index, official)
        self.assertEqual(rows[0]["price_kind"], "vendor_official")
        self.assertEqual(rows[0]["input"], 0.15)

    def test_official_modality_fields_pass_through(self):
        index, _ = merge.index_incoming([])
        official = {
            normalize_key("chatgpt-image-latest"): {
                "model_name": "chatgpt-image-latest",
                "input": 5.0,
                "output": 32.0,
                "output_text": 10.0,
                "output_image": 32.0,
                "input_image": 8.0,
                "cache_read": 1.25,
                "cache_read_image": 2.0,
            }
        }
        existing = [{**self.existing[0], "model_name": "chatgpt-image-latest", "is_free": False}]
        row = merge.price_records(existing, index, official)[0]
        self.assertEqual(row["input_image"], 8.0)
        self.assertEqual(row["cache_read_image"], 2.0)
        self.assertEqual(row["output_image"], 32.0)

    def test_official_meters_pass_through(self):
        """Per-image / per-second meters survive into pricing.json untouched."""
        index, _ = merge.index_incoming([])
        meters = [
            {"dim": "output_image", "price": 0.134, "unit": "image",
             "when": {"resolution": "1K-2K"}},
            {"dim": "output_image", "price": 0.24, "unit": "image",
             "when": {"resolution": "4K"}},
        ]
        official = {
            normalize_key("gemini-3-pro-image"): {
                "model_name": "gemini-3-pro-image",
                "input": 2.0,
                "output": 120.0,
                "meters": meters,
            }
        }
        existing = [{**self.existing[0], "model_name": "gemini-3-pro-image"}]
        row = merge.price_records(existing, index, official)[0]
        self.assertEqual(row["meters"], meters)

    def test_official_row_without_numbers_is_skipped(self):
        """Unpriced official entries (unresolved) must not become price rows."""
        index, _ = merge.index_incoming([])
        official = {
            normalize_key("claude-haiku-4-5-20251001"): {
                "model_name": "claude-haiku-4-5-20251001",
                "input": None,
                "output": None,
                "cache_read": None,
            }
        }
        rows = merge.price_records(self.existing, index, official)
        self.assertEqual(rows, [])

    def test_official_cache_write_12h_pass_through(self):
        index, _ = merge.index_incoming([])
        official = {
            normalize_key("gpt-6-sol"): {
                "model_name": "gpt-6-sol",
                "input": 2.0,
                "output": 10.0,
                "cache_write": 2.5,
                "cache_write_12h": 5.0,
                "tiers": [{
                    "prompt_tokens_at_least": 272000,
                    "input": 4.0, "output": 15.0,
                    "cache_read": 0.4, "cache_write": 5.0,
                    "cache_write_12h": 10.0,
                }],
            }
        }
        existing = [{**self.existing[0], "model_name": "gpt-6-sol"}]
        row = merge.price_records(existing, index, official)[0]
        self.assertEqual(row["cache_write_12h"], 5.0)
        self.assertEqual(row["tiers"][0]["cache_write_12h"], 10.0)

    def test_exact_name_wins_over_source_priority(self):
        """ollama-hosted and official rows share a key; the exact id must win."""
        index, _ = merge.index_incoming(
            [
                source("kimi-k3", source="openrouter", context_length=1048576),
                source("kimi-k3", source="models.dev", context_length=131072),
            ]
        )
        picked = merge.pick_incoming(index["kimi-k3"], "kimi-k3")
        self.assertEqual(picked.context_length, 1048576)

        prefixed = [
            source("claude-haiku-4-5", source="openrouter"),
            source("claude-haiku-4-5-20251001", source="models.dev"),
        ]
        picked = merge.pick_incoming(prefixed, "claude-haiku-4-5-20251001")
        self.assertEqual(picked.model_name, "claude-haiku-4-5-20251001")

    def test_conflicts_are_reported(self):
        index, _ = merge.index_incoming(
            [
                source("gpt-6-sol", source="models.dev", context_length=1050000),
                source("gpt-6-sol", source="openrouter", context_length=131072),
            ]
        )
        conflicts = merge.detect_conflicts(index)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["key"], "gpt-6-sol")
        self.assertEqual(conflicts[0]["field"], "context_length")
        self.assertEqual(
            conflicts[0]["values"],
            {1050000: ["models.dev"], 131072: ["openrouter"]},
        )

    def test_allow_new_allowlist(self):
        index, _ = merge.index_incoming(
            [source("gpt-5-4"), source("gpt-5-5")]
        )
        records, _, added, *_ = merge.merge_metadata(
            [], index, allow_new=True, allowed_new={"gpt-5-5"}
        )
        self.assertEqual(added, ["gpt-5-5"])
        self.assertEqual([r["model_name"] for r in records], ["gpt-5-5"])

    def test_allowlist_overrides_source_slug(self):
        """openrouter reports glm-5-20260211; the site calls it glm-5."""
        index, _ = merge.index_incoming([source("glm-5-20260211", context_length=204800)])
        records, _, added, *_ = merge.merge_metadata(
            [], index, allow_new=True, allowed_new={"glm-5"}
        )
        self.assertEqual(added, ["glm-5"])
        self.assertEqual(records[0]["model_name"], "glm-5")
        self.assertEqual(records[0]["context_length"], 204800)

    def test_alias_can_be_added_even_when_key_is_matched(self):
        """claude-haiku-4-5 and claude-haiku-4-5-20251001 are separate site rows."""
        index, _ = merge.index_incoming([source("claude-haiku-4-5")])
        records, _, added, *_ = merge.merge_metadata(
            list(self.existing), index, allow_new=True, allowed_new={"claude-haiku-4-5"}
        )
        self.assertEqual(added, ["claude-haiku-4-5"])
        self.assertEqual(len(records), 2)

    def test_conflicted_fields_stay_unknown(self):
        """gemini image models disagree on context; max output agrees."""
        index, _ = merge.index_incoming(
            [
                source("gemini-3-pro-image", source="models.dev",
                       context_length=65536, max_output_tokens=32768),
                source("gemini-3-pro-image", source="openrouter",
                       context_length=131072, max_output_tokens=32768),
            ]
        )
        skip = {(c["key"], c["field"]) for c in merge.detect_conflicts(index)}
        records, *_ = merge.merge_metadata(
            [],
            index,
            allow_new=True,
            allowed_new={"gemini-3-pro-image"},
            skip_fields=skip,
        )
        self.assertEqual(records[0]["context_length"], 0)
        self.assertEqual(records[0]["max_output_tokens"], 32768)

    def test_conflicted_field_is_not_overwritten_on_existing(self):
        self.existing[0]["context_length"] = 200000
        index, _ = merge.index_incoming(
            [
                source("claude-haiku-4-5", source="models.dev", context_length=1000),
                source("claude-haiku-4-5", source="openrouter", context_length=2000),
            ]
        )
        skip = {(c["key"], c["field"]) for c in merge.detect_conflicts(index)}
        records, changes, *_ = merge.merge_metadata(
            self.existing, index, skip_fields=skip
        )
        self.assertEqual(records[0]["context_length"], 200000)
        self.assertEqual(
            [change for change in changes if change["field"] == "context_length"], []
        )

    def test_overrides_win_over_every_source(self):
        index, _ = merge.index_incoming([source("gemini-3-pro-image")])
        records, changes, *_ = merge.merge_metadata(
            [], index, allow_new=True, allowed_new={"gemini-3-pro-image"}
        )
        self.assertEqual(records[0]["context_length"], 0)

        overrides = {
            "models": [
                {
                    "model_name": "gemini-3-pro-image",
                    "fields": {"context_length": 131072, "unknown_field": 1},
                    "source": "https://ai.google.dev/gemini-api/docs/pricing",
                }
            ]
        }
        applied, missing = merge.apply_overrides(records, overrides, changes)
        self.assertEqual(applied, 1)
        self.assertEqual(records[0]["context_length"], 131072)
        self.assertNotIn("unknown_field", records[0])
        self.assertEqual(missing, [])
        self.assertEqual(changes[-1]["via"], "override")

    def test_tie_break_source_fills_conflicts(self):
        """OpenRouter limits are what actually gets enforced, so it ties breaks."""
        index, _ = merge.index_incoming(
            [
                source("kimi-k3", source="models.dev", context_length=1048576,
                       max_output_tokens=1048576),
                source("kimi-k3", source="openrouter", context_length=1048576,
                       max_output_tokens=943718),
            ]
        )
        records, _, _, ambiguous, _, tie = merge.merge_metadata(
            [], index, allow_new=True, allowed_new={"kimi-k3"}, tie_break="openrouter"
        )
        self.assertEqual(records[0]["max_output_tokens"], 943718)
        self.assertEqual(ambiguous, [])
        self.assertEqual(tie, [{"model": "kimi-k3", "field": "max_output_tokens",
                                "source": "openrouter"}])

    def test_conflict_without_tie_break_stays_unknown(self):
        index, _ = merge.index_incoming(
            [
                source("kimi-k3", source="models.dev", max_output_tokens=1048576),
                source("kimi-k3", source="openrouter", max_output_tokens=943718),
            ]
        )
        records, *_rest = merge.merge_metadata(
            [], index, allow_new=True, allowed_new={"kimi-k3"}
        )
        self.assertEqual(records[0]["max_output_tokens"], 0)

    def test_override_target_must_exist(self):
        applied, missing = merge.apply_overrides(
            list(self.existing),
            {"models": [{"model_name": "does-not-exist", "fields": {"context_length": 1}}]},
        )
        self.assertEqual(applied, 0)
        self.assertEqual(missing, ["does-not-exist"])


class PricingPublicationTest(unittest.TestCase):
    """公开仓库只放牌价；上游结算价与由它生成的表达式一律不落盘。

    new-api 侧用私有 basis 导出表达式（``export_billing --basis``），
    这里固化两条边界：
      1. 提交的 pricing.json 不得含任何结算痕迹；
      2. 导出时 basis 必须能覆盖牌价并生成正确表达式。
    """

    ROOT = pathlib.Path(__file__).resolve().parents[3]

    def load(self, rel):
        return json.loads((self.ROOT / rel).read_text(encoding="utf-8"))

    def test_committed_pricing_has_no_settlement_data(self):
        pricing = self.load("api/newapi/pricing.json")["data"]
        self.assertTrue(pricing)
        for row in pricing:
            name = row["model_name"]
            self.assertNotIn("billing_basis", row, name)
            self.assertFalse(
                [k for k in row if k.endswith("_cny")], "%s 仍带 *_cny" % name
            )
        self.assertFalse(
            (self.ROOT / "api/newapi/billing_basis.json").exists(),
            "上游结算价文件不能提交到仓库",
        )

    def test_export_uses_private_basis(self):
        prices = {
            "data": [
                {
                    "model_name": "demo-model",
                    "vendor_name": "Vendor",
                    "price_kind": "vendor_official",
                    "currency": "USD",
                    "unit": "per_1m_tokens",
                    "input": 2.0,
                    "output": 10.0,
                }
            ]
        }
        basis = {
            "data": {"demo-model": {"input_cny": 7.0, "output_cny": 21.0, "input": 1.029412, "output": 3.088235}},
            "names": {"demo-model": "demo-model"},
            "meta": {},
        }
        payload = export_billing.build_payload(prices, None, basis)
        self.assertEqual(
            payload["billing_setting.billing_expr"]["demo-model"],
            'tier("standard", p * 1.029412 + c * 3.088235)',
        )

    def test_export_falls_back_to_list_price(self):
        prices = {
            "data": [
                {
                    "model_name": "demo-model",
                    "vendor_name": "Vendor",
                    "price_kind": "vendor_official",
                    "currency": "USD",
                    "unit": "per_1m_tokens",
                    "input": 2.0,
                    "output": 10.0,
                }
            ]
        }
        payload = export_billing.build_payload(prices)
        self.assertEqual(
            payload["billing_setting.billing_expr"]["demo-model"],
            'tier("standard", p * 2 + c * 10)',
        )

    def test_export_emits_basis_only_models(self):
        basis = {
            "data": {"image-only": {"per_image_cny": 0.34, "per_image": 0.05, "meters": [{"dim": "output_image", "price": 0.05, "unit": "image"}]}},
            "names": {"image-only": "image-only"},
            "meta": {},
        }
        payload = export_billing.build_payload({"data": []}, None, basis)
        self.assertEqual(
            payload["billing_setting.billing_expr"]["image-only"],
            'tier("image", fixed(0.05)) * image_count',
        )

    def test_row_without_any_price_source_keeps_shell_only(self):
        previous = [
            {
                "model_name": "kept-model",
                "vendor_name": "Vendor",
                "price_kind": "aggregator_reference",
                "source": "upstream:basis",
                "currency": "USD",
                "unit": "per_1m_tokens",
                "input": 1.0,
                "billing_expr": 'tier("standard", p * 1)',
                "billing_basis": {"input": 1.0},
            }
        ]
        rows = merge.price_records(
            [{"model_name": "kept-model", "vendor_name": "Vendor"}],
            {},
            {},
            previous=previous,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model_name"], "kept-model")
        self.assertNotIn("input", rows[0])
        self.assertNotIn("billing_expr", rows[0])
        self.assertNotIn("billing_basis", rows[0])

    def test_unpriced_model_without_history_is_skipped(self):
        rows = merge.price_records(
            [{"model_name": "brand-new", "vendor_name": "Vendor"}], {}, {}
        )
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
