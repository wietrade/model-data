#!/usr/bin/env python3
"""导出「自己的价」，供 new-api「同步价格」第二次导入。

价格分两个文件维护：

    官方价     api/newapi/pricing.json        公开，厂商官方页抄录
    自己的价   本脚本的 --basis（私有）       只写与官方不同的字段

后台的操作顺序是固定的：**先同步官方价，再同步自己的价**。后一次会覆盖前一次
写进 options 的对应字段，所以只改差异字段就够了。

输出形如 ``{"success": true, "message": "ok", "data": [...]}``，
每条只带 new-api 能识别的倍率字段（type2 格式），不含计费表达式：

    python -m tools.ops.export_own_price \
        --basis /opt/model-data-private/billing_basis.json \
        -o /opt/model-data-private/pricing.own.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.model_sync import expr  # noqa: E402
from tools.model_sync.merge import attach_newapi_ratios  # noqa: E402

PUBLIC = ROOT / "api" / "newapi" / "pricing.json"

# new-api type2 只认这些字段
NEWAPI_FIELDS = (
    "model_name",
    "quota_type",
    "model_ratio",
    "model_price",
    "completion_ratio",
    "cache_ratio",
    "create_cache_ratio",
    "image_ratio",
    "audio_ratio",
    "audio_completion_ratio",
)


def load_basis(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    data = doc.get("data")
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: 缺少 data 对象")
    return data


def build_rows(public_rows, basis):
    """官方价 ⊕ 自己的价，输出 new-api 能吃的倍率行。"""
    rows = {}
    for row in public_rows:
        name = row.get("model_name")
        if not name:
            continue
        entry = basis.get(name)
        merged = dict(row)
        if isinstance(entry, dict):
            merged["billing_basis"] = entry
        merged = expr.apply_billing_basis(merged)
        if merged.get("price_kind") == "unpriced" and not isinstance(entry, dict):
            continue
        rows[name] = attach_newapi_ratios(merged)

    # 只在私有文件里、公开价表没有的模型（例如没有官方价的型号）也要导出
    for name, entry in basis.items():
        if name in rows or not isinstance(entry, dict):
            continue
        rows[name] = attach_newapi_ratios({"model_name": name, "billing_basis": entry})

    out = []
    for name in sorted(rows):
        row = rows[name]
        picked = {k: row[k] for k in NEWAPI_FIELDS if k in row}
        if len(picked) > 1:  # 至少有一个价格字段
            out.append(picked)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--basis", required=True, help="自己的价（私有文件）")
    parser.add_argument("-o", "--out", required=True)
    parser.add_argument("--public", default=str(PUBLIC))
    args = parser.parse_args(argv)

    public = json.loads(Path(args.public).read_text(encoding="utf-8")).get("data") or []
    basis = load_basis(args.basis)
    rows = build_rows(public, basis)

    payload = {"success": True, "message": "ok", "data": rows}
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} own-price rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
