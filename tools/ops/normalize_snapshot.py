#!/usr/bin/env python3
"""把第三方快照（cheaperinference）洗成一套无冗余、无自相矛盾的事实记录。

原文件里同一件事有三套字段，且会打架，实测（505 条）：

============  ======================================  ======================
冗余/冲突        现象                                    本脚本的处理
============  ======================================  ======================
`context-128k` 126 条同时带 `context-128k` + `context-1m`  只保留 `contextLength` 数字；
/ `context-1m` （是「≥阈值」的累积标签）                    标签丢弃
`detail_ContextWindow` / `detail_MaximumOutput`  与数值字段 0 不一致      只用来校验 / 回填缺失
`vision` / `image-input` / `detail_VisionInput`  21 条 token 说有图、bool             以 `detail_*` 为准，
                                               和原文都说没有                 token 降级为旁证
`reasoning` / token / `detail_Reasoning`         27 条同样过度声明           同上
`detail_Input` / input token                    65 条矛盾（含 5 个 `Not reported`）  以 `detail_Input` 为准；
                                                                         `Not reported` = 未知，不当 false
`free` 字段                                     505 条里只有 1 条为 true   不采用（`:free` 是聚合源命名）
`type` / `kind` / `group`                       三套分类，只有 87 条一致     只保留 `type`，用它算用途
============  ======================================  ======================

用法::

    python -m tools.ops.normalize_snapshot --report          # 只看冗余/冲突统计
    python -m tools.ops.normalize_snapshot -o /tmp/ci-normalized.json"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 不写死快照路径：不传 -i 时由 latest_snapshot() 取 raw/ 下最新一期，
# 否则每次换新快照都要改代码（旧版本曾硬编码 10-23 的 full 快照）。

INPUT_MAP = {"text": "text", "image": "image", "pdf": "file", "file": "file", "audio": "audio", "video": "video"}
OUTPUT_MAP = {"text": "text", "image": "image", "audio": "audio", "video": "video"}
# 只有 detail_* 里没有对应证据的能力才从 token 取
TOKEN_ONLY_CAPS = {
    "web-search": "web_search",
    "implicit-caching": "cache_implicit",
    "explicit-caching": "cache_explicit",
}
PARAM_CAPS = {
    "tools": "tools",
    "tool_choice": "tools",
    "structured_outputs": "structured_output",
    "response_format": "structured_output",
}
_UNKNOWN = {"", "not reported", "n/a"}


# 端点 -> 计费维度（快照只给「按什么收」，单价在 pricing.json / 私有 basis）
BILLING_RULES = (
    (("/v1/images/",), "image"),  # 按张
    (("/v1/videos/",), "video"),  # 按视频（或按视频秒）
    (("/v1/audio/speech",), "audio_character"),  # TTS 按字符
    (("/v1/audio/transcriptions",), "audio_second"),  # ASR 按音频秒
    (("/v1/realtime",), "audio_second"),
    (
        ("/v1/chat", "/v1/responses", "/v1/messages", "/v1/embeddings", "/v1/decisions"),
        "tokens",
    ),
)
BILLING_BY_TYPE = {
    "image": "image",
    "video": "video",
    "speech": "audio_character",
    "transcription": "audio_second",
    "realtime": "audio_second",
    "text": "tokens",
    "embedding": "tokens",
    "decision": "tokens",
}


def billing_dimension(endpoints, kind):
    """按端点判计费维度；端点没报时用 ``type`` 兜底。"""
    joined = " ".join(endpoints)
    for prefixes, dimension in BILLING_RULES:
        if any(prefix in joined for prefix in prefixes):
            return dimension
    return BILLING_BY_TYPE.get(kind)


def _split(value):
    text = (value or "").strip()
    if text.lower() in _UNKNOWN:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


_SCALE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def _number(value):
    """``'1,048,576 tokens'`` / ``'1M'`` / ``'512 tokens'`` -> int。"""
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kKmMbB])?", str(value or "").replace(",", ""))
    if not match:
        return None
    number = float(match.group(1))
    return int(number * _SCALE.get((match.group(2) or "").lower(), 1))


def model_type(record) -> str:
    """用途分类（与快照的 type 同口径），只从模态 + 能力推导。

    ``decision`` / ``realtime`` 推不出来（前者文本进文本出、后者音文本双向），
    需要外部标记；本函数对这两种只在明显线索下才返回。
    """
    ins = set(record.get("input_modalities") or [])
    outs = set(record.get("output_modalities") or [])
    caps = set(record.get("capabilities") or [])
    if "embedding" in caps or "rerank" in caps:
        return "embedding"
    if "audio" in outs and ins >= {"audio"} and "text" in outs:
        return "realtime"
    if outs == {"audio"} and ins == {"text"}:
        return "speech"
    if outs and "audio" not in outs and ins == {"audio"}:
        return "transcription"
    if "video" in outs:
        return "video"
    if "image" in outs:
        return "image"
    return "text"


def normalize_item(item, strict: bool = False) -> dict:
    """一条原始记录 -> 无冗余的事实记录。缺失的维度记进 ``unknown``。

    ``strict=True`` 时**只用站点原文**：原文没报的模态/能力就留空，
    不按 ``type`` 或 ``vision`` 推断（``input_source`` 只会是 ``detail`` 或 ``none``）。
    """
    tokens = set(item.get("capabilities") or [])
    params = set(_split(item.get("detail_SupportedParameters")))
    unknown = []
    kind = (item.get("type") or "text").strip()

    # 输入模态：detail_Input 打底，**vision 任一来源说 Supported 就补 image**
    # （实测 13 条 detail_Input 只写 text、但 detail_VisionInput=Supported——
    #  即「既能输文本也能输截图」，不能判成 text-only）
    inputs = [INPUT_MAP[v] for v in _split(item.get("detail_Input")) if v in INPUT_MAP]
    input_source = "detail" if inputs else ("none" if strict else "type")
    if not inputs:
        # 原文没报 -> unknown 恒记（无论后面是否按 type 补）
        unknown.append("input_modalities")
        if not strict:
            inputs = {"embedding": ["text"], "transcription": ["audio"], "realtime": ["audio", "text"]}.get(
                kind, ["text"]
            )
    vision = bool(item.get("vision")) or item.get("detail_VisionInput") == "Supported"
    if vision and not strict and "image" not in inputs:
        inputs.append("image")
        input_source += "+vision"

    outputs = [OUTPUT_MAP[v] for v in _split(item.get("detail_Output")) if v in OUTPUT_MAP]
    output_source = "detail" if outputs else ("none" if strict else "type")
    if not outputs:
        unknown.append("output_modalities")
        if not strict:
            outputs = {
                "image": ["image"],
                "video": ["video"],
                "speech": ["audio"],
                "realtime": ["audio", "text"],
                "embedding": ["text"],
            }.get(kind, ["text"])

    caps = set()
    if item.get("reasoning") or item.get("detail_Reasoning") == "Supported":
        caps.add("reasoning")
    if params:
        caps |= {cap for key, cap in PARAM_CAPS.items() if key in params}
        capabilities_source = "params"
    elif strict:
        capabilities_source = "none"
        unknown.append("supported_parameters")
    else:
        # 参数表没公布时 token 只作弱证据（实测会过度声明，见文件头）
        if "tool-use" in tokens:
            caps.add("tools")
        if "structured-output" in tokens:
            caps.add("structured_output")
        capabilities_source = "tokens"
        unknown.append("supported_parameters")
    caps |= {cap for key, cap in TOKEN_ONLY_CAPS.items() if key in tokens}
    if kind == "embedding" or any(token.startswith("embedding") for token in tokens):
        caps.add("embedding")

    # 上下文 / 最大输出：**三个字段只留一个数字**。
    # `context-128k` / `context-1m` 是累积阈值标签，与数字重复，直接丢；
    # `detail_*` 与数值字段实测 0 处不一致，只用来回填缺失（以及万一未来冲突时留证）。
    conflicts = []
    context_length = item.get("contextLength") or None
    context_source = "numeric" if context_length else "none"
    detail_context = _number(item.get("detail_ContextWindow"))
    if context_length and detail_context and detail_context != context_length:
        conflicts.append({"field": "context_length", "numeric": context_length, "detail": detail_context})
    elif not context_length and detail_context:
        context_length, context_source = detail_context, "detail"

    max_output = item.get("maxOutputTokens") or None
    max_output_source = "numeric" if max_output else "none"
    detail_max = _number(item.get("detail_MaximumOutput"))
    if max_output and detail_max and detail_max != max_output:
        conflicts.append({"field": "max_output_tokens", "numeric": max_output, "detail": detail_max})
    elif not max_output and detail_max:
        max_output, max_output_source = detail_max, "detail"
    if context_length and max_output and max_output > context_length:
        # 该站实测 19 条「输出上限 > 上下文」，违反我们目录自己的不变式（max ≤ ctx）
        conflicts.append(
            {
                "field": "max_output_tokens",
                "reason": "exceeds_context",
                "max_output_tokens": max_output,
                "context_length": context_length,
            }
        )

    record = {
        "id": item.get("id"),
        "provider": item.get("providerLabel"),
        "type": kind,
        "context_length": context_length or None,
        "max_output_tokens": max_output or None,
        "input_modalities": sorted(set(inputs)),
        "output_modalities": sorted(set(outputs)),
        "capabilities": sorted(caps),
        "image_edit": bool(item.get("imageEdit")),
        "endpoints": [ep for ep in _split(item.get("detail_Endpoints")) if ep.startswith("/")],
        "billing_dimension": billing_dimension(
            [ep for ep in _split(item.get("detail_Endpoints")) if ep.startswith("/")], kind
        ),
        "input_source": input_source,
        "output_source": output_source,
        "context_source": context_source,
        "max_output_source": max_output_source,
        "capabilities_source": capabilities_source,
        "conflicts": conflicts,
        "unknown": unknown,
    }
    if context_length is None:
        record["unknown"].append("context_length")
    if max_output is None:
        record["unknown"].append("max_output_tokens")
    return record


# ------------------------------------------------------------------ 冗余审计


def audit(items):
    """返回「同一事实几套字段」的一致/矛盾统计，供 --report 打印。"""
    stats = {}
    both_tokens = sum(1 for it in items if {"context-128k", "context-1m"} <= set(it.get("capabilities") or []))
    no_token = sum(
        1 for it in items if not ({"context-128k", "context-1m"} & set(it.get("capabilities") or []))
    )
    stats["context_token"] = {"both_128k_and_1m": both_tokens, "no_token": no_token, "total": len(items)}

    def compare(field, num_field):
        bad = [
            (it.get("id"), _number(it.get(field)), it.get(num_field))
            for it in items
            if _number(it.get(field)) is not None and _number(it.get(field)) != it.get(num_field)
        ]
        return {"mismatch": len(bad), "samples": bad[:3]}

    stats["detail_vs_number"] = {
        "context_window": compare("detail_ContextWindow", "contextLength"),
        "max_output": compare("detail_MaximumOutput", "maxOutputTokens"),
    }

    def tri(bool_field, token, detail, truth):
        agree_true = sum(
            1
            for it in items
            if bool(it.get(bool_field)) and token in (it.get("capabilities") or []) and it.get(detail) == truth
        )
        overclaim = sum(
            1
            for it in items
            if not it.get(bool_field) and token in (it.get("capabilities") or []) and it.get(detail) == "Not supported"
        )
        return {"agree_true": agree_true, "token_overclaims": overclaim}

    stats["three_sources"] = {
        "vision": tri("vision", "image-input", "detail_VisionInput", "Supported"),
        "reasoning": tri("reasoning", "reasoning", "detail_Reasoning", "Supported"),
        "image_edit": tri("imageEdit", "image-edit", "detail_ImageEditing", "Supported"),
    }

    overclaim = 0
    for it in items:
        tokens = set(it.get("capabilities") or [])
        src = (it.get("detail_Input") or "").strip().lower()
        if "image-input" in tokens and "image" not in src:
            overclaim += 1
        if "image-input" not in tokens and "image" in src:
            overclaim += 1
    stats["input_token_vs_detail"] = {"mismatch": overclaim}
    stats["free_field_true"] = sum(1 for it in items if it.get("free"))
    return stats


def render(stats):
    lines = ["# 快照冗余审计", ""]
    c = stats["context_token"]
    lines.append(
        f"- `context-128k` / `context-1m`：{c['both_128k_and_1m']}/{c['total']} 条**同时带两个**"
        f"（是「≥阈值」累积标签），{c['no_token']} 条一个都没带 → 与 `contextLength` 重复，丢弃"
    )
    d = stats["detail_vs_number"]
    lines.append(f"- `detail_ContextWindow` vs `contextLength`：{d['context_window']['mismatch']} 处不一致")
    lines.append(f"- `detail_MaximumOutput` vs `maxOutputTokens`：{d['max_output']['mismatch']} 处不一致（纯冗余）")
    t = stats["three_sources"]
    lines.append(
        f"- `vision`：三源一致 {t['vision']['agree_true']} 条，**token 过度声明 {t['vision']['token_overclaims']} 条**"
    )
    lines.append(
        f"- `reasoning`：三源一致 {t['reasoning']['agree_true']} 条，**token 过度声明 {t['reasoning']['token_overclaims']} 条**"
    )
    lines.append(f"- `imageEdit`：三源一致 {t['image_edit']['agree_true']} 条，过度声明 {t['image_edit']['token_overclaims']} 条")
    lines.append(f"- `detail_Input` vs 输入 token：{stats['input_token_vs_detail']['mismatch']} 处矛盾")
    lines.append(f"- `free` 字段为 true 的条目：{stats['free_field_true']} 个（`:free` 是聚合源命名，不采信）")
    return "\n".join(lines)


def latest_snapshot() -> Path:
    """raw/ 下最新的 cheaperinference-<YYYYMMDD>.json（排除 .verified 派生物）。"""
    raw = ROOT / "raw"
    found = sorted(
        p for p in raw.glob("cheaperinference-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].json")
    ) if raw.exists() else []
    if not found:
        raise SystemExit("raw/ 下找不到 cheaperinference-<YYYYMMDD>.json，请用 -i 指定")
    return found[-1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-i", "--input", default=None, help="默认取 raw/ 下最新一期")
    parser.add_argument("-o", "--out", help="输出规范化 JSON")
    parser.add_argument("--report", action="store_true", help="打印冗余/冲突统计")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="只用站点原文：原文没报的模态/能力留空，不按 type/vision 推",
    )
    parser.add_argument("--limit", type=int, help="只处理前 N 条（调试用）")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.input or latest_snapshot()).read_text(encoding="utf-8"))
    items = payload["models"]
    if args.limit:
        items = items[: args.limit]

    if args.report:
        print(render(audit(items)))
    if args.out:
        normalized = [normalize_item(it, strict=args.strict) for it in items]
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "source": payload.get("source"),
                    "fetched_at": payload.get("fetched_at"),
                    "note": "由 tools/ops/normalize_snapshot.py 归一化：去 context-* 标签、token 降级为旁证、detail_* 为准",
                    "count": len(normalized),
                    "models": normalized,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print("wrote %s（%d 条）" % (out, len(normalized)))
    if not args.out and not args.report:
        parser.error("要么 --report，要么 -o")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
