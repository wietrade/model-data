"""Source adapters.

Two families of sources are supported:

* **aggregators** (public, no credentials) provide factual metadata and list
  prices in one place: ``models.dev`` and ``openrouter``.
* **official APIs** (need credentials) are authoritative about which model ids
  exist for a vendor, but expose little metadata. They are used to discover
  models the aggregators missed and to warn about stale entries.

Adding a source means adding one ``SourceModel`` producer; the merge logic and
the output schema stay untouched.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .normalize import (
    capabilities_from_flags,
    is_free_price,
    model_name_from_id,
    normalize_modalities,
    normalize_key,
    split_model_id,
    vendor_info,
)

USER_AGENT = "new-api-metadata-sync/1.0 (+https://github.com/wietrade/new-api)"
MAX_BYTES = 32 << 20

MODELS_DEV_URL = "https://models.dev/api.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"

OFFICIAL_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models?limit=1000",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
}

OFFICIAL_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
}


@dataclass
class SourceModel:
    """One model as reported by a single source, already normalized."""

    vendor_key: str
    source: str
    source_id: str
    model_name: str
    vendor_name: str
    icon: str
    description: str = ""
    capabilities: list = field(default_factory=list)
    input_modalities: list = field(default_factory=list)
    output_modalities: list = field(default_factory=list)
    context_length: int = 0
    max_output_tokens: int = 0
    release_date: str = ""
    price: dict = field(default_factory=dict)  # USD per 1M tokens

    @property
    def key(self):
        return normalize_key(self.model_name)

    @property
    def is_free(self):
        return is_free_price(self.price)


def _get_json(url, timeout=30, headers=None):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("%s: response larger than %d bytes" % (url, MAX_BYTES))
    return json.loads(raw.decode("utf-8"))


def _per_million(value):
    """Convert a per-token string/number into USD per 1M tokens."""
    if value in (None, ""):
        return None
    try:
        return round(float(value) * 1_000_000, 6)
    except (TypeError, ValueError):
        return None


def _timestamp_to_date(value):
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def _clean_price(price):
    return {k: v for k, v in price.items() if v is not None}


# ---------------------------------------------------------------- aggregators


def fetch_models_dev(vendors, timeout=30):
    """https://models.dev/api.json -> list[SourceModel]."""
    payload = _get_json(MODELS_DEV_URL, timeout=timeout)
    if not isinstance(payload, dict):
        raise ValueError("models.dev: unexpected payload (expected object)")

    out = []
    for vendor_key in vendors:
        provider = payload.get(vendor_key)
        if not isinstance(provider, dict):
            continue
        models = provider.get("models") or {}
        if not isinstance(models, dict):
            continue
        for model_id, model in models.items():
            if not isinstance(model, dict):
                continue
            name = model_name_from_id(model.get("canonical_model_id") or model_id)
            if not name:
                continue
            modalities = model.get("modalities") or {}
            limits = model.get("limit") or {}
            cost = model.get("cost") or {}
            vendor_name, icon = vendor_info(vendor_key)
            price = _clean_price(
                {
                    "input": cost.get("input"),
                    "output": cost.get("output"),
                    "cache_read": cost.get("cache_read"),
                    "cache_write": cost.get("cache_write"),
                }
            )
            out.append(
                SourceModel(
                    vendor_key=vendor_key,
                    source="models.dev",
                    source_id=model.get("canonical_model_id") or model_id,
                    model_name=name,
                    vendor_name=vendor_name,
                    icon=icon,
                    description=(model.get("description") or "").strip(),
                    capabilities=capabilities_from_flags(
                        model, model.get("family") or ""
                    ),
                    input_modalities=normalize_modalities(modalities.get("input")),
                    output_modalities=normalize_modalities(modalities.get("output")),
                    context_length=int(limits.get("context") or 0),
                    max_output_tokens=int(limits.get("output") or 0),
                    release_date=(model.get("release_date") or "")[:10],
                    price=price,
                )
            )
    return out


