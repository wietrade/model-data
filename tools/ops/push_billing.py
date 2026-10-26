#!/usr/bin/env python3
"""用 new-api 的管理令牌，通过 HTTP 把计费表达式推上去。

相比直连 SQLite 的 ``apply_billing.py``，这条路：

* 不碰数据库文件（避开 WAL 模式下「只复制 .db 就等于漏数据」的备份问题）
* **不需要重启**：``billing_setting`` 是注册过的运行时配置，
  ``updateOptionMap`` → ``config.GlobalConfig`` 会即时更新内存里的价目表
* 走服务端自己的校验（``validateModelPricing``）

两个必须注意的点：

1. ``PUT /api/option/`` 对这个 key 是**整表替换**，所以要先把当前值 GET 下来合并，
   否则没出现在 payload 里的模型会被静默删掉。
2. ``GET /api/option/`` 返回的是**内存视图**，可能比库里多几个默认值；合并后写回会
   把它们一起固化进 options。这些值本来就在生效，因此不会改变行为。

用法::

    export NEWAPI_TOKEN=nap_xxx
    python -m tools.ops.push_billing -i /opt/model-data-private/billing.json --dry-run
    python -m tools.ops.push_billing -i /opt/model-data-private/billing.json --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

KEYS = ("billing_setting.billing_mode", "billing_setting.billing_expr")
DEFAULT_BASE = "https://api.nowhub.org"


def api(base: str, token: str, method: str, path: str, body=None, timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def current_options(base: str, token: str) -> dict[str, dict]:
    items = api(base, token, "GET", "/api/option/").get("data") or []
    by_key = {item["key"]: item.get("value") for item in items if isinstance(item, dict)}
    result = {}
    for key in KEYS:
        raw = by_key.get(key)
        try:
            result[key] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except json.JSONDecodeError:
            raise SystemExit(f"{key} 不是合法 JSON，先人工看一下再跑")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-i", "--input", required=True, help="export_billing 的输出")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--token", default=os.environ.get("NEWAPI_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if not args.token:
        raise SystemExit("缺少令牌：export NEWAPI_TOKEN=... 或传 --token")

    payload = json.loads(open(args.input, encoding="utf-8").read())
    missing = [key for key in KEYS if key not in payload]
    if missing:
        raise SystemExit(f"{args.input} 缺少键：{', '.join(missing)}")

    try:
        current = current_options(args.base_url, args.token)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"读取 options 失败：HTTP {error.code} {error.reason}")

    merged = {}
    for key in KEYS:
        new = dict(current[key])
        added = sorted(set(payload[key]) - set(current[key]))
        changed = sorted(k for k in payload[key] if k in current[key] and current[key][k] != payload[key][k])
        kept = sorted(set(current[key]) - set(payload[key]))
        new.update(payload[key])
        merged[key] = new
        print(f"{key}: {len(current[key])} -> {len(new)}  (+{len(added)} / ~{len(changed)} / 保留 {len(kept)})")
        for name in added[:5]:
            print(f"    + {name}")
        for name in changed[:8]:
            print(f"    ~ {name}")
        if kept:
            print(f"    保留（payload 里没有）: {', '.join(kept)}")

    if not args.apply:
        print("\n预演结束；确认无误后加 --apply 才会真正写入（写后即时生效，无需重启）")
        return 0

    for key in KEYS:
        api(args.base_url, args.token, "PUT", "/api/option/",
            {"key": key, "value": json.dumps(merged[key], ensure_ascii=False, separators=(",", ":"))})
        print(f"已写入 {key}: {len(merged[key])} 条")

    after = current_options(args.base_url, args.token)
    for key in KEYS:
        print(f"回读校验 {key}: {len(after[key])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
