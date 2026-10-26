#!/usr/bin/env python3
"""抓官方页 → 归一化成结构化快照 → 与目录比对（可选写回 overrides）。

三家官方口径：

| 厂商 | 逐模型页 | 兜底 |
|:---|:---|:---|
| OpenAI | ``developers.openai.com/api/docs/models/<id>.md`` | — |
| Anthropic | ``platform.claude.com/docs/en/models/<slug>/overview.md`` | — |
| Google | ``ai.google.dev/gemini-api/docs/models/<id>``（HTML） | ``models.list`` 的 input/outputTokenLimit |

用法::

    # 抓一遍并存快照（同时打印差异）
    python -m tools.ops.harvest_official --fetch --check

    # 只看已缓存的页面（离线）
    python -m tools.ops.harvest_official --cache %TEMP%/official-docs --check

    # 把差异写进 overrides.json（元数据，不动价格）
    python -m tools.ops.harvest_official --fetch --apply

设计约束：**价格不参与自动写回**（官方价仍人工确认），这里只管
``context_length`` / ``max_output_tokens`` 两个事实字段。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.model_sync import official_meta  # noqa: E402

MODELS = ROOT / "api" / "newapi" / "models.json"
OVERRIDES = ROOT / "reference-data" / "metadata" / "overrides.json"
GEMINI_LIST = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
FIELDS = ("context_length", "max_output_tokens")


def page_url(vendor: str, name: str) -> str | None:
    if vendor == "OpenAI":
        return "https://developers.openai.com/api/docs/models/%s.md" % name
    if vendor == "Anthropic":
        slug = name[len("claude-"):] if name.startswith("claude-") else name
        return "https://platform.claude.com/docs/en/models/%s/overview.md" % slug.replace(".", "-")
    if vendor == "Google":
        return "https://ai.google.dev/gemini-api/docs/models/%s?hl=en" % name
    return None


# 平台侧后缀：官方站点上不存在这些 id，但底下的基础型号存在
_DATE_SUFFIX = re.compile(r"-\d{8}$|-\d{4}-\d{2}-\d{2}$")
_PLATFORM_SUFFIXES = ("-tiered",)


def name_variants(name: str) -> list[str]:
    """把我们的模型名退化成可能的**官方模型 id**，按可信度从高到低。

    直接拿平台命名去拼官方 URL 会得到 404，但那**不等于「官方没有这个模型」**。
    实测到的四类（2026-10-26 快照 9 个 404 里的 7 个）：

    * `claude-haiku-4-5-20251001` → 日期快照后缀，官方 slug 是 `haiku-4-5`
    * `gemma-4-26b-a4b-it:free`  → 聚合源后缀，官方 id 没有 `:free`
    * `gemini-3.8-flash-tiered`  → 平台自造的阶梯计价版本
    * 而 `gemini-3-pro-image-preview` 这种 `-preview` 变体**不退化**：
      preview 是另一个 SKU，借用非 preview 页的数值会污染目录。

    先试原名，再逐级去掉这些后缀；第一个 200 即采用，并在结果里记下 `resolved_name`。
    全部 404 时才能判定为「官方确实没这个 id」。
    """
    out = [name]

    def add(candidate: str) -> None:
        if candidate and candidate not in out:
            out.append(candidate)

    base = name
    if ":" in base:
        base = base.split(":", 1)[0]
        add(base)
    # 后缀可能叠加（gemini-3.8-flash-tiered-20260908），逐级剥到不再变化为止
    reduced = True
    while reduced:
        reduced = False
        stripped = _DATE_SUFFIX.sub("", base)
        if stripped != base:
            base = stripped
            add(base)
            reduced = True
            continue
        for suffix in _PLATFORM_SUFFIXES:
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                add(base)
                reduced = True
                break
    # 注意**不做** `-preview` 退化：preview 是另一个 SKU（规格可能不同），
    # 借用非 preview 页的数值会把它抬成 `basis: page` 从而被 --apply 写进目录。
    # 这类模型只有 models.list 一面之辞，保持 basis: api_only 由人工判断。
    return out


class Fetcher:
    def __init__(self, cache_dir: Path, refresh: bool, timeout: int = 45, retries: int = 3):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.timeout = timeout
        self.retries = max(retries, 1)
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        tail = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1] or "index"
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in tail)[:60]
        return self.cache_dir / ("%s-%s.txt" % (safe, digest))

    def get(self, url: str, headers=None):
        path = self._path(url)
        if path.exists() and not self.refresh:
            raw = path.read_text(encoding="utf-8")
            cached_status = raw.split("\n", 1)[0].removeprefix("STATUS ")
            # 瞬时网络错误不能当结论缓存：否则一次抖动会让该模型永久显示「官方没页面」
            if cached_status != "ERR":
                return cached_status, raw.split("\n", 1)[-1]
        body = ""
        status = "ERR"
        for attempt in range(1, self.retries + 1):
            request = urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0", **(headers or {})})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    # file:// 的 response.status 是 None，按成功处理（测试与本地快照会用到）
                    status = str(getattr(response, "status", None) or 200)
                    body = response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                status, body = str(exc.code), ""
            except Exception as exc:  # noqa: BLE001 - 网络异常同一处理
                status, body = "ERR", "%s: %s" % (type(exc).__name__, exc)
            if status != "ERR":
                break
            if attempt < self.retries:
                time.sleep(1.5 * attempt)
        if status != "ERR":
            path.write_text("STATUS %s\n%s" % (status, body), encoding="utf-8", newline="\n")
        return status, body


def gemini_api_map(fetcher: Fetcher, api_key: str) -> tuple[dict, str]:
    if not api_key:
        return {}, ""
    status, body = fetcher.get(GEMINI_LIST, headers={"x-goog-api-key": api_key})
    if status != "200":
        print("warn: models.list %s" % status, file=sys.stderr)
        return {}, ""
    return official_meta.parse_gemini_api(json.loads(body)), GEMINI_LIST


def collect(fetcher: Fetcher, catalog, gemini_map, platform_only=()):
    """抓每个模型对应的官方页。

    ``platform_only`` 是 ``overrides.json`` 里标了 ``platform_only: true`` 的模型名：
    它们是上游/转售平台的命名，官方根本没有这个 id，抓了只会得到 404。
    直接记 ``source_kind: platform_only`` 并跳过请求，免得每次复跑都误报「官方无数据」。
    """
    rows = []
    for model in catalog:
        vendor = model.get("vendor_name") or ""
        name = model.get("model_name") or ""
        if name in platform_only:
            rows.append(
                {
                    "model": name,
                    "vendor": vendor,
                    "status": "-",
                    "source_kind": "platform_only",
                    "basis": "none",
                    "source_url": None,
                    "resolved_name": name,
                    "url_candidates": [],
                    "context_length": None,
                    "max_output_tokens": None,
                    "conflicts": None,
                    "catalog_context_length": model.get("context_length"),
                    "catalog_max_output_tokens": model.get("max_output_tokens"),
                }
            )
            continue
        # 拿平台命名直接拼官方 URL 会 404；逐级退化到官方 id 再判定
        url = None
        status, body = "ERR", b""
        resolved = ""
        tried = []
        for candidate in name_variants(name):
            attempt = page_url(vendor, candidate)
            if not attempt or attempt in tried:
                continue
            tried.append(attempt)
            got_status, got_body = fetcher.get(attempt)
            if url is None:
                url, status, body = attempt, got_status, got_body
            if got_status == "200":
                url, status, body = attempt, got_status, got_body
                resolved = candidate
                break
        if not url:
            continue
        parsed = {}
        basis = "none"
        if status != "200":
            # 全部候选都 404 才算「官方没有这个 id」；单个 404 只说明 URL 拼法不对
            kind = "no_official_page" if status == "404" else "error"
        else:
            if vendor == "OpenAI":
                parsed = official_meta.parse_openai(body)
            elif vendor == "Anthropic":
                parsed = official_meta.parse_claude(body)
            else:
                parsed = official_meta.parse_gemini_page(body)
            kind = "official_doc" if parsed else "unparsed"
            basis = "page" if parsed else "none"
        if vendor == "Google" and gemini_map:
            api_values = gemini_map.get(name) or {}
            before = len(parsed)
            parsed = official_meta.merge_sources(parsed, api_values)
            if basis == "page":
                kind = "official_doc+api" if len(parsed) > before or parsed.get("conflicts") else "official_doc"
            elif parsed:
                # 逐模型页缺失（preview / 已下线）：只有 API 一面之辞，不用于自动校正。
                kind = "api_only"
                basis = "api_only"
        rows.append(
            {
                "model": name,
                "vendor": vendor,
                "status": status,
                "source_kind": kind,
                "basis": basis,
                "source_url": url,
                "resolved_name": resolved or name,
                "url_candidates": tried,
                "context_length": parsed.get("context_length"),
                "max_output_tokens": parsed.get("max_output_tokens"),
                "conflicts": parsed.get("conflicts"),
                "catalog_context_length": model.get("context_length"),
                "catalog_max_output_tokens": model.get("max_output_tokens"),
            }
        )
    return rows


def diff_rows(rows):
    """只报**逐模型页**给出的值；仅 API 有值的一律不入 diff（单独列供人工判断）。"""
    out = []
    for row in rows:
        if not str(row.get("basis") or "").startswith("page"):
            continue
        for field, catalog_field in (
            ("context_length", "catalog_context_length"),
            ("max_output_tokens", "catalog_max_output_tokens"),
        ):
            official = row.get(field)
            current = row.get(catalog_field)
            if official is None or current is None:
                continue
            if int(official) != int(current):
                out.append(
                    {
                        "model": row["model"],
                        "field": field,
                        "catalog": current,
                        "official": official,
                        "source_url": row["source_url"],
                        "conflicts": row.get("conflicts"),
                    }
                )
    return out


def render_markdown(rows, diffs, generated_at):
    ok = sum(1 for r in rows if str(r.get("basis") or "").startswith("page"))
    unsupported = [r["model"] for r in rows if r["source_kind"] == "unsupported"]
    api_only = [
        r for r in rows
        if r.get("basis") == "api_only"
        and (
            r.get("context_length") not in (None, r.get("catalog_context_length"))
            or r.get("max_output_tokens") not in (None, r.get("catalog_max_output_tokens"))
        )
    ]
    lines = [
        "# 官方元数据核对（%s）" % generated_at,
        "",
        "- 覆盖 %d 个模型：%d 个有逐模型页、%d 个无逐模型页" % (len(rows), ok, len(unsupported)),
        "- 页面级差异 %d 处" % len(diffs),
        "",
    ]
    if diffs:
        lines += ["| 模型 | 字段 | 目录 | 官方 | 官方页 |", "|:---|:---|:---|:---|:---|"]
        for d in diffs:
            lines.append(
                "| `%s` | %s | %s | **%s** | %s |"
                % (d["model"], d["field"], d["catalog"], d["official"], d["source_url"])
            )
        conflicts = [d for d in diffs if d.get("conflicts")]
        if conflicts:
            lines += ["", "## 页面与 models.list 冲突（已取页面值）", ""]
            for d in conflicts:
                for c in d["conflicts"]:
                    lines.append(
                        "- `%s` %s：页面 %s / API %s" % (d["model"], c["field"], c["doc"], c["api"])
                    )
    pinned = [r for r in rows if r.get("basis") == "page" and r.get("conflicts")]
    if pinned:
        lines += ["", "## 已钉住页面值（页面与 models.list 不一致，--apply 会写进 overrides）", ""]
        for r in pinned:
            pairs = "，".join("%s=%s" % (c["field"], c["doc"]) for c in r["conflicts"])
            lines.append("- `%s`：%s（API 给的是 %s）" % (
                r["model"],
                pairs,
                ", ".join(str(c["api"]) for c in r["conflicts"]),
            ))
    if api_only:
        lines += ["", "## 仅 models.list 有值（未用于自动校正，需人工判断）", ""]
        for r in api_only:
            lines.append(
                "- `%s`：目录 ctx/out = %s/%s，API = %s/%s"
                % (
                    r["model"],
                    r.get("catalog_context_length"),
                    r.get("catalog_max_output_tokens"),
                    r.get("context_length"),
                    r.get("max_output_tokens"),
                )
            )
    if unsupported:
        lines += ["", "无逐模型页（保留目录现值）：" + "、".join("`%s`" % n for n in unsupported)]
    return "\n".join(lines)


def _append_note(old: str, extra: str) -> str:
    if not old:
        return extra
    if note_present(extra, old):
        return old
    sep = "" if old.endswith(("。", "；", ".", ";")) else "；"
    return old + sep + extra


def note_present(extra: str, old: str) -> bool:
    """粗粒度去重：同一句已经写过就不再追加。"""
    head = extra.split("：", 1)[-1][:24]
    return bool(head) and head in old


def apply_overrides(diffs, rows, day):
    """把两类别东西写进 overrides.json：

    1. 目录与页面不一致的字段（直接校正）；
    2. 页面与 ``models.list`` 不一致的字段（即使目录已对，也要**钉住**：
       合并时会先让官方 API 赢过聚合源，不钉的话下次同步就被 API 改掉了）。

    幂等：只写「与现有 overrides 不同」的字段；没变化就不碰文件、不追加 note。
    """
    desired = {}
    pins = {}
    for d in diffs:
        desired.setdefault(d["model"], {})[d["field"]] = int(d["official"])

    for row in rows:
        if row.get("basis") != "page" or not row.get("conflicts"):
            continue
        for conflict in row["conflicts"]:
            desired.setdefault(row["model"], {}).setdefault(conflict["field"], int(conflict["doc"]))
            pins.setdefault(row["model"], {})[conflict["field"]] = "页面 %s / API %s" % (
                conflict["doc"],
                conflict["api"],
            )

    if not desired:
        print("官方页与目录一致，overrides.json 未改动")
        return

    doc = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    models = doc.setdefault("models", [])
    by_name = {r["model"]: r for r in rows}
    touched = 0

    for model in sorted(desired):
        fields = desired[model]
        existing = next((e for e in models if e.get("model_name") == model), None)
        current = dict(existing.get("fields") or {}) if existing else {}
        pending = {k: v for k, v in fields.items() if current.get(k) != v}
        if not pending:
            continue

        row = by_name.get(model, {})
        note = "%s 官方页核对（%s）：%s。依据 %s" % (
            row.get("vendor") or "厂商",
            day,
            "，".join("%s=%s" % (k, v) for k, v in sorted(pending.items())),
            row.get("source_url") or "官方文档",
        )
        conflicts = [pins.get(model, {})[k] for k in sorted(pending) if k in pins.get(model, {})]
        if conflicts:
            note += "（与 models.list 冲突，取页面：%s）" % "；".join(conflicts)

        if existing is None:
            models.append({"model_name": model, "note": note, "fields": pending})
        else:
            existing.setdefault("fields", {}).update(pending)
            existing["note"] = _append_note(existing.get("note") or "", note)
        touched += 1

    if not touched:
        print("官方页与目录一致，overrides.json 未改动")
        return

    OVERRIDES.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("已更新 overrides.json：%d 个模型" % touched)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", help="页面缓存目录（默认系统临时目录/official-docs）")
    parser.add_argument("--fetch", action="store_true", help="忽略缓存重新抓取")
    parser.add_argument("--proxy", help="抓取时使用的 HTTPS 代理")
    parser.add_argument("--check", action="store_true", help="打印差异表")
    parser.add_argument("--apply", action="store_true", help="把差异写进 overrides.json（仅元数据）")
    parser.add_argument("--out", help="快照输出路径（默认 source-data/official-metadata-<date>.json）")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    if args.proxy:
        os.environ["HTTPS_PROXY"] = args.proxy
        os.environ["https_proxy"] = args.proxy

    cache = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "official-docs"
    fetcher = Fetcher(cache, refresh=args.fetch)
    catalog = json.loads(MODELS.read_text(encoding="utf-8"))["data"]
    gemini_map, gemini_src = gemini_api_map(fetcher, (os.environ.get("GEMINI_API_KEY") or "").strip())

    overrides_doc = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.exists() else {}
    platform_only = {
        str(item.get("model_name") or "")
        for item in overrides_doc.get("models") or []
        if item.get("platform_only")
    }
    rows = collect(fetcher, catalog, gemini_map, platform_only)
    diffs = diff_rows(rows)
    now = datetime.now().astimezone()
    generated_at = now.isoformat(timespec="seconds")
    day = now.strftime("%Y%m%d")

    snapshot = {
        "generated_at": generated_at,
        "sources": {
            "openai": "https://developers.openai.com/api/docs/models/<id>.md",
            "anthropic": "https://platform.claude.com/docs/en/models/<slug>/overview.md",
            "google": "https://ai.google.dev/gemini-api/docs/models/<id>",
            "google_list_api": gemini_src or None,
        },
        "models": rows,
    }
    out_path = Path(args.out) if args.out else ROOT / "source-data" / ("official-metadata-%s.json" % day)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("snapshot: %s（%d 个模型）" % (out_path, len(rows)))

    if args.apply:
        apply_overrides(diffs, rows, day)
    if args.check or args.apply:
        if args.format == "json":
            print(json.dumps(diffs, ensure_ascii=False, indent=2))
        else:
            print(render_markdown(rows, diffs, generated_at))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
