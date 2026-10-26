"""Merge source data into the committed metadata documents.

Merge policy (deliberate, keeps hand-maintained content alive):

* factual fields are refreshed from sources: vendor, capabilities, modalities,
  context window, max output, free flag
* local fields are never overwritten: description, icon, tags, endpoints,
  name_rule, status  (`tags` is user-owned by design)
* existing models missing from every source are kept as-is
* new models are only created with ``--allow-new`` (plus optional release-date
  floor), so an aggregator adding hundreds of models cannot flood the plaza
* ambiguous matches (same normalized key, several candidates) are reported and
  left untouched
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .normalize import CAPABILITY_ORDER, normalize_key

MODALITY_ORDER = ("text", "image", "file", "audio", "video")

# 汇率只在一处配置：sources/fx.json。数据行必须存**原币值**，禁止手写换算结果，
# 否则同一批数据会同时出现几个隐含汇率（2026-10-26 真的踩到过）。
FX_PATH = Path(__file__).resolve().parents[2] / "sources" / "fx.json"

# 需要随币种换算的数值字段（按 1M tokens / 每张图 计价）
PRICE_NUMBER_FIELDS = (
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

FACTUAL_FIELDS = (
    "vendor_name",
    "capabilities",
    "input_modalities",
    "output_modalities",
    "context_length",
    "max_output_tokens",
    "is_free",
    "lifecycle",
    "release_date",
    "knowledge_cutoff",
)

DEFAULT_MODEL = {
    "vendor_name": "",
    "description": "",
    "icon": "",
    "name_rule": 0,
    "status": 1,
    "tags": "",
    "capabilities": [],
    "input_modalities": [],
    "output_modalities": [],
    "lifecycle": "",
    "release_date": "",
    "knowledge_cutoff": "",
    "context_length": 0,
    "max_output_tokens": 0,
    "is_free": False,
    "endpoints": None,
}


def index_incoming(incoming):
    """Group sources by normalized key, in source-priority order.

    Multiple entries for one key are kept (models.dev and openrouter disagree
    often enough that dropping them would hide real conflicts).
    """
    index = {}
    duplicates = 0
    for model in incoming:
        key = model.key
        if not key:
            continue
        bucket = index.setdefault(key, [])
        if bucket:
            duplicates += 1
        bucket.append(model)
    return index, duplicates


def pick_incoming(candidates, model_name):
    """Choose the candidate that best matches a concrete model name.

    1. identical model name (``gpt-5.6-sol`` == ``gpt-5.6-sol``)
    2. source id ending with the name (``anthropic/claude-haiku-4-5``)
    3. highest-priority source (first in ``--sources`` order)
    """
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.model_name == model_name:
            return candidate
    for candidate in candidates:
        if candidate.source_id.endswith("/" + model_name) or candidate.source_id == model_name:
            return candidate
    return candidates[0]


CONFLICT_FIELDS = ("context_length", "max_output_tokens")


def detect_conflicts(index):
    """Report keys where sources disagree on a factual field.

    Silent "first source wins" is how a 1.05M context window becomes 1.31M
    in production, so disagreements are surfaced explicitly.
    """
    conflicts = []
    for key, candidates in index.items():
        if len(candidates) < 2:
            continue
        for field in CONFLICT_FIELDS:
            values = {}
            for candidate in candidates:
                value = int(getattr(candidate, field) or 0)
                if value > 0:
                    values.setdefault(value, []).append(candidate.source)
            if len(values) > 1:
                conflicts.append(
                    {
                        "key": key,
                        "field": field,
                        "values": {
                            value: sorted(set(sources))
                            for value, sources in values.items()
                        },
                    }
                )
    return conflicts


def _incoming_values(model):
    return {
        "vendor_name": model.vendor_name,
        "capabilities": list(model.capabilities or []),
        "input_modalities": list(model.input_modalities or []),
        "output_modalities": list(model.output_modalities or []),
        "context_length": int(model.context_length or 0),
        "max_output_tokens": int(model.max_output_tokens or 0),
        "is_free": model.is_free,
        # 聚合源目前不提供生命周期信息；用 getattr 兼容测试里的简化 model 对象
        "lifecycle": getattr(model, "lifecycle", "") or "",
        "release_date": getattr(model, "release_date", "") or "",
        "knowledge_cutoff": getattr(model, "knowledge_cutoff", "") or "",
    }


def _new_record(model, name=None, values=None, skip=None):
    skip = skip or set()
    values = values or _incoming_values(model)
    record = {
        "model_name": name or model.model_name,
        "vendor_name": model.vendor_name,
        "description": model.description or "",
        "icon": model.icon or "",
        "name_rule": DEFAULT_MODEL["name_rule"],
        "status": DEFAULT_MODEL["status"],
        "tags": DEFAULT_MODEL["tags"],
        "capabilities": _ordered_list("capabilities", values.get("capabilities") or ()),
        "input_modalities": _ordered_list(
            "input_modalities", values.get("input_modalities") or ()
        ),
        "output_modalities": _ordered_list(
            "output_modalities", values.get("output_modalities") or ()
        ),
        "context_length": 0 if (model.key, "context_length") in skip
        else int(values.get("context_length") or 0),
        "max_output_tokens": 0 if (model.key, "max_output_tokens") in skip
        else int(values.get("max_output_tokens") or 0),
        "is_free": bool(values.get("is_free")),
        "endpoints": None,
    }
    return record


def _refresh(record, model, changes, skip=None, skipped=None):
    """Apply factual fields, ignoring empty/unknown source values.

    Fields listed in ``skip`` (source disagreement) are left untouched: a
    guessed context window is worse than an unknown one.
    """
    skip = skip or set()
    values = _incoming_values(model)
    _apply_values(record, values, model.key, changes, skip, skipped)


def _meaningful(field, value):
    """Normalize a candidate value; ``None`` means "source has no opinion"."""
    if field == "is_free":
        return None if value is None else bool(value)
    if field in ("context_length", "max_output_tokens"):
        number = int(value or 0)
        return number if number > 0 else None
    if isinstance(value, (list, tuple)):
        return tuple(sorted(value)) if value else None
    return value or None


def _ordered_list(field, values):
    """Restore a deterministic order after set-based comparison."""
    if field == "capabilities":
        return [cap for cap in CAPABILITY_ORDER if cap in values]
    if field in ("input_modalities", "output_modalities"):
        return [mod for mod in MODALITY_ORDER if mod in values]
    return list(values)


def agreed_values(candidates):
    """Per-field values that every candidate agrees on.

    Dated snapshots of one model (``deepseek-v4-pro-20260813`` and
    ``...-20260423``) often agree on the context window but not on max output;
    taking field-level agreement keeps the trustworthy half instead of
    discarding the whole model.
    """
    agreed = {}
    conflicts = set()
    prepared = [_incoming_values(candidate) for candidate in candidates]
    for field in FACTUAL_FIELDS:
        seen = {}
        for values in prepared:
            value = _meaningful(field, values[field])
            if value is not None:
                seen[value] = True
        if len(seen) == 1:
            agreed[field] = next(iter(seen))
        elif len(seen) > 1:
            conflicts.add(field)
    return agreed, conflicts


def _apply_values(record, values, model_key, changes, skip, skipped=None):
    for field in FACTUAL_FIELDS:
        if (model_key, field) in skip:
            if skipped is not None and record.get(field) not in (None, 0, [], "", False):
                skipped.append({"model": record.get("model_name", ""), "field": field})
            continue
        new = _meaningful(field, values.get(field))
        old = record.get(field)
        if new is None:
            continue
        if field == "max_output_tokens":
            context = record.get("context_length") or 0
            if context and new > context:
                new = context
        if field == "is_free":
            new = bool(new)
        elif isinstance(new, tuple):
            new = _ordered_list(field, new)
        if old != new:
            changes.append(
                {
                    "model": record.get("model_name", ""),
                    "field": field,
                    "from": old,
                    "to": new,
                }
            )
            record[field] = new


def _official_agreement(candidates, field):
    """官方源内部一致时返回 ``(value, source)``，否则 ``None``。

    官方源（``official:<vendor>``）只在少数事实字段上有发言权，但那是
    「运行时真正强制的值」，所以和聚合源冲突时以它为准；官方源自己互相
    矛盾时不敢猜，交回上游按冲突处理。
    """
    found = {}
    for candidate in candidates:
        if not str(candidate.source).startswith("official:"):
            continue
        value = _meaningful(field, _incoming_values(candidate).get(field))
        if value is None:
            continue
        found[value] = candidate.source
    if len(found) == 1:
        return next(iter(found.items()))
    return None


def resolve_values(candidates, tie_break=None, model_name=""):
    """Resolve one model's fact values from all candidate records.

    优先级：**各方一致 > 官方源（``official:*``，需官方内部一致）
    > ``tie_break``（默认 openrouter）> 记为未解决**。

    官方优先于聚合源，是因为 ``context_length`` / ``max_output_tokens``
    这类上限由厂商 API 真正强制；聚合站经常把 0.9× 折算值或思考预算
    塞进同一个字段。
    """
    if len(candidates) == 1:
        return _incoming_values(candidates[0]), set(), {}

    values, conflicts = agreed_values(candidates)
    resolved = {}

    for field in sorted(conflicts):
        official = _official_agreement(candidates, field)
        if official is not None:
            values[field], source = official
            resolved[field] = source

    if tie_break:
        def rank(candidate):
            if candidate.model_name == model_name:
                return 0
            if model_name and (
                candidate.source_id == model_name
                or candidate.source_id.endswith("/" + model_name)
            ):
                return 1
            return 2

        prepared = [(c, _incoming_values(c)) for c in sorted(candidates, key=rank)]
        for field in sorted(conflicts - set(resolved)):
            for candidate, candidate_values in prepared:
                if candidate.source != tie_break:
                    continue
                value = _meaningful(field, candidate_values[field])
                if value is not None:
                    values[field] = value
                    resolved[field] = tie_break
                    break

    conflicts -= set(resolved)
    return values, conflicts, resolved


def merge_metadata(existing, index, allow_new=False, min_release_date="",
                   allowed_new=None, skip_fields=None, tie_break=None):
    """Return (records, changes, added, ambiguous, missing).

    ``allowed_new`` restricts creation to an explicit set of model names, so
    补全 can be reviewed model by model instead of trusting every aggregator row.
    ``skip_fields`` is a set of ``(normalized_key, field)`` that sources
    disagree on; those fields are never written.
    """
    changes = []
    added = []
    ambiguous = []
    tie_broken = []
    matched_keys = set()
    skip_fields = set(skip_fields or ())

    # exact names first, then normalized keys (only when unambiguous)
    by_name = {str(item.get("model_name", "")): item for item in existing}

    for record in existing:
        name = str(record.get("model_name", ""))
        model_key = normalize_key(name)
        candidates = index.get(model_key) or []
        if not candidates:
            continue
        if len(candidates) == 1:
            values = _incoming_values(candidates[0])
            conflicts = set()
        else:
            values, conflicts, resolved = resolve_values(candidates, tie_break, name)
            for field, source in resolved.items():
                tie_broken.append({"model": name, "field": field, "source": source})
            if conflicts:
                ambiguous.append(
                    "%s (%s)" % (name, ",".join(sorted(conflicts)))
                )
        conflict_fields = conflicts | {
            field for (key, field) in skip_fields if key == model_key
        }
        matched_keys.add(model_key)
        _apply_values(record, values, model_key, changes, conflict_fields)

    if allow_new:
        pending = {
            normalize_key(name): name for name in (allowed_new or ()) if name
        }
        existing_names = {str(item.get("model_name", "")) for item in existing}
        for key, candidates in sorted(
            index.items(),
            key=lambda item: (item[1][0].vendor_name, item[1][0].model_name),
        ):
            desired = pending.get(key) if pending else None
            if pending and desired is None:
                continue
            if desired is not None and desired in existing_names:
                continue
            if key in matched_keys and desired is None:
                continue
            model = pick_incoming(candidates, desired or "")
            if min_release_date and (model.release_date or "") < min_release_date:
                continue
            name = desired or model.model_name
            if not name:
                continue
            if len(candidates) == 1:
                values = _incoming_values(candidates[0])
                conflicts = set()
            else:
                values, conflicts, resolved = resolve_values(
                    candidates, tie_break, name or ""
                )
                for field, source in resolved.items():
                    tie_broken.append(
                        {"model": name, "field": field, "source": source}
                    )
            conflict_fields = conflicts | {
                field for (candidate_key, field) in skip_fields if candidate_key == key
            }
            existing.append(_new_record(model, name, values, conflict_fields))
            existing_names.add(name)
            added.append(name)
            matched_keys.add(key)

    missing = sorted(
        name
        for name in by_name
        if normalize_key(name) not in index
    )
    # 模型名里的 ``:free`` 是明确的免计费契约：聚合源价格缺失或冲突时
    # 也必须标记为免费，否则前端会漏掉“免费”徽标和筛选。
    for record in existing:
        if str(record.get("model_name", "")).endswith(":free"):
            record["is_free"] = True
    return existing, changes, added, ambiguous, missing, tie_broken


def load_official_prices(path):
    """Read ``pricing.official.json`` into ``{normalized_key: row}``.

    The file is optional: without it the merge behaves exactly as before and
    ``pricing.json`` stays an aggregator-only snapshot.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    prices = {}
    for row in payload.get("data") or []:
        name = str(row.get("model_name") or "").strip()
        if name:
            prices[normalize_key(name)] = row
    return prices


