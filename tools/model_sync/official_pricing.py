"""解析厂商定价页的 Markdown 版本，用于核对 ``pricing.official.json``。

两家的文档站都提供 ``.md`` 版本（OpenAI / Anthropic），表格是稳定可解析的：

- ``https://developers.openai.com/api/docs/pricing.md``
- ``https://platform.claude.com/docs/en/about-claude/pricing.md``

这里只做**解析 + 比对**，绝不写盘：官方价仍是人工确认后录入的事实源，
本模块负责把「页面上写了什么」和「我们记了什么」放在一起给人看。
"""

from __future__ import annotations

import re
from .normalize import normalize_key

_ANNOTATION = re.compile(r"<sup>.*?</sup>", re.S)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MONEY = re.compile(r"\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)")
_SKIP_SECTIONS = ("batch", "priority", "flex")


def clean_label(text: str) -> str:
    """``Claude Opus 4.5 ([link](...))`` -> ``Claude Opus 4.5``."""
    text = _LINK.sub(r"\1", text)
    text = _ANNOTATION.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_money(text: str):
    """``$10.00 / MTok`` -> ``10.0``；``-`` / 空 -> ``None``."""
    if not text:
        return None
    value = text.replace("*", "").strip()
    if value in {"-", "—", "N/A", ""}:
        return None
    match = _MONEY.search(value)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def table_cells(line: str):
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    parts = [cell.strip() for cell in stripped.strip("|").split("|")]
    return parts


def iter_tables(markdown: str):
    """Yield ``(heading, header, rows)`` for every markdown table.

    ``heading`` 是该表格上方最近的标题栈（如 ``Standard / Grouped Pricing Table data``），
    用来跳过 Batch / Priority / Flex 这类倍率表。
    """
    headings = {}
    header = None
    rows = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            headings[level] = stripped.lstrip("#").strip()
            for deeper in [key for key in headings if key > level]:
                del headings[deeper]
            if header is not None:
                yield _heading_text(headings), header, rows
                header, rows = None, []
            continue
        if stripped.startswith("|"):
            cells = table_cells(stripped)
            if header is None:
                header = cells
                continue
            if all(set(cell) <= set("-: ") for cell in cells):
                continue
            rows.append(cells)
            continue
        if header is not None:
            yield _heading_text(headings), header, rows
            header, rows = None, []
    if header is not None:
        yield _heading_text(headings), header, rows


def _heading_text(headings):
    return " / ".join(headings[key] for key in sorted(headings))


def _skip(heading: str) -> bool:
    """Batch / Priority / Flex 是主表的倍率，不是牌价。"""
    lowered = heading.lower()
    return any(word in lowered for word in _SKIP_SECTIONS)


def _column(header, *needles):
    """Index of the first header cell containing all needles (case-insensitive)."""
    lowered = [cell.lower() for cell in header]
    for index, cell in enumerate(lowered):
        if all(needle in cell for needle in needles):
            return index
    return None


def _cell(row, index):
    if index is None or index >= len(row):
        return ""
    return row[index]


def _merge(out, key, entry, prices):
    """同名字段只认第一次出现（主表在前），空值不覆盖已有值。"""
    slot = out.setdefault(key, entry)
    for field, value in prices.items():
        slot["prices"].setdefault(field, value)


def parse_claude(markdown: str):
    """Anthropic 定价表 -> ``{normalized_name: prices}``。

    列：Model / Base input / 5m cache writes / 1h cache writes / Cache hits / Output
    """
    out = {}
    for heading, header, rows in iter_tables(markdown):
        if _skip(heading) or _column(header, "base input") is None:
            continue
        in_col = _column(header, "base input")
        w5_col = _column(header, "5m cache")
        w1h_col = _column(header, "1h cache")
        hit_col = _column(header, "cache hit")
        out_col = _column(header, "output")
        if out_col is None:
            continue
        for row in rows:
            raw_label = _cell(row, 0)
            label = clean_label(raw_label)
            if not label or label.lower() == "model":
                continue
            base = label.split("(")[0].strip()
            slug = re.sub(r"^Claude\s+", "claude-", base, flags=re.I)
            slug = slug.lower().replace(" ", "-")
            prices = {
                "input": parse_money(_cell(row, in_col)),
                "cache_write": parse_money(_cell(row, w5_col)),
                "cache_write_1h": parse_money(_cell(row, w1h_col)),
                "cache_read": parse_money(_cell(row, hit_col)),
                "output": parse_money(_cell(row, out_col)),
            }
            prices = {k: v for k, v in prices.items() if v is not None}
            if not prices:
                continue
            entry = {"label": label, "base": base, "slug": slug, "prices": {}}
            limit = re.search(r"up to ([0-9,]+) tokens", raw_label)
            if limit:
                entry["context_limit_hint"] = int(limit.group(1).replace(",", ""))
            # 同一模型在长上下文 / 倍率表里会再出现一次；主表在前，只认首次命中。
            for key in (normalize_key(slug), normalize_key(base)):
                _merge(out, key, entry, prices)
    return out


