#!/usr/bin/env python3
"""清洗第三方快照（cheaperinference）——**只做数据质量，不引入我们自己的词表**。

原则：保持站点自己的字段名与取值，只做三件事：

1. **去冗余**：`context-128k` / `context-1m` 与 `contextLength` 表达同一件事（126 条同时带两个），丢弃；
   `kind` / `group` 与 `type` 相同时丢弃（不同的保留在 `type_aliases`）。
2. **去掉自相矛盾的值**：`capabilities` 里的 token 与站点自己的 `detail_*` / 布尔字段冲突时，
   以 `detail_*` 为准，被删掉的 token 记进 `removed[]` 并写原因。
3. **如实标注缺口与冲突**：`missing[]` 用站点自己的字段名；`conflicts[]` 记录值之间打架的地方。

不做的事：不把 `pdf` 改成 `file`、不把 `tool-use` 改成 `tools`、不加计费维度、不推 `type` 之外的分类——
这些都只属于「和我们目录对接」的适配器（`normalize_snapshot.py`）。

用法::

    python -m tools.ops.clean_snapshot -o raw/cheaperinference-clean.json
    python -m tools.ops.clean_snapshot --report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IN = ROOT / "raw" / "cheaperinference-20261023-full.json"
CONTEXT_TOKENS = {"context-128k", "context-1m"}
# 站点 token -> 它在 detail_Input 里对应的词，用来判「token 说的输入类型原文里到底有没有」
INPUT_TOKEN_WORDS = {
    "image-input": {"image"},
    "file-input": {"pdf", "file"},
    "audio-input": {"audio"},
    "video-input": {"video"},
}
_UNKNOWN = {"", "not reported", "n/a", "none"}
_SCALE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def _split(value):
    text = str(value or "").strip()
    if text.lower() in _UNKNOWN:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _number(value):
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kKmMbB])?", str(value or "").replace(",", ""))
    if not match:
        return None
    return int(float(match.group(1)) * _SCALE.get((match.group(2) or "").lower(), 1))


def clean_item(item) -> dict:
    """一条原始记录 -> 去掉冗余/矛盾后的记录（字段名与取值保持站点原样）。"""
    missing = []
    removed = []
    conflicts = []

    # ---- 上下文：三个字段只留一个数字 ----
    context_length = item.get("contextLength") or None
    context_source = "contextLength" if context_length else "none"
    detail_context = _number(item.get("detail_ContextWindow"))
    if not context_length and detail_context:
        context_length, context_source = detail_context, "detail_ContextWindow"
    if context_length is None:
        missing.append("contextLength")
    elif detail_context and detail_context != context_length:
        conflicts.append(
            {"field": "contextLength", "value": context_length, "detail_ContextWindow": detail_context}
        )

    # ---- 最大输出：同样只留一个 ----
    max_output = item.get("maxOutputTokens") or None
    max_output_source = "maxOutputTokens" if max_output else "none"
    detail_max = _number(item.get("detail_MaximumOutput"))
    if not max_output and detail_max:
        max_output, max_output_source = detail_max, "detail_MaximumOutput"
    if max_output is None:
        missing.append("maxOutputTokens")
    elif detail_max and detail_max != max_output:
        conflicts.append(
            {"field": "maxOutputTokens", "value": max_output, "detail_MaximumOutput": detail_max}
        )
    if context_length and max_output and max_output > context_length:
        conflicts.append(
            {
                "field": "maxOutputTokens",
                "reason": "greater_than_contextWindow",
                "maxOutputTokens": max_output,
                "contextLength": context_length,
            }
        )

    # ---- 模态：保持站点词表（text/image/pdf/audio/video） ----
    inputs = _split(item.get("detail_Input"))
    outputs = _split(item.get("detail_Output"))
    if not inputs:
        missing.append("detail_Input")
    if not outputs:
        missing.append("detail_Output")

    # ---- capabilities：保留原 token，只去冗余与自相矛盾 ----
    raw_tokens = list(item.get("capabilities") or [])
    capabilities = []
    for token in raw_tokens:
        if token in CONTEXT_TOKENS:
            removed.append({"value": token, "reason": "duplicate_of_contextLength"})
            continue
        if token == "image-input" and not (
            item.get("vision") or item.get("detail_VisionInput") == "Supported"
        ) and item.get("detail_VisionInput") == "Not supported":
            # 只有「vision=false」且「原文明确 Not supported」两个证据都反对时才删
            removed.append({"value": token, "reason": "detail_VisionInput=Not supported"})
            conflicts.append(
                {
                    "field": "capabilities",
                    "value": token,
                    "reason": "contradicts_detail_VisionInput",
                    "detail_VisionInput": item.get("detail_VisionInput"),
                    "vision": bool(item.get("vision")),
                }
            )
            continue
        if token == "reasoning" and not (
            item.get("reasoning") or item.get("detail_Reasoning") == "Supported"
        ) and item.get("detail_Reasoning") == "Not supported":
            removed.append({"value": token, "reason": "detail_Reasoning=Not supported"})
            conflicts.append(
                {
                    "field": "capabilities",
                    "value": token,
                    "reason": "contradicts_detail_Reasoning",
                    "detail_Reasoning": item.get("detail_Reasoning"),
                }
            )
            continue
        if token in INPUT_TOKEN_WORDS and inputs:
            if not (INPUT_TOKEN_WORDS[token] & {word.lower() for word in inputs}):
                # detail_Input 可能漏写（多模态模型只写 text 的很多），所以**不删**，
                # 只记一条冲突——证据不足时不动原值。
                conflicts.append(
                    {
                        "field": "capabilities",
                        "value": token,
                        "reason": "not_listed_in_detail_Input",
                        "detail_Input": item.get("detail_Input"),
                    }
                )
        capabilities.append(token)

    record = {
        "id": item.get("id"),
        "label": item.get("label"),
        "provider": item.get("providerLabel"),
        "type": item.get("type"),
        "context_length": context_length,
        "context_source": context_source,
        "max_output_tokens": max_output,
        "max_output_source": max_output_source,
        "input": inputs,
        "output": outputs,
        "capabilities": capabilities,
        "image_edit": bool(item.get("imageEdit")),
        "endpoints": [ep for ep in _split(item.get("detail_Endpoints")) if ep.startswith("/")],
        "missing": missing,
        "removed": removed,
        "conflicts": conflicts,
    }
    aliases = {k: item.get(k) for k in ("kind", "group") if item.get(k) and item.get(k) != item.get("type")}
    if aliases:
        record["type_aliases"] = aliases
    return record


def report(items):
    rows = [clean_item(it) for it in items]
    total = len(rows)
    lines = [
        "# 清洗结果（站点原样，不含我们的词表）",
        "",
        f"- 记录数：{total}",
        f"- `context-128k/1m` 被删除：{sum(1 for r in rows if any(x['value'].startswith('context-') for x in r['removed']))} 条",
        f"- 自相矛盾的能力 token 被删除：{sum(1 for r in rows if any(not x['value'].startswith('context-') for x in r['removed']))} 条",
        f"- 有 `conflicts`：{sum(1 for r in rows if r['conflicts'])} 条",
        f"- 有 `type_aliases`（kind/group 与 type 不同）：{sum(1 for r in rows if r.get('type_aliases'))} 条",
        f"- 字段完整（`missing` 为空）：{sum(1 for r in rows if not r['missing'])} 条",
        "",
    ]
    for field, count in Counter(f for r in rows for f in r["missing"]).most_common():
        lines.append(f"- 缺 `{field}`：{count} 条")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-i", "--input", default=str(DEFAULT_IN))
    parser.add_argument("-o", "--out", help="输出清洗后的 JSON")
    parser.add_argument("--report", action="store_true", help="打印清洗统计")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    items = payload["models"]

    if args.report:
        print(report(items))
    if args.out:
        cleaned = [clean_item(it) for it in items]
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "source": payload.get("source"),
                    "fetched_at": payload.get("fetched_at"),
                    "note": "站点原样清洗：去 context-* 冗余、删自相矛盾的 token、标缺失与冲突；不含我们的词表",
                    "count": len(cleaned),
                    "models": cleaned,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print("wrote %s（%d 条）" % (out, len(cleaned)))
    if not args.out and not args.report:
        parser.error("要么 --report，要么 -o")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