OFFICIAL_PRICE_FIELDS = (
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
    "tiers",
    "meters",
    "time_tiers",
    "effective_from",
    "effective_to",
    "upcoming",
)


def free_price_row(record):
    """Row for a model the catalog marks free but no source prices.

    ``is_free`` is our own guarantee that the model is not billed, so a zero row
    is more accurate than leaving the model out of the price list.
    """
    row = {
        "model_name": str(record.get("model_name", "")),
        "vendor_name": record.get("vendor_name") or "",
        "price_kind": "free",
        "source_kind": "catalog",
        "source": "metadata:is_free",
        "currency": "USD",
        "unit": "per_1m_tokens",
        "input": 0.0,
        "output": 0.0,
        "cache_read": 0.0,
    }
    return row


def unpriced_row(record):
    """Row for a model with no vendor list price.

    公开仓只放官方价。聚合站报价是我们自己算倍率时用的旁证，结算价是我们
    的成本——两者都不进这个目录，所以这里只留「有此模型、无公开价」这一个事实。
    """
    return {
        "model_name": str(record.get("model_name", "")),
        "vendor_name": record.get("vendor_name") or "",
        "price_kind": "unpriced",
    }


def official_price_row(record, official, fx=None):
    """Turn one ``pricing.official.json`` row into a ``pricing.json`` row.

    只搬运厂商官方价与其出处（``source_url`` / ``retrieved_at`` / ``confidence``）。
    结算价（basis）与由价格派生的表达式一律不进来。
    """
    name = str(record.get("model_name", ""))
    row = {
        "model_name": name,
        "vendor_name": record.get("vendor_name") or official.get("vendor_name") or "",
        "price_kind": "vendor_official",
        "source_kind": official.get("source_kind") or "official_doc",
        "source": "vendor_official",
        "source_model_id": official.get("model_name") or name,
        "currency": "USD",
        "unit": "per_1m_tokens",
    }
    for key in ("source_url", "retrieved_at", "confidence"):
        value = official.get(key)
        if value:
            row[key] = value
    for field in OFFICIAL_PRICE_FIELDS:
        value = official.get(field)
        if value is not None:
            row[field] = value
    return convert_to_usd(row, fx)


