#!/usr/bin/env python3
"""比对第三方快照与本目录的模型事实，输出差异清单。

用途：``raw/`` 里的快照只是旁证，不能直接并入 ``api/newapi/models.json``。
本脚本给出「哪些字段、双方各是什么值」，由人对照官方文档决定改哪边。

用法::

    python -m tools.ops.compare_snapshot raw/cheaperinference-20261023-full.json
    python -m tools.ops.compare_snapshot raw/... --format json -o /tmp/diff.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.model_sync.normalize import normalize_key  # noqa: E402

DEFAULT_LOCAL = ROOT / "api" / "newapi" / "models.json"

# 快照字段 -> 本地字段（None 表示需要布尔推断）
FIELD_MAP = {
    "contextLength": "context_length",
    "maxOutputTokens": "max_output_tokens",
}


def load_models(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["models"] if isinstance(data, dict) else data


def load_local(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["data"] if isinstance(data, dict) else data


def build_index(items):
    index = {}
    for item in items:
        for raw in (item.get("id"), item.get("label")):
            name = str(raw or "").strip()
            if not name:
                continue
            index.setdefault(normalize_key(name), item)
            index.setdefault(normalize_key(name.split("/")[-1]), item)
    return index


def compare(local, snapshot):
    index = build_index(snapshot)
    matched, unmatched, diffs = [], [], []
    for model in local:
        name = model["model_name"]
        item = index.get(normalize_key(name))
        if item is None:
            unmatched.append(name)
            continue
        matched.append(name)
        for source_field, local_field in FIELD_MAP.items():
            theirs = item.get(source_field)
            ours = model.get(local_field)
            if theirs and theirs != ours:
                diffs.append(
                    {"model": name, "field": local_field, "ours": ours, "snapshot": theirs}
                )
        snapshot_vision = bool(item.get("vision"))
        our_vision = "image" in (model.get("input_modalities") or [])
        if snapshot_vision != our_vision:
            diffs.append(
                {
                    "model": name,
                    "field": "input_modalities(image)",
                    "ours": our_vision,
                    "snapshot": snapshot_vision,
                }
            )
        snapshot_reasoning = bool(item.get("reasoning"))
        our_reasoning = "reasoning" in (model.get("capabilities") or [])
        if snapshot_reasoning != our_reasoning:
            diffs.append(
                {
                    "model": name,
                    "field": "capabilities(reasoning)",
                    "ours": our_reasoning,
                    "snapshot": snapshot_reasoning,
                }
            )
    return matched, unmatched, diffs


def render_markdown(matched, unmatched, diffs, snapshot_path):
    lines = [
        f"快照：`{snapshot_path}`",
        "",
        f"- 命中 {len(matched)} 个模型，未命中 {len(unmatched)} 个，差异 {len(diffs)} 处",
        "",
    ]
    if diffs:
        lines += ["| 模型 | 字段 | 本目录 | 快照 |", "|:---|:---|:---|:---|"]
        for diff in diffs:
            lines.append(
                f"| `{diff['model']}` | {diff['field']} | {diff['ours']} | {diff['snapshot']} |"
            )
    if unmatched:
        lines += ["", "## 快照里没有的本地模型", "",
                  "、".join(f"`{name}`" for name in unmatched)]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="raw/ 下的第三方快照")
    parser.add_argument("--local", default=str(DEFAULT_LOCAL), help="本地 models.json")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("-o", "--output", help="写入文件而不是打印")
    args = parser.parse_args(argv)

    snapshot_path = Path(args.snapshot)
    matched, unmatched, diffs = compare(
        load_local(Path(args.local)), load_models(snapshot_path)
    )

    if args.format == "json":
        text = json.dumps(
            {"matched": matched, "unmatched": unmatched, "diffs": diffs},
            ensure_ascii=False,
            indent=2,
        )
    else:
        text = render_markdown(matched, unmatched, diffs, args.snapshot)

    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
