"""把已到生效日的 `upcoming` 价格提升为当前价（catalog → 线上）。

`pricing.json` 用 `effective_from` / `effective_to` / `upcoming[]` 记录厂商公布的
未来调价（例：`gemini-4-argon` 2026-12-01 起输入 $2 → $4）。到期后需要：

1. 把 `upcoming` 里的价格写进行的基础字段；
2. 校验新价能生成计费表达式（表达式本身不写进公开文件，由导出时现算）；
3. 通过 `export_billing.py` + `apply_billing.py` 落库并重启。

本脚本负责第 1、2 步，默认只预演。

用法::

    python scripts/ops/promote_upcoming_pricing.py                # 预演（今天）
    python scripts/ops/promote_upcoming_pricing.py --date 2026-12-01
    python scripts/ops/promote_upcoming_pricing.py --apply

退出码：0 正常（无论是否有变更）；变更条数打印为 ``PROMOTED: N``，便于 cron 判断。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.model_sync import expr as expr_mod  # noqa: E402

PRICING = ROOT / "api" / "newapi" / "pricing.json"

# `upcoming` 里允许覆盖的字段：非 token 价格的其它键（price_kind/source 等）不得改写
PROMOTABLE = (
    "input",
    "output",
    "output_text",
    "output_image",
    "input_image",
    "cache_read",
    "cache_read_image",
    "cache_write",
    "cache_write_1h",
    "cache_write_12h",
    "per_image",
)


def promote_row(row: dict, today: dt.date) -> bool:
    pending = [item for item in (row.get("upcoming") or []) if item.get("effective_from")]
    if not pending:
        return False

    due = [item for item in pending if dt.date.fromisoformat(item["effective_from"]) <= today]
    if not due:
        return False

    item = max(due, key=lambda it: it["effective_from"])
    changed = False
    for field in PROMOTABLE:
        if field in item and item[field] is not None:
            if row.get(field) != item[field]:
                changed = True
            row[field] = item[field]

    row["effective_from"] = item["effective_from"]
    row.pop("effective_to", None)
    row["upcoming"] = [it for it in pending if it is not item]
    if not row["upcoming"]:
        row.pop("upcoming", None)

    note = f"{item['effective_from']} 起按官方已公布的新价生效（由 upcoming 提升）"
    row["notes"] = (row.get("notes", "") + "\n" + note).strip()

    # 只校验新价能生成表达式（计费侧要能用）；表达式本身不写进公开文件。
    expression, _ = expr_mod.build(row)
    if not expression:
        raise SystemExit(f"{row['model_name']}: 新价格无法生成计费表达式")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=None, help="生效判定日期，默认今天（YYYY-MM-DD）")
    parser.add_argument("--apply", action="store_true", help="写回 pricing.json")
    parser.add_argument("--file", default=str(PRICING))
    args = parser.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    path = Path(args.file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data", payload)

    promoted = []
    for row in rows:
        if promote_row(row, today):
            promoted.append(row["model_name"])
            print(f"  {row['model_name']}: in={row.get('input')} out={row.get('output')}")

    print(f"PROMOTED: {len(promoted)}")
    if not promoted:
        return 0
    if not args.apply:
        print("（预演，未写入；加 --apply 生效）")
        return 0

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"已写入 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