def load_fx(path=None):
    """读汇率表：``{"units_per_usd": {"CNY": 6.677446, ...}}``。"""
    target = Path(path) if path else FX_PATH
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"units_per_usd": {"USD": 1.0}}
    rates = document.get("units_per_usd")
    if not isinstance(rates, dict) or "USD" not in rates:
        return {"units_per_usd": {"USD": 1.0}}
    return document


def _scale_prices(source, factor):
    for field in PRICE_NUMBER_FIELDS:
        value = source.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            source[field] = round(float(value) / factor, 6)


def convert_to_usd(row, fx=None):
    """把一行原币官方价换算成 USD；已经是 USD 的行原样返回。

    换算覆盖基础价、``tiers``/``time_tiers`` 里的所有价位与 ``meters`` 单价——
    漏掉任何一层都会得到一半 USD 一半原币的脏数据。
    """
    currency = (row.get("currency") or "USD").upper()
    if currency == "USD":
        return row

    rates = (fx or load_fx()).get("units_per_usd") or {}
    factor = rates.get(currency)
    if not isinstance(factor, (int, float)) or factor <= 0:
        raise ValueError(f"sources/fx.json 里没有 {currency} 的汇率，无法换算 {row.get('model_name')}")

    converted = copy.deepcopy(row)
    _scale_prices(converted, factor)
    for tier in converted.get("tiers") or []:
        if isinstance(tier, dict):
            _scale_prices(tier, factor)
    time_tiers = converted.get("time_tiers")
    for point in time_tiers if isinstance(time_tiers, list) else [time_tiers]:
        if not isinstance(point, dict):
            continue
        for window in [point.get("peak")] + list(point.get("windows") or []):
            if isinstance(window, dict):
                _scale_prices(window, factor)
    for meter in converted.get("meters") or []:
        if isinstance(meter, dict) and isinstance(meter.get("price"), (int, float)):
            meter["price"] = round(float(meter["price"]) / factor, 6)

    converted["currency"] = "USD"
    converted["fx_to_usd"] = factor
    return converted



