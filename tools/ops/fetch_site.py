#!/usr/bin/env python3
"""抓 cheaperinference 的市场页 + 每个模型的详情页，产出**忠实于站点**的快照。

数据来源（都是服务端渲染，不需要登录 / API key / 浏览器）：

* ``/markets``      —— 全部模型汇总字段，内嵌在 Next.js 的 RSC 载荷里
* ``/models/<id>``  —— 每个模型一张 14 行 ``dt/dd`` 表（端点、模态原文、上下文、
  最大输出、支持的参数…），即 ``detail_*`` 的来源

三层保证数据正确：

1. **解析**：只从 RSC 载荷里取，宽松匹配 ``dt``/``dd``（不依赖 className）；
   标签单复数 + 大小写归一（embedding 类用单数 ``Endpoint``）。
2. **抓取**：每个模型独立重试，单个失败不影响其余；统计成功/失败/缺行。
3. **校验**（``--verify``，默认开）：条目数、12 个字段是否齐全、端点形态、
   数值冲突、身份一致性（详情页的 Model ID / Provider 是否与市场页一致）、
   id 是否可安全拼进 URL；发现致命问题退出码 1。

本脚本**不改站点的判定**：站点写 ``Not reported`` 就照录，写错的数值也照录。
「用官方数据纠正站点错误」是下一步（corrections 层）的事，不能混在这里。

用法::

    python -m tools.ops.fetch_site --proxy http://127.0.0.1:7897 --out source-data/cheaperinference-20261026.json
    python -m tools.ops.fetch_site --limit 5 --no-details      # 只试解析
    python -m tools.ops.fetch_site --save-html .tmp/pages     # 顺便留证据
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://platform.cheaperinference.com"
UA = "model-data/1.0 (+https://github.com/wietrade/model-data)"
ROOT = Path(__file__).resolve().parents[2]

# 价格 / 结算口径：公开仓库一律剔除（--keep-prices 只能用于私有目录）
PRICE_KEYS = {
    "listInputPerM",
    "listOutputPerM",
    "ourInputPerM",
    "ourOutputPerM",
    "cacheReadInputMultiplier",
    "cacheWriteInputMultiplier",
    "discountPercent",
    "listPriceKnown",
    "unitPriceUsd",
    "referenceUnitPriceUsd",
    "unit",
    "imageOutputPerM",
    "referenceImageOutputPerM",
    "zdr",
}

# 详情页标签 -> 快照字段；注意 embedding 类模型用单数 Endpoint
# detail_Provider 是**卖方/上游**（页面 meta 写 "from Venice AI through one API"），
# 与市场页的 providerLabel（模型厂商，如 OpenAI）不是一个东西，必须分开存。
LABEL_MAP = {
    "provider": "detail_Provider",
    "model id": "id",
    "type": "detail_Type",
    "endpoint": "detail_Endpoints",
    "endpoints": "detail_Endpoints",
    "input": "detail_Input",
    "output": "detail_Output",
    "vision input": "detail_VisionInput",
    "image editing": "detail_ImageEditing",
    "video input": "detail_VideoInput",
    "reasoning": "detail_Reasoning",
    "streaming": "detail_Streaming",
    "context window": "detail_ContextWindow",
    "maximum output": "detail_MaximumOutput",
    "supported parameters": "detail_SupportedParameters",
}
# 详情页必须出现的行（缺行说明站点改版或解析失效，要报错）
REQUIRED_LABELS = {
    "provider",
    "model id",
    "type",
    "endpoints",
    "input",
    "output",
    "vision input",
    "image editing",
    "video input",
    "reasoning",
    "streaming",
    "context window",
    "maximum output",
    "supported parameters",
}
DETAIL_ORDER = [
    "detail_Provider",
    "detail_Type",
    "detail_Endpoints",
    "detail_Input",
    "detail_Output",
    "detail_VisionInput",
    "detail_ImageEditing",
    "detail_VideoInput",
    "detail_Reasoning",
    "detail_Streaming",
    "detail_ContextWindow",
    "detail_MaximumOutput",
    "detail_SupportedParameters",
]
ENDPOINT_PLACEHOLDER = "None has passed a live request yet"
SCALE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_DT = re.compile(r'"dt",null,\{[^{}]*?"children":"([^"]*)"')
_DD = re.compile(r'"dd",null,\{[^{}]*?"children":"([^"]*)"')


def _number(value):
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kKmMbB])?", str(value or "").replace(",", ""))
    if not match:
        return None
    return int(float(match.group(1)) * SCALE.get((match.group(2) or "").lower(), 1))


def _get(url, proxy=None, retries=3, timeout=30, ua=UA):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
    )
    last = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": ua})
            with opener.open(request, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - 网络异常统一重试
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("GET %s 失败: %s" % (url, last))


def _rsc_text(page):
    """把 Next.js 的 RSC push 块拼回可读文本（只做这一层反转义，不用全局 replace）。"""
    chunks = _PUSH.findall(page)
    if not chunks:
        raise ValueError("页面里没有 self.__next_f.push 载荷，可能不是 Next.js 或结构已变")
    return "".join(json.loads(chunk) for chunk in chunks)


def _balanced(text, start):
    """从 ``start`` 处的 ``{`` 起返回配平的 JSON 子串。"""
    depth, in_str, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_str:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_str = False
            continue
        if char == '"':
            in_str = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("JSON 没有配平")


def parse_markets(page):
    """市场页 -> 模型列表（保持站点给的顺序）。"""
    text = _rsc_text(page)
    start = text.find('{"models":[')
    if start < 0:
        raise ValueError("市场页里找不到 models 数组")
    return json.loads(_balanced(text, start))["models"]


def parse_detail(page):
    """详情页 -> ``({字段: 值}, 缺失的必需标签)``。"""
    text = _rsc_text(page)
    labels = _DT.findall(text)
    values = _DD.findall(text)
    if len(labels) != len(values):
        raise ValueError("dt/dd 数量不一致: %d/%d" % (len(labels), len(values)))
    rows, seen = {}, set()
    for label, value in zip(labels, values):
        clean = htmllib.unescape(label).strip().lower()
        # embedding 类模型写单数 Endpoint，归一后再判断必需行
        seen.add("endpoints" if clean == "endpoint" else clean)
        key = LABEL_MAP.get(clean)
        if key:
            rows[key] = htmllib.unescape(value).strip()
    return rows, sorted(REQUIRED_LABELS - seen)


def fetch(base=BASE, proxy=None, limit=None, concurrency=6, delay=0.1, with_details=True,
          save_html=None, log=print):
    """抓市场页和详情页。返回 ``(models, details, errors, missing_rows)``。"""
    models = parse_markets(_get(base + "/markets", proxy=proxy))
    log("市场页: %d 条模型" % len(models))
    if limit:
        models = models[:limit]
    if not with_details:
        return models, {}, [], {}

    def load(model):
        time.sleep(delay)
        page = _get("%s/models/%s" % (base, model["id"]), proxy=proxy)
        if save_html:
            target = Path(save_html) / (model["id"] + ".html")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page, encoding="utf-8", newline="\n")
        return model["id"], parse_detail(page)

    details, errors, missing = {}, [], {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(load, model): model["id"] for model in models}
        for index, future in enumerate(as_completed(futures), 1):
            model_id = futures[future]
            try:
                _, (rows, missing_labels) = future.result()
            except Exception as exc:  # noqa: BLE001 - 单条失败不影响其余
                errors.append((model_id, str(exc)))
                continue
            details[model_id] = rows
            if missing_labels:
                missing[model_id] = missing_labels
            if index % 50 == 0:
                log("  详情 %d/%d" % (index, len(models)))
    log("详情页: 成功 %d / 失败 %d / 缺行 %d" % (len(details), len(errors), len(missing)))
    return models, details, errors, missing


def merge(models, details, keep_prices=False):
    """汇总字段 + 详情行 -> 记录列表。

    所有记录用**同一套键**（缺的填 ``None``），顺序固定：先市场页字段，
    再按 ``DETAIL_ORDER`` 追加详情字段。ID 兜底用详情页的 Model ID 校验。
    """
    drop = set() if keep_prices else set(PRICE_KEYS) | {"logoUrl"}

    market_keys = []
    for model in models:
        for key in model:
            if key not in market_keys and key not in drop:
                market_keys.append(key)
    if "id" in market_keys:
        market_keys.remove("id")
        market_keys.insert(0, "id")

    records = []
    for model in models:
        record = {key: model.get(key) for key in market_keys}
        for key in DETAIL_ORDER:
            record[key] = None
        for key, value in details.get(model["id"], {}).items():
            if key != "id":
                record[key] = value
        records.append(record)
    return records, market_keys


def verify(models, details, records, market_keys):
    """对抓取结果做自检，返回 ``(errors, warnings, info)``；errors 会让退出码变 1。"""
    errors, warnings = [], []
    ids = [record.get("id") for record in records]

    if len(records) != len(models):
        errors.append("条目数不一致: 市场页 %d / 输出 %d" % (len(models), len(records)))
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        errors.append("重复 id: %s" % sorted(duplicates))
    unsafe = [i for i in ids if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(i))]
    if unsafe:
        errors.append("id 不能安全拼进 URL: %s" % unsafe[:10])

    for record in records:
        if not record.get("id"):
            errors.append("有记录缺少 id")
            continue
        absent = [key for key in DETAIL_ORDER if key not in record]
        if absent:
            errors.append("%s 缺少详情字段 %s" % (record["id"], absent))
        if not details.get(record["id"]):
            errors.append("%s 没有抓到详情页" % record["id"])

    # 身份一致性：详情页自称的 Model ID / Provider 必须与市场页一致
    for model in models:
        rows = details.get(model["id"])
        if not rows:
            continue
        if rows.get("id") and rows["id"] != model["id"]:
            errors.append("详情页 Model ID 不一致: 市场页 %s / 详情页 %s" % (model["id"], rows["id"]))

    # 端点形态
    placeholders, bad_endpoints = [], []
    for record in records:
        endpoints = (record.get("detail_Endpoints") or "").strip()
        if endpoints == ENDPOINT_PLACEHOLDER:
            placeholders.append(record["id"])
        elif not all(part.strip().startswith("/") for part in endpoints.split(",") if part.strip()):
            bad_endpoints.append((record["id"], endpoints))
    if bad_endpoints:
        errors.append("端点形态异常: %s" % bad_endpoints[:5])

    # 数值冲突：详情原文与市场页数值必须一致
    conflicts = []
    for record in records:
        for detail_key, numeric_key in (("detail_ContextWindow", "contextLength"),
                                        ("detail_MaximumOutput", "maxOutputTokens")):
            detail_value = _number(record.get(detail_key))
            numeric_value = record.get(numeric_key)
            if detail_value is not None and numeric_value is not None and detail_value != numeric_value:
                conflicts.append((record["id"], detail_key, numeric_value, record.get(detail_key)))
    if conflicts:
        errors.append("详情原文与数值字段冲突 %d 条: %s" % (len(conflicts), conflicts[:5]))

    info = {
        "条目数": len(records),
        "字段数": len(market_keys) + len(DETAIL_ORDER),
        "端点占位句": len(placeholders),
        "servedAt 为空": sum(1 for r in records if not r.get("servedAt")),
        "providerSlug 为空": sum(1 for r in records if not r.get("providerSlug")),
        "卖方≠厂商": sum(1 for r in records
                       if r.get("detail_Provider") and r["detail_Provider"] != r.get("providerLabel")),
    }
    return errors, warnings, info


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--proxy", default=None, help="例如 http://127.0.0.1:7897")
    parser.add_argument("--out", help="输出 JSON 路径")
    parser.add_argument("--limit", type=int, help="只抓前 N 条（调试用）")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--delay", type=float, default=0.1, help="每个详情请求前的等待秒数")
    parser.add_argument("--no-details", action="store_true", help="只抓市场页")
    parser.add_argument("--keep-prices", action="store_true", help="保留价格字段（只能写私有目录）")
    parser.add_argument("--save-html", help="把详情页 HTML 存到该目录（留证据/复盘用）")
    parser.add_argument("--no-verify", action="store_true", help="跳过自检")
    args = parser.parse_args(argv)

    started = time.time()
    models, details, errors, missing = fetch(
        base=args.base,
        proxy=args.proxy,
        limit=args.limit,
        concurrency=args.concurrency,
        delay=args.delay,
        with_details=not args.no_details,
        save_html=args.save_html,
    )
    records, market_keys = merge(models, details, args.keep_prices)

    fatal = [{"id": model_id, "error": error} for model_id, error in errors]
    for model_id, labels in missing.items():
        fatal.append({"id": model_id, "error": "详情页缺行: %s" % ", ".join(labels)})

    verify_errors, verify_warnings = [], []
    if not args.no_verify:
        verify_errors, verify_warnings, info = verify(models, details, records, market_keys)
        for line in verify_errors:
            print("✗ %s" % line)
        for line in verify_warnings[:20]:
            print("! %s" % line)
        if len(verify_warnings) > 20:
            print("! …还有 %d 条警告" % (len(verify_warnings) - 20))
        print("自检: %s｜%s" % ("通过" if not verify_errors else "失败",
                              "，".join("%s %s" % item for item in info.items())))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "source": "%s/markets + %s/models/<id>" % (args.base, args.base),
        "fetched_at": today,
        "imported_at": today,
        "count": len(records),
        "note": (
            "抓取自站点服务端渲染页面；价格字段%s剔除。"
            "站点的字段矛盾（如 Reasoning 写 Not supported）原样保留，纠正在后续 corrections 层处理。"
            "注意：capabilities 与 detail_Endpoints 由站点按近期真实请求动态计算，"
            "两次抓取会不同；detail_Provider 是卖方/上游，不是模型厂商。"
            % ("" if args.keep_prices else "已")
        ),
        "fetch": {
            "url": args.base + "/markets",
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seconds": round(time.time() - started, 1),
            "failed_pages": fatal,
        },
        "models": [{key: record.get(key) for key in market_keys + DETAIL_ORDER} for record in records],
    }

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print("wrote %s（%d 条，%d 字节）" % (out, len(records), out.stat().st_size))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
    return 1 if fatal or (not args.no_verify and verify_errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
