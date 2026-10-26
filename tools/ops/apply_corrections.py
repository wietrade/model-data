#!/usr/bin/env python3
"""把 L2 核实层应用到 L1 抓取快照，产出 L3 可信视图。**永不修改 detail_***。

三层结构::

    L1  raw/cheaperinference-<date>.json         站点原话，一字不改
    L2  corrections/<date>/corrections.json  官方核实值 + source_url
    L3  raw/cheaperinference-<date>.verified.json L1 + L2，供下游消费

硬性规则（脚本会强制检查，不是文档里的约定）：

1. ``detail_*`` 字段一律只读：输出里这些键必须与 L1 逐字节相同，否则报错退出；
2. 每条 correction 必须有 ``source_url``，否则拒绝应用；
3. ``confidence`` 低于 ``--min-confidence`` 的条目不应用，只列进待复核清单；
4. 应用后仍违反 ``maxOutputTokens <= contextLength`` 的记录，必须在报告里逐条列出。

用法::

    python -m tools.ops.apply_corrections --date 20261026
    python -m tools.ops.apply_corrections \\
        --snapshot raw/cheaperinference-20261026.json \\
        --corrections corrections/20261026/corrections.json \\
        --out raw/cheaperinference-20261026.verified.json \\
        --changelog .tmp/changelog-20261026.csv
    python -m tools.ops.apply_corrections --snapshot ... --corrections ... --dry-run
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
from collections import Counter
from pathlib import Path

# 允许被修正的字段：全是「我们自己的结构化字段」
SAFE_FIELDS = {
    "contextLength",
    "maxOutputTokens",
    "vision",
    "reasoning",
    "imageEdit",
    "type",
    "group",
    "kind",
    "providerLabel",
    "providerSlug",
    "servedAs",
}
ROUTING_FIELDS = ("servedAs", "retiredAt")
CAP_ACTIONS = ("add_capabilities", "remove_capabilities")
LEVELS = {"high": 3, "medium": 2, "low": 1}
CAP_ORDER = [
    "image-input",
    "file-input",
    "audio-input",
    "video-input",
    "reasoning",
    "tool-use",
    "structured-output",
    "web-search",
    "implicit-caching",
    "explicit-caching",
    "image-edit",
    "websockets",
    "realtime",
    "context-128k",
    "context-1m",
]


def sort_caps(caps):
    return sorted(set(caps), key=lambda c: (CAP_ORDER.index(c) if c in CAP_ORDER else 99, c))


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(corrections, by_id):
    errors, warnings = [], []
    for index, entry in enumerate(corrections, 1):
        tag = "#%d %s" % (index, entry.get("id"))
        if entry.get("id") not in by_id:
            errors.append("%s：快照里没有这个模型" % tag)
        if not entry.get("source_url"):
            errors.append("%s：缺 source_url，拒绝应用" % tag)
        if entry.get("confidence") not in LEVELS:
            errors.append("%s：confidence 取值非法 %r" % (tag, entry.get("confidence")))
        if not (entry.get("field") or entry.get("add_capabilities") or entry.get("remove_capabilities")):
            errors.append("%s：没有要做的修改" % tag)
        if entry.get("field") and entry["field"] not in SAFE_FIELDS:
            errors.append("%s：字段 %r 不在允许列表（detail_* 永远不可改）" % (tag, entry["field"]))
        for token in entry.get("add_capabilities", []) + entry.get("remove_capabilities", []):
            if token not in CAP_ORDER:
                warnings.append("%s：未知能力标签 %r，已忽略" % (tag, token))
    return errors, warnings


def apply(snapshot, corrections, min_confidence="high"):
    models = snapshot["models"]
    by_id = {m["id"]: m for m in models}
    errors, warnings = validate(corrections, by_id)
    if errors:
        raise SystemExit("核实层自检失败：\n  " + "\n  ".join(errors))

    threshold = LEVELS[min_confidence]
    changelog, skipped = [], []
    for entry in corrections:
        if LEVELS[entry["confidence"]] < threshold:
            skipped.append({
                "id": entry["id"],
                "field": entry.get("field") or ",".join(entry.get("add_capabilities") or entry.get("remove_capabilities")),
                "value": entry.get("value"),
                "confidence": entry["confidence"],
                "source_url": entry["source_url"],
            })
            continue
        record = by_id[entry["id"]]
        if entry.get("field"):
            old = record.get(entry["field"])
            if old != entry["value"]:
                record[entry["field"]] = entry["value"]
                changelog.append([entry["id"], entry["field"], json.dumps(old, ensure_ascii=False),
                                  json.dumps(entry["value"], ensure_ascii=False),
                                  entry["confidence"], entry["source_url"], entry.get("reason", "")])
        if entry.get("add_capabilities") or entry.get("remove_capabilities"):
            old = list(record.get("capabilities") or [])
            new = set(old)
            new |= set(entry.get("add_capabilities") or [])
            new -= set(entry.get("remove_capabilities") or [])
            new = sort_caps(new)
            if new != old:
                record["capabilities"] = new
                changelog.append([entry["id"], "capabilities", json.dumps(old, ensure_ascii=False),
                                  json.dumps(new, ensure_ascii=False),
                                  entry["confidence"], entry["source_url"], entry.get("reason", "")])

    touched = {row[0] for row in changelog if row[1] == "contextLength"}
    changelog.extend(sync_context_tags(snapshot, touched))
    return changelog, skipped, warnings


def sync_context_tags(snapshot, model_ids):
    """contextLength 被改后，同步 capabilities 里的 context-128k / context-1m 标签。

    站点是按自家声称的上下文打标签的（grok-4 站点写 2M → 带 context-1m），
    我们改成官方规格 256K 后，标签会变成“说 1M 实际 256K”的自相矛盾。
    只动被修正过的行，站点原生标签不碰。
    """
    by_id = {m["id"]: m for m in snapshot["models"]}
    rows = []
    for model_id in sorted(model_ids):
        record = by_id.get(model_id)
        ctx = record.get("contextLength") if record else None
        if not isinstance(ctx, int):
            continue
        old = list(record.get("capabilities") or [])
        new = {c for c in old if not c.startswith("context-")}
        for tag, threshold in (("context-128k", 128000), ("context-1m", 1000000)):
            if ctx >= threshold:
                new.add(tag)
        new = sort_caps(new)
        if new != old:
            record["capabilities"] = new
            rows.append([model_id, "capabilities (context 标签)", json.dumps(old, ensure_ascii=False),
                         json.dumps(new, ensure_ascii=False), "high", "",
                         "随同行 contextLength 修正同步"])
    return rows


def apply_routing(snapshot, routing):
    """把「实际服务的模型」写成附加字段 servedAs / retiredAt。

    这些字段与核实结论无关（contextLength 等仍记原型号规格），只是让下游知道
    请求其实被转到了哪里，避免用户按旧规格使用已退役的 id。
    """
    by_id = {m["id"]: m for m in snapshot["models"]}
    changelog, errors = [], []
    for model_id, item in (routing.get("models") or {}).items():
        record = by_id.get(model_id)
        if record is None:
            errors.append("%s：快照里没有这个模型" % model_id)
            continue
        if not str(item.get("source_url", "")).startswith("http"):
            errors.append("%s：缺 source_url" % model_id)
            continue
        for field, key in (("servedAs", "served_as"), ("retiredAt", "retired_at")):
            value = item.get(key)
            if value is None or record.get(field) == value:
                continue
            old = record.get(field)
            record[field] = value
            changelog.append([model_id, field, json.dumps(old, ensure_ascii=False),
                              json.dumps(value, ensure_ascii=False), item.get("confidence", "high"),
                              item["source_url"], "上游路由：%s" % item.get("quote", "")])
    if errors:
        raise SystemExit("路由层自检失败：\n  " + "\n  ".join(errors))
    return changelog


def check_invariants(before, after):
    """返回（detail_* 是否被动过, 仍未解决的 max>context 列表）。"""
    by_before = {m["id"]: m for m in before["models"]}
    moved, violations = [], []
    for record in after["models"]:
        source = by_before.get(record["id"], {})
        for key, value in source.items():
            if key.startswith("detail_") and record.get(key) != value:
                moved.append((record["id"], key, value, record.get(key)))
        ctx, out = record.get("contextLength"), record.get("maxOutputTokens")
        if isinstance(ctx, int) and isinstance(out, int) and out > ctx:
            violations.append((record["id"], ctx, out))
        for key in ("contextLength", "maxOutputTokens"):
            if record.get(key) is not None and not isinstance(record.get(key), int):
                violations.append((record["id"], "%s 非整数" % key, record.get(key)))
    return moved, violations


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", help="快照日期 YYYYMMDD；给了就自动推导其余路径")
    parser.add_argument("--snapshot", help="L1 抓取快照")
    parser.add_argument("--corrections", help="L2 核实层")
    parser.add_argument("--routing", help="可选：上游路由层（servedAs / retiredAt）")
    parser.add_argument("--out", help="L3 输出路径")
    parser.add_argument("--changelog", help="变更清单 CSV")
    parser.add_argument("--min-confidence", default="high", choices=sorted(LEVELS, key=LEVELS.get))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.date:
        day = args.date.replace("-", "")
        root = Path("corrections") / day
        routing = root / "routing.json"
        args.snapshot = args.snapshot or str(Path("raw") / ("cheaperinference-%s.json" % day))
        args.corrections = args.corrections or str(root / "corrections.json")
        args.routing = args.routing or (str(routing) if routing.exists() else None)
        args.out = args.out or str(Path("raw") / ("cheaperinference-%s.verified.json" % day))
        args.changelog = args.changelog or str(root / "changelog.csv")
    if not args.snapshot or not args.corrections:
        parser.error("需要 --date，或同时提供 --snapshot 与 --corrections")

    snapshot = load(args.snapshot)
    corrections = load(args.corrections)
    original = copy.deepcopy(snapshot)
    entries = corrections.get("corrections", corrections if isinstance(corrections, list) else [])

    changelog, skipped, warnings = apply(snapshot, entries, args.min_confidence)
    routing_rows = []
    if args.routing:
        routing_rows = apply_routing(snapshot, load(args.routing))
        changelog.extend(routing_rows)
    moved, violations = check_invariants(original, snapshot)

    if moved:
        print("✗ detail_* 被改动了 %d 处，违反只读约束：%s" % (len(moved), moved[:3]))
        return 1

    snapshot.setdefault("audit", {})
    snapshot["audit"].update({
        "corrections_id": corrections.get("id"),
        "applied": len(changelog),
        "skipped_low_confidence": len(skipped),
        "min_confidence": args.min_confidence,
        "remaining_max_output_over_context": len(violations),
        "note": "在 L1 抓取快照基础上应用 L2 官方核实值；detail_* 未改动。",
    })

    print("应用 %d 处（跳过 %d 条低置信度）｜detail_* 未改动｜剩余 max>context %d 条"
          % (len(changelog) - len(routing_rows), len(skipped), len(violations)))
    if routing_rows:
        print("路由标注 %d 处（servedAs / retiredAt）" % len(routing_rows))
    for line in warnings[:10]:
        print("! %s" % line)
    for model_id, ctx, out in violations[:10]:
        print("  · %s：maxOutput %s > context %s" % (model_id, out, ctx))

    if args.changelog and not args.dry_run:
        path = Path(args.changelog)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["model_id", "field", "old", "new", "confidence", "source_url", "reason"])
            writer.writerows(changelog)
        print("wrote", path)

    if not args.dry_run and args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print("wrote", out, "（%d 条）" % len(snapshot["models"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
