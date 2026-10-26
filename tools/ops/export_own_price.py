#!/usr/bin/env python3
"""导出「自己的价」，供 new-api「同步价格」第二次导入。

价格分两个文件维护：

    官方价     api/newapi/pricing.json        公开，厂商官方页抄录
    自己的价   本脚本的 --basis（私有）       只写与官方不同的字段

后台的操作顺序是固定的：**先同步官方价，再同步自己的价**。后一次会覆盖前一次
写进 options 的对应字段，所以只改差异字段就够了。

输出与 ``api/newapi/pricing.json`` **完全同构**（同一个 envelope、同一批字段），
只是价格换成了自己的价、倍率跟着重算。这样后台「同步价格」里填两个自定义地址、
走同一套解析即可：第一趟官方价，第二趟自己的价覆盖差异字段。

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


def load_basis(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    data = doc.get("data")
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: 缺少 data 对象")
    return data


def build_rows(public_rows, basis):
    """官方价 ⊕ 自己的价，输出**与 pricing.json 完全同构**的行。

    结构必须一致：两个文件填进后台的两个自定义地址，走同一套解析。
    差异只在值上——价格字段换成自己的价，倍率字段跟着重算。
    """
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
        merged.pop("billing_basis", None)
        if isinstance(entry, dict):
            merged["source"] = "own_price"
        rows[name] = attach_newapi_ratios(merged)

    # 只在私有文件里、公开价表没有的模型（例如没有官方价的型号）也要导出
    for name, entry in basis.items():
        if name in rows or not isinstance(entry, dict):
            continue
        merged = {"model_name": name, "currency": "USD", "unit": "per_1m_tokens"}
        merged.update({k: v for k, v in entry.items() if k in expr.OVERRIDE_FIELDS})
        if merged.get("per_image") is not None:
            merged["unit"] = "per_image"
        merged["price_kind"] = "own_price"
        merged["source"] = "own_price"
        rows[name] = attach_newapi_ratios(merged)

    return [rows[name] for name in sorted(rows)]


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