def parse_openai(markdown: str):
    """OpenAI 定价表 -> ``{normalized_name: prices}``。

    支持三种表：短/长上下文 11 列（含 30m/12h 写入）、Input/Output/Cached input 4 列，
    以及带 ``Modality`` 列的图像模型表（Image 行落到 ``*_image`` 字段）。
    """
    out = {}
    for heading, header, rows in iter_tables(markdown):
        if _skip(heading):
            continue
        has_short = _column(header, "short context", "input") is not None
        if not has_short and _column(header, "input") is None:
            continue
        model_col = _column(header, "model")
        if model_col is None:
            continue
        if has_short:
            columns = {
                "input": _column(header, "short context", "input"),
                "output": _column(header, "short context", "output"),
                "cache_read": _column(header, "short context", "cached"),
                "cache_write": _column(header, "short context", "30m"),
                "cache_write_12h": _column(header, "short context", "12h"),
            }
            long_columns = {
                "input": _column(header, "long context", "input"),
                "output": _column(header, "long context", "output"),
                "cache_read": _column(header, "long context", "cached"),
                "cache_write": _column(header, "long context", "30m"),
                "cache_write_12h": _column(header, "long context", "12h"),
            }
        else:
            columns = {
                "input": _column(header, "input"),
                "output": _column(header, "output"),
                "cache_read": _column(header, "cached"),
            }
            long_columns = {}

        modality_col = _column(header, "modality")

        for row in rows:
            raw_label = _cell(row, model_col)
            label = clean_label(raw_label)
            if not label or label.lower() == "model":
                continue
            base = label.split("(")[0].strip()
            suffix = ""
            if modality_col is not None:
                modality = _cell(row, modality_col).lower()
                if not modality.startswith(("image", "text")):
                    continue
                suffix = "_image" if modality.startswith("image") else ""
            prices = {}
            for field, index in columns.items():
                value = parse_money(_cell(row, index))
                if value is not None:
                    prices[field + suffix] = value
            if not prices:
                continue
            entry = {"label": label, "base": base, "slug": base.lower(), "prices": {}}
            if long_columns:
                tier = {}
                for field, index in long_columns.items():
                    value = parse_money(_cell(row, index))
                    if value is not None:
                        tier[field] = value
                if tier:
                    limit = re.search(r"<\s*([0-9,]+)K", raw_label)
                    threshold = int(limit.group(1).replace(",", "")) * 1000 if limit else None
                    entry["long_context"] = {"prices": tier, "prompt_tokens_at_least": threshold}
            _merge(out, normalize_key(base), entry, prices)
    return out


def compare(official_rows, parsed, vendor_prefixes):
    """把页面解析结果与 ``pricing.official.json`` 的对应行比对。

    只比较双方都有的模型；页面多出来 / 我们多出来的单独列出，供人判断。
    """
    ours = {}
    for row in official_rows:
        name = str(row.get("model_name") or "")
        if not name.startswith(tuple(vendor_prefixes)):
            continue
        ours[normalize_key(name)] = row

    common, only_page, only_ours, diffs = [], [], [], []
    for key, entry in parsed.items():
        if key not in ours:
            only_page.append(entry["label"])
            continue
        common.append(ours[key]["model_name"])
        row = ours[key]
        for field, value in entry["prices"].items():
            if field in row and row[field] is not None and abs(float(row[field]) - value) > 1e-9:
                diffs.append(
                    {
                        "model": row["model_name"],
                        "field": field,
                        "ours": row[field],
                        "page": value,
                    }
                )
            elif field not in row or row.get(field) is None:
                diffs.append(
                    {"model": row["model_name"], "field": field, "ours": None, "page": value}
                )
    matched_keys = {normalize_key(name) for name in common}
    for key, row in ours.items():
        if key not in matched_keys:
            only_ours.append(row["model_name"])
    return {
        "matched": sorted(set(common)),
        "only_on_page": sorted(set(only_page)),
        "only_in_catalog": sorted(set(only_ours)),
        "diffs": diffs,
    }
