#!/usr/bin/env python3
"""把我们核实过的官方价与 basellm/llm-metadata 的公开数据交叉核对。

两边是**完全独立的来源**（我们逐页抄官方文档，他们以 models.dev 为底 + 社区 overrides），
所以逐字相同就是互相印证；不同则至少有一方错，值得人工看一眼。

数据面：`https://basellm.github.io/llm-metadata/api/all.json`（约 650KB，一次拉全量），
结构是 `{provider: {models: {id: {cost: {...}}}}}`。

对「峰谷价」这类表示差异做了归一：两边都把所有出现过的 (input, output) 组合摊平成集合
再比对，所以「基础价放高峰 / 放非高峰」不会误报。

用法::

    python -m tools.ops.crosscheck_basellm                 # 用线上数据
    python -m tools.ops.crosscheck_basellm --all-json <file>   # 用本地文件
    python -m tools.ops.crosscheck_basellm --strict        # 有差异时退出码 1
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRICING = ROOT / "api" / "newapi" / "pricing.json"
DEFAULT_URL = "https://basellm.github.io/llm-metadata/api/all.json"


def fetch(url: str, proxy: str | None, timeout: int = 60) -> dict:
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    else:
        opener = urllib.request.build_opener()
    request = urllib.request.Request(url, headers={"User-Agent": "model-data-crosscheck"})
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def index_upstream(document: dict) -> dict[str, dict]:
    """`{model_id: cost}`，同名的地区变体（-cn）只保留第一份 USD 价目。"""
    index: dict[str, dict] = {}
    for provider, payload in (document or {}).items():
        if not isinstance(payload, dict):
            continue
        for model_id, model in (payload.get("models") or {}).items():
            if not isinstance(model, dict):
                continue
            cost = model.get("cost")
            if not isinstance(cost, dict):
                continue
            if cost.get("currency", "USD") != "USD":
                continue
            index.setdefault(model_id, cost)
    return index


def _pairs(cost) -> set[tuple[float, float]]:
    """一份价目里出现过的所有 (input, output) 组合（基础价 + 阶梯 + 时间窗）。"""
    pairs: set[tuple[float, float]] = set()

    def add(source):
        if not isinstance(source, dict):
            return
        i, o = source.get("input"), source.get("output")
        if isinstance(i, (int, float)) and isinstance(o, (int, float)):
            pairs.add((round(float(i), 6), round(float(o), 6)))

    add(cost)
    for tier in cost.get("tiers") or []:
        add(tier)
    for window in (cost.get("schedule") or {}).get("windows") or []:
        add(window)
    return pairs


def _our_pairs(row: dict) -> set[tuple[float, float]]:
    pairs: set[tuple[float, float]] = set()

    def add(source):
        if not isinstance(source, dict):
            return
        i, o = source.get("input"), source.get("output")
        if isinstance(i, (int, float)) and isinstance(o, (int, float)):
            pairs.add((round(float(i), 6), round(float(o), 6)))

    add(row)
    for tier in row.get("tiers") or []:
        add(tier)

    # time_tiers 有两种写法：{peak, off_peak_multiplier} 或 [{windows: [...]}]
    time_tiers = row.get("time_tiers")
    entries = time_tiers if isinstance(time_tiers, list) else [time_tiers]
    for point in entries:
        if not isinstance(point, dict):
            continue
        for window in point.get("windows") or []:
            add(window)
        peak = point.get("peak")
        if isinstance(peak, dict):
            add(peak)
            multiplier = point.get("off_peak_multiplier")
            if isinstance(multiplier, (int, float)):
                pairs.add(
                    (round(float(peak["input"]) * multiplier, 6),
                     round(float(peak["output"]) * multiplier, 6))
                )
    return pairs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all-json", help="本地 all.json（不联网）")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--proxy", default=None, help="如 http://127.0.0.1:7897")
    parser.add_argument("--strict", action="store_true", help="有差异时退出码 1")
    args = parser.parse_args(argv)

    if args.all_json:
        document = json.loads(Path(args.all_json).read_text(encoding="utf-8"))
    else:
        document = fetch(args.url, args.proxy)

    upstream = index_upstream(document)
    rows = json.loads(PRICING.read_text(encoding="utf-8")).get("data") or []
    priced = [row for row in rows if row.get("input") is not None]

    missing, same, differ = [], 0, []
    for row in priced:
        name = row["model_name"]
        cost = upstream.get(name)
        if cost is None:
            missing.append(name)
            continue
        ours, theirs = _our_pairs(row), _pairs(cost)
        if ours & theirs:
            same += 1
        else:
            differ.append((name, sorted(ours), sorted(theirs)))

    print(f"我们有官方价 {len(priced)} 个 ｜ 对方收录 {len(upstream)} 个")
    print(f"  一致 {same} ｜ 对方没有 {len(missing)} ｜ 数值不同 {len(differ)}")
    if missing:
        print(f"\n对方未收录（我们自己核实过）：{', '.join(missing)}")
    for name, ours, theirs in differ:
        print(f"\n{name}\n  我们: {ours}\n  他们: {theirs}")

    if args.strict and differ:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
