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
from tools.ops.normalize_snapshot import normalize_item  # noqa: E402

DEFAULT_LOCAL = ROOT / "api" / "newapi" / "models.json"

# 对比字段：快照侧一律用**归一化后**的键名（原始快照会先过 normalize_snapshot）
FIELD_MAP = {
    "context_length": "context_length",
    "max_output_tokens": "max_output_tokens",
}

# 集合类字段：模态与能力（清洗后直接用，不再从 bool 反推）
SET_FIELDS = ("input_modalities", "output_modalities", "capabilities")


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


def normalize_snapshot(items):
    """原始快照（带 ``detail_*``）先洗一遍：token 过度声明、detail 优先级都在那里定。"""
    if items and any(str(k).startswith("detail_") for k in items[0]):
        return [normalize_item(item) for item in items]
    return items


def compare(local, snapshot):
    snapshot = normalize_snapshot(snapshot)
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

        low_confidence = {
            "input_modalities": item.get("input_source") in ("type", "type+vision"),
            "output_modalities": item.get("output_source") == "type",
            "capabilities": item.get("capabilities_source") == "tokens",
        }
        for field in SET_FIELDS:
            theirs = set(item.get(field) or [])
            ours = set(model.get(field) or [])
            if theirs != ours:
                diffs.append(
                    {
                        "model": name,
                        "field": field,
                        "ours": sorted(ours),
                        "snapshot": sorted(theirs),
                        "low": low_confidence.get(field, False),
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
            field = diff["field"] + ("（弱证据）" if diff.get("low") else "")
            ours = diff["ours"]
            theirs = diff["snapshot"]
            if isinstance(ours, list):
                ours = ", ".join(map(str, ours)) or "—"
                theirs = ", ".join(map(str, theirs)) or "—"
            lines.append(f"| `{diff['model']}` | {field} | {ours} | {theirs} |")
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
