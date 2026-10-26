#!/usr/bin/env python3
"""标出「老/过时」模型：从待核实清单里剔除，但**快照仍保留**。

判定只用两条可复核规则：
  1. 同家族里已有更新代，且本站点确实在卖更新代（判断依据就是快照里存在更新的 id）；
  2. 官方已宣布下线。

每条都写清「被谁取代」，便于以后复核。这不是删除数据，只是不再为它们花核实成本。

用法：
    python tools/ops/mark_legacy.py                # 最新一期快照
    python tools/ops/mark_legacy.py --date 20261026

输出：source-data/corrections/<date>/legacy.json（派生，可随时重跑）
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

RAW = Path("source-data")
ROOT = Path("source-data/corrections")


def resolve_date(day=None):
    """不指定就用 source-data/corrections/ 下最新的日期目录。"""
    if day:
        return day.replace("-", "")
    found = sorted(
        p.name for p in ROOT.iterdir()
        if p.is_dir() and re.fullmatch(r"\d{8}", p.name)
    ) if ROOT.exists() else []
    if not found:
        raise SystemExit("source-data/corrections/ 下没有 YYYYMMDD 目录，请用 --date 指定")
    return found[-1]

# (正则, 被谁取代, 原因)
RULES = [
    # ---- OpenAI ----
    (r"^gpt-4o(-.*)?$", "gpt-6.1 系列", "GPT-4o 代已落后 4 个大版本"),
    (r"^gpt-4\.1(-.*)?$", "gpt-6.1 系列", "GPT-4.1 代已落后 4 个大版本"),
    (r"^gpt-5(-.*)?$", "gpt-6.1 系列", "GPT-5 首代"),
    (r"^gpt-5\.1(-.*)?$", "gpt-6.1 系列", "落后 3 代"),
    (r"^gpt-5\.2(-.*)?$", "gpt-6.1 系列", "落后 2 代"),
    (r"^gpt-image-1(-.*)?$", "gpt-image-2.5 系列", "图像模型上游已有 2.5"),
    (r"^whisper-1$", "whisper-large-v3 / -turbo", "OpenAI 初代 STT"),
    (r"^tts-1(-hd)?$", "tts-gemini-3-1 / tts-qwen3 等", "OpenAI 初代 TTS"),
    # ---- Anthropic ----
    (r"^claude-(haiku|sonnet|opus)-4\.[5-8](-.*)?$", "claude-*-5.5", "Claude 4.x 代已被 5.5 取代"),
    # ---- Google ----
    (r"^gemini-2\.5-.*$", "gemini-4-argon / 3.8 系列", "Gemini 2.5 代"),
    (r"^gemini-3\.1-.*$", "gemini-4-argon / 3.8 系列", "Gemini 3.1 代，落后 3 个次版本"),
    (r"^gemma-3-.*$", "gemma-4-31b-it", "Gemma 3 代已被 Gemma 4 取代"),
    # ---- DeepSeek ----
    (r"^deepseek-v3(\.\d+)?(-.*)?$", "deepseek-v4.1-flash", "V3 代"),
    (r"^deepseek-r1(-.*)?$", "deepseek-v4 系列", "R1 代（V3 架构的推理版）"),
    # ---- 智谱 ----
    (r"^glm-4\.\d+(-.*)?$", "glm-5.3", "GLM 4.x 代已被 5.3 取代"),
    # ---- 阿里 ----
    (r"^qwen3-(?!.*3\.)[0-9a-z].*$", "qwen3.8 系列", "Qwen3 首代（版本号未带小数）"),
    (r"^qwen3\.5-.*$", "qwen3.8 系列", "落后 3 个次版本"),
    # ---- 月之暗面 ----
    (r"^kimi-k2(-.*)?$", "kimi-k3.1-pro", "K2 代；其中 kimi-k2.5 官方已于 2026-08-31 下线"),
    # ---- MiniMax ----
    (r"^minimax-m1(-.*)?$", "minimax-m3 系列", "M1 代"),
    (r"^minimax-m2\.1(-.*)?$", "minimax-m3 系列", "M2.1 代"),
    # ---- xAI ----
    (r"^grok-4\.1(-.*)?$", "grok-4.7", "落后 6 个次版本"),
    (r"^grok-4\.20-.*$", "grok-4.7", "4.20 为过渡版本"),
    # ---- Mistral ----
    (r"^mistral-(large(-3)?|nemo|small(-.*)?)$", "mistral-large-4", "Mistral 老代"),
    # ---- Meta ----
    (r"^llama-(3\.\d+|4)-.*$", "站点无更新代，但已明显落后", "Llama 3.x/4 代"),
    # ---- 图像/视频 ----
    (r"^flux-(1\.1|2-.*)$", "flux-3-image / flux-3-video", "FLUX 1.x/2 代"),
    (r"^flux-pro-1\..*$", "flux-3-*", "FLUX 1.x pro 代"),
    (r"^recraft-v[23]$", "recraft-v4.1", "Recraft v2/v3"),
    (r"^seedream-4\.5$", "seedream-5.0", "落后 1 代，且同系列 5.0 在售"),
    (r"^seedance-1\.0-pro$", "seedance-2.5", "落后 2 代"),
    (r"^wan-2\.5-preview$", "wan-3.0-video", "预览版且已有 3.0"),
    (r"^nova-(lite|micro|pro|2-lite)$", "站点无更新代，但已明显落后", "Amazon Nova 初代"),
]
COMPILED = [(re.compile(pattern), by, reason) for pattern, by, reason in RULES]

# 上游已下线 / 已退役，但站点仍在卖（请求会被转发到新模型）——优先于上面的家族规则
RETIRED = {
    "mimo-v2.5": ("（无，已下线）", "小米官方 2026-10-21 下线，ID 不再可用"),
    "grok-4": ("grok-4.3", "xAI 2026-05-15 退役，请求转发到 grok-4.3"),
    "grok-4.1-fast-reasoning": ("grok-4.3", "xAI 2026-05-15 退役，请求转发到 grok-4.3"),
    "grok-4.1-fast-non-reasoning": ("grok-4.3", "xAI 2026-05-15 退役，请求转发到 grok-4.3"),
    "grok-code-fast-1": ("grok-build-0.1", "xAI 2026-05-15 退役，请求转发到 grok-build-0.1"),
    "deepseek-v4-flash-vision-exp": ("deepseek-v4.1-flash", "第三方标注 deprecated 2026-09-25"),
}

# 语音/转写/OCR/embedding 等专用模型的版本节奏与对话模型不同，不按「落后 N 代」判老
MEDIA = ("-asr", "-embedding", "-transcribe", "-tts", "-live", "-ocr", "-diarization", "-stt", "-voice",
         "-image", "-video")
# 名字里带 next / latest 的通常是新一代，不能按版本号判老
EXCEPTIONS = {"qwen3-coder-next"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="快照日期 YYYYMMDD，默认取 source-data/corrections/ 下最新一期")
    args = ap.parse_args()

    day = resolve_date(args.date)
    l1_path = RAW / ("cheaperinference-%s.json" % day)
    corr_path = ROOT / day / "corrections.json"
    out_path = ROOT / day / "legacy.json"
    for p in (l1_path, corr_path):
        if not p.exists():
            raise SystemExit("缺少文件：%s" % p)

    models = {m["id"]: m for m in json.loads(l1_path.read_text(encoding="utf-8"))["models"]}
    covered = {c["id"] for c in json.loads(corr_path.read_text(encoding="utf-8"))["corrections"]}

    legacy = {}
    for model_id, model in models.items():
        if model_id in covered:
            continue
        if model_id in RETIRED:
            by, reason = RETIRED[model_id]
            legacy[model_id] = {"superseded_by": by, "reason": reason, "type": model["type"]}
            continue
        for pattern, by, reason in COMPILED:
            if not pattern.match(model_id):
                continue
            # 专用媒体模型（ASR/TTS/转写/OCR/embedding）不按对话模型的代际判断
            if model_id in EXCEPTIONS:
                break
            if any(tag in model_id for tag in MEDIA) and "图像" not in reason and "视频" not in reason:
                break
            legacy[model_id] = {"superseded_by": by, "reason": reason, "type": model["type"]}
            break

    payload = {
        "id": "legacy-%s" % day,
        "applies_to": "source-data/cheaperinference-%s.json" % day,
        "note": (
            "这些模型不再花核实成本：字段保留站点原值，也不进 corrections。"
            "判定依据：同家族已有更新代（快照里能看到）、官方已下线/退役，或第三方标注 deprecated；"
            "标注均为人工判断，非官方 EOL 声明。"
        ),
        "count": len(legacy),
        "models": dict(sorted(legacy.items())),
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    unverified = len(models) - len(covered)
    print("L1 %d 条｜已核实 %d｜未核实 %d｜其中判为老代 %d｜仍需核实 %d"
          % (len(models), len(covered), unverified, len(legacy), unverified - len(legacy)))
    print("按原因:", dict(Counter(v["reason"] for v in legacy.values()).most_common(8)))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
