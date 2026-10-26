"""Export the price list as new-api billing options.

new-api reads ``billing_setting.billing_mode`` and ``billing_setting.billing_expr``
from the options table. This turns ``pricing.json`` into exactly those two maps,
so a price change is one command instead of hand-editing expressions in the UI.

上游结算价（我们自己的采购成本）**不在仓库里**。它由 ``--basis`` 指定的私有
文件提供，导出时用它覆盖牌价再生成表达式::

    python -m tools.model_sync.export_billing \
        --basis /opt/model-data-private/billing_basis.json -o /tmp/billing.json

不传 ``--basis`` 时按公开牌价导出（用于本地预览）。

``--alias live=source`` maps a model still deployed under an old name onto the
expression of the model that replaced it (for example a ``:free`` suffix that
was dropped after the model turned out to be paid).

默认还会读 ``reference-data/metadata/aliases.json``：渠道侧那些**官方不存在的
id**（例如 ``gpt-image-2.5``）不在目录里建条目，但要能按对应的官方模型计费。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import expr
from .merge import basis_for, load_billing_basis
from .normalize import normalize_key

ALIASES_PATH = os.path.join("reference-data", "metadata", "aliases.json")


def load_aliases(path=None):
    """读取渠道别名表：``{上游 id: 目录里的官方模型}``。缺文件不算错。"""
    target = path or ALIASES_PATH
    try:
        with open(target, encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError:
        return {}
    mapping = document.get("aliases") if isinstance(document, dict) else None
    if not isinstance(mapping, dict):
        return {}
    return {str(k): str(v) for k, v in mapping.items() if str(k).strip() and str(v).strip()}


def load_prices(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def build_payload(prices, aliases=None, basis=None):
    """Render ``{model: billing_expr}``.

    Expressions are always recomputed from the row, with the private settlement
    basis overlaid when supplied: the committed ``billing_expr`` only reflects
    list prices, so trusting it would silently drop the upstream cost basis.
    """
    expressions = {}
    for row in prices.get("data") or []:
        name = str(row.get("model_name") or "")
        if not name:
            continue
        source_row = dict(row)
        entry = basis_for(name, basis)
        if entry:
            source_row["billing_basis"] = entry
        expression, _ = expr.build(source_row)
        if expression:
            expressions[name] = expression
    # 只在私有 basis 里有、公开价目表里没有牌价的模型，也要能导出。
    names = (basis or {}).get("names") or {}
    for key, entry in ((basis or {}).get("data") or {}).items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("model_name") or names.get(key) or key
        if name in expressions:
            continue
        expression, _ = expr.build({"model_name": name, "billing_basis": entry})
        if expression:
            expressions[name] = expression
    by_key = {normalize_key(name): name for name in expressions}
    for alias, source in (aliases or {}).items():
        target = expressions.get(source) or expressions.get(by_key.get(normalize_key(source)))
        if target is None:
            raise SystemExit(f"alias {alias}: no expression for {source}")
        expressions[alias] = target
    if not expressions:
        raise SystemExit("pricing file produced no billing expression")
    return {
        "billing_setting.billing_mode": {name: "tiered_expr" for name in expressions},
        "billing_setting.billing_expr": expressions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--input",
        default=os.path.join("api", "newapi", "pricing.json"),
    )
    parser.add_argument("-o", "--output")
    parser.add_argument(
        "--basis",
        help="上游结算价文件（私有，不随仓库发布）；省略则按公开牌价导出",
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        metavar="LIVE=SOURCE",
        help="deployed model name that should reuse the expression of SOURCE",
    )
    parser.add_argument(
        "--aliases-file",
        default=None,
        help="渠道别名表（默认 reference-data/metadata/aliases.json）",
    )
    args = parser.parse_args(argv)

    aliases = load_aliases(args.aliases_file)
    for item in args.alias:
        if "=" not in item:
            raise SystemExit(f"--alias expects LIVE=SOURCE, got {item!r}")
        live, source = item.split("=", 1)
        aliases[live.strip()] = source.strip()

    basis = load_billing_basis(args.basis) if args.basis else None
    payload = build_payload(load_prices(args.input), aliases, basis)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded + "\n")
        count = len(payload["billing_setting.billing_expr"])
        print(f"wrote {count} expressions to {args.output}")
    else:
        print(encoded)


if __name__ == "__main__":
    sys.exit(main())
