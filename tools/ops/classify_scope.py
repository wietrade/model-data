#!/usr/bin/env python3
"""给 L1 快照里的每个模型定「核实范围」：必须核 / 可以不核 / 直接忽略。

设计前提（重要）：
  站点只有「模型维度」的数值字段 contextLength / maxOutputTokens。
  **视频、语音、转写、图像这类模型本来就没有上下文窗口**，站点显示 "Not reported"
  属于字段不适用，不是数据缺陷，不能当成「缺数据」去追着核实。

分档（按优先级从高到低判定，命中即止）：

  done      已经有官方核实条目（corrections/）
  legacy    老代模型，不再投入核实成本（corrections/<date>/legacy.json）
  main      主流厂商 ⇒ **无论缺不缺数据，都必须核**
  ignore    非主流厂商 且 缺关键数值 ⇒ 直接忽略
  review    非主流但数值齐全 / 主流以外的小众值缺失 ⇒ 有空再看
  media     图像/视频/语音/转写：没有 token 字段，只核能力与计费口径

「关键数值」按类型区分：
  text / realtime / decision   contextLength + maxOutputTokens
  embedding                    contextLength（输入上限；maxOutputTokens 不适用）
  image / video / speech / transcription   无

用法：
    python -m tools.ops.classify_scope                             # 最新一期，打摘要
    python -m tools.ops.classify_scope --date 20261026             # 指定快照
    python -m tools.ops.classify_scope -o /tmp/scope.json           # 落盘（派生物，默认不进库）
    python -m tools.ops.classify_scope --list ignore                # 列出某一档

目录约定（按快照隔离，一次快照一套）：
    source-data/cheaperinference-<date>.json
    corrections/<date>/{corrections,legacy,routing}.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

RAW = Path("source-data")
CORRECTIONS_ROOT = Path("corrections")

def resolve_date(day: str | None = None) -> str:
    """不指定就用 corrections/ 下最新的日期目录。"""
    if day:
        return day.replace("-", "")
    found = sorted(
        p.name for p in CORRECTIONS_ROOT.iterdir()
        if p.is_dir() and re.fullmatch(r"\d{8}", p.name)
    ) if CORRECTIONS_ROOT.exists() else []
    if not found:
        raise SystemExit("corrections/ 下没有 YYYYMMDD 目录，请用 --date 指定")
    return found[-1]


def paths_for(day: str) -> dict[str, Path]:
    return {
        "snapshot": RAW / ("cheaperinference-%s.json" % day),
        "corrections": CORRECTIONS_ROOT / day / "corrections.json",
        "legacy": CORRECTIONS_ROOT / day / "legacy.json",
        "routing": CORRECTIONS_ROOT / day / "routing.json",
    }

# --------------------------------------------------------------------------
# 厂商识别：顺序敏感，先具体后笼统
# --------------------------------------------------------------------------

VENDOR_RULES: list[tuple[str, str, bool]] = [
    # (厂商, 正则, 是否主流)
    # ---- 海外主流 ----
    ("anthropic", r"^claude-", True),
    ("openai", r"^(gpt-|chatgpt|o1(-|$)|o3(-|$)|o4-|dall-e|whisper|tts-1|text-embedding)", True),
    ("google", r"^(gemini|gemma|imagen|veo|lyria|chirp|tts-gemini|text-multilingual-embedding)", True),
    ("xai", r"^(grok-|xai-stt)", True),
    ("meta", r"^llama-", True),
    ("mistral", r"^(mistral|mixtral|codestral|pixtral|magistral|devstral|ministral|voxtral)", True),
    ("cohere", r"^(command-|embed-v[45]|rerank)", True),
    ("perplexity", r"^(sonar|pplx-|perplexity-)", True),
    ("nvidia", r"^nvidia-nemotron", True),
    # ---- 国产主流 ----
    ("deepseek", r"^deepseek-", True),
    ("alibaba", r"^(qwen|qwq|qvq|tts-qwen|wan-)", True),
    ("moonshot", r"^kimi-", True),
    ("zhipu", r"^(glm-|chatglm|cogview|cogvideo|autoglm)", True),
    ("bytedance", r"^(doubao|seed|ui-tars)", True),
    ("tencent", r"^(hunyuan|hy-mt|hy[0-9])", True),
    ("baidu", r"^ernie", True),
    ("minimax", r"^(minimax|hailuo)", True),
    ("01ai", r"^yi-", True),
    ("stepfun", r"^step-", True),
    ("xiaomi", r"^mimo-", True),
    ("ant", r"^ling-", True),
    ("meituan", r"^longcat", True),
    ("kuaishou", r"^kling-", True),
    ("bfl", r"^flux-", True),
    ("microsoft", r"^(phi-|mai-)", True),
]

# 需要 ctx + max 的类型
TOKEN_BOTH = {"text", "realtime", "decision"}
# 只需要 ctx（输入上限）的类型
TOKEN_CTX = {"embedding"}
# 没有 token 字段概念的类型
NO_TOKEN = {"image", "video", "speech", "transcription"}

TIER_ORDER = ["done", "legacy", "main", "ignore", "review", "media"]

# 站点连「输入/输出模态、支持参数」都没写，说明这条记录只有骨架
CAP_FIELDS = ("detail_Input", "detail_Output", "detail_SupportedParameters")


def strip_prefix(model_id: str) -> tuple[str, str | None]:
    """剥掉 `e2ee-` / `uncensored-` 这类第三方封装前缀，返回 (基名, 前缀)。"""
    for p in ("e2ee-", "uncensored-", "venice-"):
        if model_id.startswith(p):
            return model_id[len(p):], p.rstrip("-")
    return model_id, None


def classify_vendor(model_id: str) -> tuple[str, bool, str | None]:
    base, prefix = strip_prefix(model_id)
    for name, pat, main in VENDOR_RULES:
        if re.search(pat, base) or re.search(pat, model_id):
            return name, main and prefix is None, prefix
    return "other", False, prefix


def gap_of(model: dict) -> list[str]:
    """返回「缺什么」。空列表 = 站点该给的都给了。"""
    t = model.get("type")
    gaps = []
    if t not in NO_TOKEN:
        if model.get("contextLength") is None:
            gaps.append("contextLength")
        if t in TOKEN_BOTH and model.get("maxOutputTokens") is None:
            gaps.append("maxOutputTokens")
    if all(model.get(k) in (None, "Not reported") for k in CAP_FIELDS):
        gaps.append("模态/参数")
    return gaps


def classify(model: dict, covered: set[str], legacy: dict) -> dict:
    mid = model["id"]
    if mid in covered:
        return {"tier": "done", "why": "已有官方核实条目"}
    if mid in legacy:
        return {
            "tier": "legacy",
            "why": legacy[mid].get("reason", "老代"),
            "superseded_by": legacy[mid].get("superseded_by"),
        }
    vendor, is_main, prefix = classify_vendor(mid)
    gaps = gap_of(model)
    base = {"vendor": vendor, "gaps": gaps}
    if prefix:
        base["third_party_prefix"] = prefix

    if is_main:
        base.update(tier="main", why="主流厂商，缺数据也必须核" if gaps else "主流厂商")
    elif gaps:
        base.update(tier="ignore", why=f"非主流（{vendor}）且缺 {'+'.join(gaps)}")
    elif model.get("type") in NO_TOKEN:
        base.update(tier="media", why="图像/视频/语音/转写，无 token 字段，信息齐全")
    else:
        base.update(tier="review", why="非主流但信息齐全")
    return base


def build(snapshot: Path, corrections: Path, legacy_path: Path, routing_path: Path) -> dict:
    models = json.loads(snapshot.read_text(encoding="utf-8"))["models"]
    covered = {c["id"] for c in json.loads(corrections.read_text(encoding="utf-8"))["corrections"]}
    legacy = {}
    if legacy_path.exists():
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))["models"]
    routing = {}
    if routing_path and Path(routing_path).exists():
        routing = json.loads(Path(routing_path).read_text(encoding="utf-8"))["models"]

    out = OrderedDict()
    for m in sorted(models, key=lambda x: x["id"]):
        entry = {**classify(m, covered, legacy), "type": m.get("type")}
        if m["id"] in routing:
            entry["served_as"] = routing[m["id"]].get("served_as")
            entry["retired_at"] = routing[m["id"]].get("retired_at")
        out[m["id"]] = entry
    return {
        "snapshot": str(snapshot),
        "generated_at": date.today().isoformat(),
        "policy": {
            "mainstream_vendors": sorted({n for n, _, ok in VENDOR_RULES if ok}),
            "token_fields_by_type": {
                "ctx+max": sorted(TOKEN_BOTH),
                "ctx_only": sorted(TOKEN_CTX),
                "none": sorted(NO_TOKEN),
            },
            "note": "视频/语音/转写/图像的 Not reported 属于字段不适用，不算缺数据",
        },
        "models": out,
    }


def summarize(plan: dict) -> None:
    tiers = Counter(v["tier"] for v in plan["models"].values())
    total = len(plan["models"])
    print(f"L1 共 {total} 条")
    for t in TIER_ORDER:
        print(f"  {t:<7} {tiers.get(t, 0):>4}")
    todo = tiers.get("main", 0)
    print(f"\n必须核实（main）= {todo}")
    ign = [k for k, v in plan["models"].items() if v["tier"] == "ignore"]
    print(f"忽略（ignore）= {len(ign)}")
    by_vendor = Counter(plan["models"][k]["vendor"] for k in ign)
    print("  按厂商:", by_vendor.most_common())
    by_gap = Counter("+".join(plan["models"][k]["gaps"]) for k in ign)
    print("  按缺口:", by_gap.most_common())
    m_gap = [k for k, v in plan["models"].items() if v["tier"] == "main" and v["gaps"]]
    print(f"\n主流但缺数据（要重点补）= {len(m_gap)}")
    for k in m_gap:
        v = plan["models"][k]
        print(f"  {k:<40} {v['vendor']:<9} 缺 {'+'.join(v['gaps'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="快照日期 YYYYMMDD，默认取 corrections/ 下最新一期")
    ap.add_argument("-o", "--out", type=Path, help="落盘路径（派生物，一般不用存）")
    ap.add_argument("--list", choices=TIER_ORDER, help="列出某一档的模型")
    args = ap.parse_args()

    day = resolve_date(args.date)
    p = paths_for(day)
    missing = [str(v) for v in p.values() if not v.exists()]
    if missing:
        raise SystemExit("缺少文件：%s" % ", ".join(missing))

    plan = build(p["snapshot"], p["corrections"], p["legacy"], p["routing"])
    plan["date"] = day
    if args.list:
        for mid, v in plan["models"].items():
            if v["tier"] == args.list:
                print(f"{mid:<44} {v['vendor']:<10} {v['why']}")
        return
    print(f"快照 {day}")
    summarize(plan)
    if args.out:
        args.out.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
