"""把厂商官方页里的「上下文 / 最大输出」抽成结构化数据。

三家官网给的形态不同，但都能抽成同一张表：

- OpenAI：`docs/models/<id>.md` 里两条列表项
  ``- 1,050,000 context window`` / ``- 128,000 max output tokens``
- Anthropic：`docs/en/models/<slug>/overview.md` 首段
  ``Context window: 1M tokens · Max output: 128K tokens``
- Google：`gemini-api/docs/models/<id>`（HTML）里
  ``Input token limit 65,536 Output token limit 32,768``；
  没有逐模型页时退回 `models.list` 的 `inputTokenLimit` / `outputTokenLimit`

本模块只做**解析**，不联网；取页面在 `tools/ops/harvest_official.py`。
"""

from __future__ import annotations

import re

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style).*?</\1>", re.S)
_SPACE = re.compile(r"\s+")

_OPENAI_CTX = re.compile(r"([0-9][0-9,]*)\s*context window", re.I)
_OPENAI_OUT = re.compile(r"([0-9][0-9,]*)\s*max output tokens", re.I)

_CLAUDE_LIMIT = re.compile(
    r"Context window:\s*([0-9.]+)\s*([KM])\s*tokens.*?Max output:\s*([0-9.]+)\s*([KM])\s*tokens",
    re.I | re.S,
)

_GEMINI_CTX = re.compile(r"Input token limit\s*([0-9][0-9,]*)", re.I)
_GEMINI_OUT = re.compile(r"Output token limit\s*([0-9][0-9,]*)", re.I)
# 部分 Gemini 3.x 页面用另一套措辞（输入输出统一窗口 + 同步输出上限）
_GEMINI_CTX_UNIFIED = re.compile(
    r"Context window \(unified input and output token limit\)\s*([0-9][0-9,]*)", re.I
)
_GEMINI_OUT_DEFAULT = re.compile(r"Max output\s*([0-9][0-9,]*)", re.I)


def html_to_text(html: str) -> str:
    """去掉标签与脚本，压缩空白；用来在 HTML 页面里做文本匹配。"""
    text = _SCRIPT.sub(" ", html)
    text = _TAG.sub(" ", text)
    return _SPACE.sub(" ", text)


def _int(value) -> int | None:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _scaled(number: str, unit: str) -> int | None:
    try:
        value = float(number)
    except (TypeError, ValueError):
        return None
    return int(round(value * (1_000_000 if unit.upper() == "M" else 1_000)))


def parse_openai(text: str) -> dict:
    """``- 1,050,000 context window`` / ``- 128,000 max output tokens``."""
    ctx = _OPENAI_CTX.search(text)
    out = _OPENAI_OUT.search(text)
    result = {}
    if ctx:
        result["context_length"] = _int(ctx.group(1))
    if out:
        result["max_output_tokens"] = _int(out.group(1))
    return result


def parse_claude(text: str) -> dict:
    """``Context window: 1M tokens · Max output: 128K tokens``."""
    match = _CLAUDE_LIMIT.search(text)
    if not match:
        return {}
    return {
        "context_length": _scaled(match.group(1), match.group(2)),
        "max_output_tokens": _scaled(match.group(3), match.group(4)),
    }


def parse_gemini_page(html: str) -> dict:
    """Gemini 逐模型页（HTML）里的上下文 / 输出上限。

    两种措辞都要认：

    - 多数模型：``Input token limit 65,536`` / ``Output token limit 32,768``
    - Gemini 3.x：``Context window (unified input and output token limit) 1,048,576`` /
      ``Max output 65,536 (default synchronous) / up to 1,048,576 (with long decode)``
      （后者只取同步默认值，long decode 不是单次请求的实际上限）
    """
    text = html_to_text(html)
    result = {}
    for pattern in (_GEMINI_CTX, _GEMINI_CTX_UNIFIED):
        match = pattern.search(text)
        if match:
            result["context_length"] = _int(match.group(1))
            break
    for pattern in (_GEMINI_OUT, _GEMINI_OUT_DEFAULT):
        match = pattern.search(text)
        if match:
            result["max_output_tokens"] = _int(match.group(1))
            break
    return result


def parse_gemini_api(payload: dict, prefix: str = "models/") -> dict:
    """``models.list`` 的 ``inputTokenLimit`` / ``outputTokenLimit``。

    返回 ``{model_id: {"context_length": .., "max_output_tokens": ..}}``。
    """
    out = {}
    for item in (payload or {}).get("models") or []:
        name = str(item.get("name") or "")
        if prefix and name.startswith(prefix):
            name = name[len(prefix):]
        if not name:
            continue
        entry = {}
        if item.get("inputTokenLimit"):
            entry["context_length"] = int(item["inputTokenLimit"])
        if item.get("outputTokenLimit"):
            entry["max_output_tokens"] = int(item["outputTokenLimit"])
        if entry:
            out[name] = entry
    return out


def merge_sources(page: dict, api: dict) -> dict:
    """逐模型页优先，缺的字段用 ``models.list`` 补；冲突记进 ``conflicts``。"""
    merged = dict(page)
    conflicts = []
    for field, value in (api or {}).items():
        if value is None:
            continue
        if field in page and page[field] is not None and page[field] != value:
            conflicts.append({"field": field, "doc": page[field], "api": value})
            continue
        merged.setdefault(field, value)
    if conflicts:
        merged["conflicts"] = conflicts
    return merged