def has_usable_price(official):
    """Official row carries at least one number we can bill with.

    ``unresolved`` models (e.g. a variant the vendor never priced) keep their
    entry with all prices null; such a row must not become a ``pricing.json``
    row, otherwise downstream ratio derivation divides by None.
    """
    if official.get("meters"):
        return True
    if official.get("tiers"):
        return True
    return any(official.get(key) is not None for key in ("input", "output", "per_image"))


def basis_for(name, basis):
    """Look up the settlement basis for one published model name."""
    if not basis:
        return None
    data = basis.get("data") if isinstance(basis.get("data"), dict) else basis
    return data.get(normalize_key(str(name)))


def load_billing_basis(path):
    """Load the settlement document (per-model upstream cost numbers).

    Returns ``{"data": {normalized_name: entry}, "meta": {...}}``. Keys are
    normalized so aliases resolve to the same entry. A missing file is not an
    error: it only means every row bills straight from its list price.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except FileNotFoundError:
        return {"data": {}, "meta": {}}
    if not isinstance(doc, dict):
        return {"data": {}, "meta": {}}
    data = doc.get("data")
    if not isinstance(data, dict):
        return {"data": {}, "meta": {}}
    meta = {
        key: doc.get(key)
        for key in ("source", "source_url", "retrieved_at", "currency", "fx_to_usd", "unit")
        if doc.get(key) is not None
    }
    return {
        "data": {
            normalize_key(name): value
            for name, value in data.items()
            if isinstance(value, dict)
        },
        "names": {normalize_key(name): name for name in data},
        "meta": meta,
    }


def strip_settlement(row):
    """Reduce a carried settlement-flavoured row to a bare published shell.

    公开仓只放牌价。``billing_basis`` / ``*_cny`` / ``source: settlement`` /
    ``fx_to_usd`` / 结算价镜像值描述的是我们向上游付多少，一律不落盘。
    落不下来的行只留「有这个模型，但没有公开牌价」这一个事实（``unpriced``）。
    """
    if not row.get("billing_basis") and not any(k.endswith("_cny") for k in row):
        # 已是公开行（只有牌价）：原样保留，避免数据源临时失败时把价格洗掉。
        return dict(row)
    return {
        "model_name": str(row.get("model_name", "")),
        "vendor_name": str(row.get("vendor_name", "")),
        "price_kind": "unpriced",
    }


def price_records(existing, index, official=None, previous=None):
    """Build the published pricing rows (vendor list prices only).

    ``api/newapi/`` 只放厂商公开数据，所以这里只产出三类行：

    * ``vendor_official`` —— 官方定价页抄录的价，带出处；
    * ``free`` —— 目录标记免费且确实没有报价；
    * ``unpriced`` —— 有此模型但没有公开价，**不带任何数字**。

    聚合站报价（models.dev / OpenRouter）与结算价（我们向上游付多少）都不发布：
    前者是我们算倍率时的旁证，后者是成本。由价格派生的表达式同样不在这里，
    部署机 ``export_billing --basis`` 导出时现算。

    One row per **published model name**: aliases (``claude-haiku-5.5`` vs
    ``claude-haiku-5-5``) each get their own row, because price lookup is by
    exact model id.
    """
    official = official or {}
    # 上一次生成的 pricing.json：没有任何牌价来源时保住这一行（只保留行壳，
    # 结算价与表达式由 strip_settlement 清掉）。
    carried = {
        str(row.get("model_name", "")): row
        for row in (previous or [])
        if isinstance(row, dict) and row.get("model_name")
    }
    rows = []
    seen = set()
    for record in existing:
        name = str(record.get("model_name", ""))
        key = normalize_key(name)
        if name in seen:
            continue
        seen.add(name)
        listed = official.get(key)
        if listed is not None and has_usable_price(listed):
            rows.append(official_price_row(record, listed))
            continue
        model = pick_incoming(index.get(key) or [], name)
        if model is not None and model.price:
            # 聚合站报价不发布：它既不是官方价，也是我们算倍率时的内部旁证。
            rows.append(unpriced_row(record))
            continue
        if record.get("is_free"):
            rows.append(free_price_row(record))
            continue
        if name in carried:
            previous_row = carried[name]
            if previous_row.get("price_kind") in ("vendor_official", "free"):
                # 官方源临时挂掉时用上一版保住价格，避免把已核实的值洗成空。
                rows.append(strip_settlement(previous_row))
                continue
        rows.append(unpriced_row(record))

    rows.sort(key=lambda item: (item["vendor_name"], item["model_name"]))
    return rows


OVERRIDABLE_FIELDS = set(FACTUAL_FIELDS) | {
    "description",
    "icon",
    "tags",
    "endpoints",
    "name_rule",
    "status",
}


def apply_overrides(records, overrides, changes=None):
    """Apply human-verified values on top of every automatic source.

    ``overrides.json`` exists so a conflict between aggregators can be settled
    once, with a link to the vendor doc and the date it was checked, instead of
    leaving the field unknown forever.

    ``excluded`` names models that must not be published at all (no vendor
    price, removed from the catalog). Filtering here, rather than deleting the
    row by hand, means the next sync cannot bring it back.
    """
    changes = changes if changes is not None else []
    excluded = {str(name) for name in (overrides or {}).get("excluded") or []}
    if excluded and records:
        kept = [r for r in records if str(r.get("model_name", "")) not in excluded]
        if len(kept) != len(records):
            changes.extend(
                {"model": name, "field": None, "from": "present", "to": None, "via": "excluded"}
                for name in sorted(excluded)
                if any(str(r.get("model_name", "")) == name for r in records)
            )
            records[:] = kept
    by_name = {str(record.get("model_name", "")): record for record in records}
    applied = 0
    missing = []
    for item in (overrides or {}).get("models", []):
        name = str(item.get("model_name") or "")
        record = by_name.get(name)
        if record is None:
            missing.append(name)
            continue
        for field, value in (item.get("fields") or {}).items():
            if field not in OVERRIDABLE_FIELDS:
                continue
            if record.get(field) == value:
                continue
            changes.append(
                {
                    "model": name,
                    "field": field,
                    "from": record.get(field),
                    "to": value,
                    "via": "override",
                }
            )
            record[field] = value
            applied += 1
    return applied, missing


def ensure_vendors(vendors, models):
    """Append vendor entries referenced by models but missing from vendors.json."""
    known = {str(item.get("name", "")) for item in vendors}
    added = []
    for record in sorted(models, key=lambda item: str(item.get("vendor_name", ""))):
        name = str(record.get("vendor_name", ""))
        if not name or name in known:
            continue
        known.add(name)
        vendors.append(
            {
                "name": name,
                "description": "",
                "icon": str(record.get("icon", "")),
                "status": 1,
            }
        )
        added.append(name)
    return added
