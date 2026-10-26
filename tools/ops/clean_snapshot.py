#!/usr/bin/env python3
"""按原始快照结构清洗，只保留一组事实。

除下面三类值改动外，**键名与顺序一律沿用原文件**：

1. `capabilities` 去掉与 `contextLength` 重复的 `context-128k` / `context-1m`；
2. `capabilities` 去掉被**两个字段同时否定**的 token（如 `image-input` 而 `vision=false`
   且 `detail_VisionInput = Not supported`）；
3. `contextLength` / `maxOutputTokens` 为空时，从对应的 `detail_*` 文本回填。

**合并重复字段**：`detail_ContextWindow` / `detail_MaximumOutput` / `detail_Type` /
`detail_Reasoning` / `detail_VisionInput` / `detail_ImageEditing` 只是对应字段的原文写法，
`label` 只是 `id` 的副本（实测两套写法 0 处不一致），回填完成后整键删除。

**值类型归一**：`detail_VideoInput` / `detail_Streaming` 是布尔语义，原文的
`Supported` / `Not supported` 换成 `true` / `false`；`null`（原文没报）保持 `null`，不当作 false。

其他值一律原样保留：`detail_Input` 漏写某个模态、`maxOutputTokens > contextLength`
这类「有争议但不该擅自改」的情况，只在 `--report` 里统计，不写进文件。

用法::

    python -m tools.ops.clean_snapshot -o raw/cheaperinference-clean.json
    python -m tools.ops.clean_snapshot --report
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IN = ROOT / "raw" / "cheaperinference-20261023-full.json"
CONTEXT_TOKENS = {"context-128k", "context-1m"}
# 原文写法 -> 对应字段：同一个事实的两套写法，只保留后者，前者整键删除
MERGED_DUPLICATES = (
    ("detail_ContextWindow", "contextLength"),
    ("detail_MaximumOutput", "maxOutputTokens"),
    ("detail_Type", "type"),
    ("detail_Reasoning", "reasoning"),
    ("detail_VisionInput", "vision"),
    ("detail_ImageEditing", "imageEdit"),
    ("label", "id"),
)
# 原文里表示「没报」的占位值：删掉不丢信息
PLACEHOLDERS = {None, "", "Not reported"}
# 这三个字段本身就是布尔语义，把原文的字符串换成 JSON 原生 bool
BOOL_DETAILS = ("detail_VideoInput", "detail_Streaming")
BOOL_VALUES = {"Supported": True, "Not supported": False}
_SCALE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def _number(value):
    """``'128,000 tokens'`` / ``'1M'`` -> int；``Not reported`` -> None。"""
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kKmMbB])?", str(value or "").replace(",", ""))
    if not match:
        return None
    return int(float(match.group(1)) * _SCALE.get((match.group(2) or "").lower(), 1))


def clean_item(item):
    """返回 ``(清洗后的记录, 改了什么)``；记录的键与顺序与原记录一致。"""
    out = copy.deepcopy(item)
    changes = []

    tokens = list(out.get("capabilities") or [])
    kept = []
    for token in tokens:
        if token in CONTEXT_TOKENS:
            changes.append({"field": "capabilities", "value": token, "reason": "duplicate_of_contextLength"})
            continue
        if token == "image-input" and not (
            out.get("vision") or out.get("detail_VisionInput") == "Supported"
        ) and out.get("detail_VisionInput") == "Not supported":
            changes.append(
                {"field": "capabilities", "value": token, "reason": "vision=false 且原文 Not supported"}
            )
            continue
        if token == "reasoning" and not (
            out.get("reasoning") or out.get("detail_Reasoning") == "Supported"
        ) and out.get("detail_Reasoning") == "Not supported":
            changes.append(
                {"field": "capabilities", "value": token, "reason": "reasoning=false 且原文 Not supported"}
            )
            continue
        kept.append(token)
    if kept != tokens:
        out["capabilities"] = kept

    if not out.get("contextLength"):
        filled = _number(out.get("detail_ContextWindow"))
        if filled:
            out["contextLength"] = filled
            changes.append({"field": "contextLength", "value": filled, "reason": "从 detail_ContextWindow 回填"})

    if not out.get("maxOutputTokens"):
        filled = _number(out.get("detail_MaximumOutput"))
        if filled:
            out["maxOutputTokens"] = filled
            changes.append(
                {"field": "maxOutputTokens", "value": filled, "reason": "从 detail_MaximumOutput 回填"}
            )

    # 合并：原文写法与目标字段是同一个事实，回填完成后整键删除
    for detail_key, target_key in MERGED_DUPLICATES:
        if detail_key not in out:
            continue
        raw = out.get(detail_key)
        if raw not in PLACEHOLDERS and out.get(target_key) in PLACEHOLDERS:
            continue  # 目标字段没值、原文有值：保留原文，别丢信息
        changes.append(
            {"field": detail_key, "value": out.pop(detail_key), "reason": "merged_into_%s" % target_key}
        )

    return out, changes


def clean_bool_details(item, changes):
    """把 ``Supported`` / ``Not supported`` 换成 ``true`` / ``false``（原地修改）。

    只对布尔语义字段做：同一字段里不能既有 ``false`` 又有 ``"Supported"``。
    ``null``（原文没报）保持原样，不当作 false。
    """
    for key in BOOL_DETAILS:
        value = item.get(key)
        if value in BOOL_VALUES:
            item[key] = BOOL_VALUES[value]
            lowered = str(BOOL_VALUES[value]).lower()
            changes.append({"field": key, "value": BOOL_VALUES[value], "reason": "%s -> %s" % (value, lowered)})
    return item


def audit(items):
    """只统计、不落盘：值之间的遗留矛盾。"""
    stats = Counter()
    for item in items:
        ctx, out = item.get("contextLength"), item.get("maxOutputTokens")
        if ctx and out and out > ctx:
            stats["maxOutputTokens > contextLength"] += 1
        tokens = set(item.get("capabilities") or [])
        detail_in = (item.get("detail_Input") or "").lower()
        if "image-input" in tokens and "image" not in detail_in and item.get("vision"):
            stats["capabilities 有 image-input，detail_Input 未列（但视觉支持）"] += 1
        if "video-input" in tokens and "video" not in detail_in:
            stats["capabilities 有 video-input，detail_Input 未列"] += 1
        if item.get("kind") and item.get("type") and item["kind"] != item["type"]:
            stats["kind 与 type 不同"] += 1
        if item.get("group") and item.get("type") and item["group"] != item["type"]:
            stats["group 与 type 不同"] += 1
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-i", "--input", default=str(DEFAULT_IN))
    parser.add_argument("-o", "--out", help="输出路径（结构与输入完全一致）")
    parser.add_argument("--report", action="store_true", help="打印清洗统计")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    cleaned, all_changes = [], []
    for item in payload["models"]:
        record, changes = clean_item(item)
        clean_bool_details(record, changes)
        cleaned.append(record)
        all_changes.extend(changes)

    if args.report:
        by_reason = Counter(c["reason"] for c in all_changes)
        before = len(payload["models"][0])
        after = len(cleaned[0])
        print("# 清洗统计（每条键数 %d -> %d，少掉 %d 个已合并的重复字段）" % (before, after, before - after))
        print(f"- 记录数：{len(cleaned)}")
        for reason, count in by_reason.most_common():
            print(f"- {reason}：{count} 处")
        print("\n# 遗留矛盾（未改动，仅提示）")
        for text, count in audit(cleaned).most_common():
            print(f"- {text}：{count} 条")

    if args.out:
        new_payload = copy.deepcopy(payload)
        new_payload["models"] = cleaned
        note = str(new_payload.get("note") or "")
        summary = (
            "2026-10-26 清洗：去 context-* 冗余 token、删自相矛盾 token、"
            "contextLength/maxOutputTokens 空则从 detail_* 回填；"
            "detail_ContextWindow/detail_MaximumOutput/detail_Type/detail_Reasoning/"
            "detail_VisionInput/detail_ImageEditing 与对应字段重复（label 与 id 完全相同），"
            "已合并删除；detail_VideoInput/detail_Streaming 的 Supported/Not supported "
            "已转成 true/false（null 保留为未知）。"
        )
        new_payload["note"] = (note + " " + summary).strip() if note else summary
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print("wrote %s（%d 条）" % (out, len(cleaned)))
    if not args.out and not args.report:
        parser.error("要么 --report，要么 -o")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