def fetch_openrouter(vendors, timeout=30):
    """https://openrouter.ai/api/v1/models -> list[SourceModel]."""
    payload = _get_json(OPENROUTER_URL, timeout=timeout)
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("openrouter: unexpected payload (expected data[])")

    wanted = set(vendors)
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "")
        if ":" in raw_id:  # skip :free / :nitro variants, keep the paid base id
            continue
        vendor_key, _ = split_model_id(raw_id)
        if vendor_key not in wanted:
            continue
        name = model_name_from_id(item.get("canonical_slug") or raw_id)
        if not name:
            continue
        architecture = item.get("architecture") or {}
        pricing = item.get("pricing") or {}
        top_provider = item.get("top_provider") or {}
        vendor_name, icon = vendor_info(vendor_key)

        params = set(item.get("supported_parameters") or [])
        price = _clean_price(
            {
                "input": _per_million(pricing.get("prompt")),
                "output": _per_million(pricing.get("completion")),
                "cache_read": _per_million(
                    pricing.get("input_cache_read")
                    or pricing.get("cache_read")
                ),
                "cache_write": _per_million(
                    pricing.get("input_cache_write")
                    or pricing.get("cache_write")
                ),
            }
        )
        out.append(
            SourceModel(
                vendor_key=vendor_key,
                source="openrouter",
                source_id=raw_id,
                model_name=name,
                vendor_name=vendor_name,
                icon=icon,
                description=(item.get("description") or "").strip(),
                capabilities=capabilities_from_flags(
                    {
                        "reasoning": "reasoning" in params
                        or bool(item.get("reasoning")),
                        "tools": "tools" in params or "tool_choice" in params,
                        "structured_output": bool(
                            {"structured_outputs", "response_format"} & params
                        ),
                        # A published per-token price means the vendor bills
                        # cache reads/writes, i.e. the feature is supported.
                        "web_search": "web_search" in params
                        or bool(pricing.get("web_search")),
                        "cache_read": bool(pricing.get("input_cache_read")),
                        "cache_write": bool(pricing.get("input_cache_write")),
                    },
                    item.get("id") or "",
                ),
                input_modalities=normalize_modalities(
                    architecture.get("input_modalities")
                ),
                output_modalities=normalize_modalities(
                    architecture.get("output_modalities")
                ),
                context_length=int(
                    item.get("context_length") or top_provider.get("context_length") or 0
                ),
                max_output_tokens=int(top_provider.get("max_completion_tokens") or 0),
                release_date=_timestamp_to_date(item.get("created")),
                price=price,
            )
        )
    return out


# ------------------------------------------------------------- official APIs


def fetch_official(vendors, environ, timeout=30):
    """Query vendor model-list APIs; returns only ids (+ limits when known).

    Missing credentials simply skip that vendor: official APIs are a
    completeness check, never the sole source of truth for a deploy.
    """
    out = []
    for vendor_key in vendors:
        env_key = OFFICIAL_ENV_KEYS.get(vendor_key)
        api_key = (environ.get(env_key) or "").strip() if env_key else ""
        if not api_key:
            continue
        try:
            if vendor_key == "openai":
                out.extend(_official_openai(api_key, timeout))
            elif vendor_key == "anthropic":
                out.extend(_official_anthropic(api_key, timeout))
            elif vendor_key == "google":
                out.extend(_official_google(api_key, timeout))
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            print("warn: official %s list unavailable: %s" % (vendor_key, exc))
    return out


def _official_model(vendor_key, model_id, display_name="", context_length=0,
                    max_output_tokens=0):
    vendor_name, icon = vendor_info(vendor_key)
    return SourceModel(
        vendor_key=vendor_key,
        source="official:%s" % vendor_key,
        source_id=model_id,
        model_name=model_name_from_id(model_id),
        vendor_name=vendor_name,
        icon=icon,
        description=display_name,
        context_length=int(context_length or 0),
        max_output_tokens=int(max_output_tokens or 0),
    )


def _official_openai(api_key, timeout):
    payload = _get_json(
        OFFICIAL_ENDPOINTS["openai"],
        timeout=timeout,
        headers={"Authorization": "Bearer " + api_key},
    )
    return [
        _official_model("openai", item.get("id", ""))
        for item in payload.get("data", [])
        if item.get("id")
    ]


def _official_anthropic(api_key, timeout):
    payload = _get_json(
        OFFICIAL_ENDPOINTS["anthropic"],
        timeout=timeout,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    return [
        _official_model(
            "anthropic", item.get("id", ""), item.get("display_name") or ""
        )
        for item in payload.get("data", [])
        if item.get("id")
    ]


def _official_google(api_key, timeout):
    payload = _get_json(
        OFFICIAL_ENDPOINTS["google"] + "?key=" + api_key,
        timeout=timeout,
    )
    out = []
    for item in payload.get("models", []):
        name = str(item.get("name") or "")
        if name.startswith("models/"):
            name = name[len("models/"):]
        if not name:
            continue
        out.append(
            _official_model(
                "google",
                name,
                item.get("displayName") or "",
                item.get("inputTokenLimit") or 0,
                item.get("outputTokenLimit") or 0,
            )
        )
    return out


SOURCES = {
    "models.dev": fetch_models_dev,
    "openrouter": fetch_openrouter,
}


def collect(sources, vendors, timeout=30, environ=None, official=False):
    """Fetch every enabled source, higher priority first.

    Returns ``(incoming, errors, stats)`` where ``incoming`` is a list of
    SourceModel ordered by source priority.
    """
    incoming = []
    errors = []
    stats = {}

    for name in sources:
        fetcher = SOURCES.get(name)
        if fetcher is None:
            errors.append("unknown source: %s" % name)
            continue
        try:
            models = fetcher(vendors, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - one bad source must not abort
            errors.append("%s: %s" % (name, exc))
            continue
        stats[name] = len(models)
        incoming.extend(models)

    if official:
        models = fetch_official(vendors, environ or {}, timeout=timeout)
        stats["official"] = len(models)
        incoming.extend(models)

    return incoming, errors, stats
