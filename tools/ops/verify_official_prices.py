#!/usr/bin/env python3
"""核对厂商定价页（Markdown 版）与 ``pricing.official.json`` 是否一致。

只读：输出差异清单，不修改任何文件。官方价仍由人工确认后录入。

用法::

    # 用已下载的页面
    python -m tools.ops.verify_official_prices \
        --claude /tmp/claude_pricing.md --openai /tmp/openai_pricing.md

    # 直接抓（走 HTTPS_PROXY / --proxy）
    python -m tools.ops.verify_official_prices --fetch --proxy http://127.0.0.1:7897
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.model_sync import official_pricing  # noqa: E402

SOURCES = {
    "claude": "https://platform.claude.com/docs/en/about-claude/pricing.md",
    "openai": "https://developers.openai.com/api/docs/pricing.md",
}
PREFIXES = {"claude": ("claude-",), "openai": ("gpt-",)}
OFFICIAL = ROOT / "reference-data" / "price" / "pricing.official.json"


def fetch(url: str, proxy: str | None, timeout: int = 60) -> str:
    if proxy:
        os.environ["HTTPS_PROXY"] = proxy
        os.environ["https_proxy"] = proxy
    request = urllib.request.Request(url, headers={"user-agent": "model-data/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def load_official(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["data"] if isinstance(data, dict) else data


def render(sections, as_json: bool):
    if as_json:
        return json.dumps(sections, ensure_ascii=False, indent=2)
    lines = []
    for vendor, result in sections.items():
        lines.append(f"## {vendor}")
        lines.append("")
        lines.append(
            f"- 命中 {len(result['matched'])} 个模型，差异 {len(result['diffs'])} 处，"
            f"页面多出 {len(result['only_on_page'])} 个，目录多出 {len(result['only_in_catalog'])} 个"
        )
        if result["diffs"]:
            lines += ["", "| 模型 | 字段 | 目录 | 页面 |", "|:---|:---|:---|:---|"]
            for diff in result["diffs"]:
                lines.append(
                    f"| `{diff['model']}` | {diff['field']} | {diff['ours']} | {diff['page']} |"
                )
        if result["only_in_catalog"]:
            lines += ["", "目录里有、页面没有：" + "、".join(f"`{n}`" for n in result["only_in_catalog"])]
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", help="Anthropic pricing.md 本地路径")
    parser.add_argument("--openai", help="OpenAI pricing.md 本地路径")
    parser.add_argument("--fetch", action="store_true", help="直接抓取官方页面")
    parser.add_argument("--proxy", help="抓取时使用的 HTTPS 代理")
    parser.add_argument("--official", default=str(OFFICIAL))
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("-o", "--output")
    args = parser.parse_args(argv)

    texts = {}
    for vendor in ("claude", "openai"):
        path = getattr(args, vendor)
        if path:
            texts[vendor] = Path(path).read_text(encoding="utf-8")
        elif args.fetch:
            texts[vendor] = fetch(SOURCES[vendor], args.proxy)
    if not texts:
        parser.error("至少给一个 --claude/--openai 文件，或使用 --fetch")

    official_rows = load_official(Path(args.official))
    sections = {}
    for vendor, text in texts.items():
        parser_fn = official_pricing.parse_claude if vendor == "claude" else official_pricing.parse_openai
        sections[vendor] = official_pricing.compare(
            official_rows, parser_fn(text), PREFIXES[vendor]
        )

    text = render(sections, args.format == "json")
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
