"""Vendor / model-id / capability normalization shared by every source adapter.

The rules here are intentionally the single place where naming differences
between vendors ("claude-haiku-4-5" vs "claude-haiku-4.5" vs
"claude-haiku-4-5-20251001") are reconciled.
"""

from __future__ import annotations

import re

# provider key -> (vendor display name, lobe-icons icon name)
# Icon is only set when the name is known to exist in lobe-icons; an empty
# string is safe (the frontend falls back to a generic icon).
VENDOR_INFO = {
    "anthropic": ("Anthropic", "Claude.Color"),
    "openai": ("OpenAI", "OpenAI"),
    "google": ("Google", "Gemini.Color"),
    "google-vertex": ("Google", "Gemini.Color"),
    "google-ai-studio": ("Google", "Gemini.Color"),
    "deepseek": ("DeepSeek", "DeepSeek.Color"),
    "xai": ("xAI", ""),
    "mistral": ("Mistral", ""),
    "mistralai": ("Mistral", ""),
    "meta": ("Meta", ""),
    "meta-llama": ("Meta", ""),
    "alibaba": ("Alibaba", ""),
    "qwen": ("Alibaba", ""),
    "moonshotai": ("Moonshot AI", "Moonshot"),
    "moonshot": ("Moonshot AI", "Moonshot"),
    "zhipuai": ("Z.AI", "ZAI"),
    "z-ai": ("Z.AI", "ZAI"),
    "cohere": ("Cohere", ""),
    "amazon": ("Amazon", ""),
    "microsoft": ("Microsoft", ""),
    "nvidia": ("NVIDIA", ""),
    "minimax": ("MiniMax", ""),
    "baidu": ("Baidu", ""),
    "bytedance": ("ByteDance", ""),
}

# Closed vocabulary, keep in sync with model/model_metadata_sync.go and
# web/src/features/pricing/constants.ts.
CAPABILITY_ORDER = (
    "chat",
    "reasoning",
    "tools",
    "structured_output",
    "vision",
    "files",
    "audio",
    "image_generation",
    "video_generation",
    "embedding",
    "rerank",
    "web_search",
    "code_interpreter",
    "cache_implicit",
    "cache_explicit",
)

# capabilities that must live in `capabilities[]`; the rest are derived from
# modalities and therefore deliberately not duplicated (see README.md).
CAPABILITIES_FROM_FLAGS = (
    "reasoning",
    "tools",
    "structured_output",
    "web_search",
    "code_interpreter",
    "cache_implicit",
    "cache_explicit",
)

MODALITY_ALIASES = {
    "text": "text",
    "image": "image",
    "images": "image",
    "audio": "audio",
    "video": "video",
    "file": "file",
    "files": "file",
    "pdf": "file",
    "document": "file",
    "documents": "file",
}

_VARIANT_SUFFIX = re.compile(r":(?:free|nitro|extended|online|thinking)$")
_LATEST_SUFFIX = re.compile(r"[-_.]latest$")
# 20251001 / 2025-10-01 / 2025_10_01
_DATE_SUFFIX = re.compile(r"[-_.]?(?:19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}$")


def vendor_info(key):
    """Return (display name, icon) for a provider key."""
    key = (key or "").strip().lower()
    return VENDOR_INFO.get(key, ((key or "").strip(), ""))


def split_model_id(raw):
    """Split ``vendor/model`` into (vendor_key, model_part)."""
    raw = (raw or "").strip()
    if "/" in raw:
        vendor, rest = raw.split("/", 1)
        return vendor.strip().lower(), rest.strip()
    return "", raw


def model_name_from_id(raw):
    """``anthropic/claude-haiku-4-5:free`` -> ``claude-haiku-4-5``."""
    _, rest = split_model_id(raw)
    return _VARIANT_SUFFIX.sub("", rest)


def normalize_key(name):
    """Matching key: lowercase, no vendor prefix, no variant/date suffixes.

    ``claude-haiku-4-5-20251001`` and ``anthropic/claude-haiku-4.5`` both
    normalize to ``claude-haiku-4-5``.
    """
    name = model_name_from_id(name).lower()
    name = _VARIANT_SUFFIX.sub("", name)
    name = _LATEST_SUFFIX.sub("", name)
    name = _DATE_SUFFIX.sub("", name)
    name = name.replace(".", "-").replace("_", "-")
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name


def normalize_modalities(values):
    """Map source modality names onto the closed vocabulary, de-duplicated."""
    out = []
    for value in values or []:
        mapped = MODALITY_ALIASES.get(str(value).strip().lower())
        if mapped and mapped not in out:
            out.append(mapped)
    return out


def capabilities_from_flags(model, family=""):
    """Build the closed capability list from boolean/derived source flags.

    Only decision-relevant keys are emitted: vision/files/audio and
    image/video generation are represented by modalities instead.
    """
    caps = set()
    if model.get("reasoning"):
        caps.add("reasoning")
    if model.get("tool_call") or model.get("tools") or model.get("function_calling"):
        caps.add("tools")
    if (
        model.get("structured_output")
        or model.get("structured_outputs")
        or model.get("response_format")
    ):
        caps.add("structured_output")
    if model.get("web_search"):
        caps.add("web_search")
    if model.get("cache_read") or model.get("cache_implicit"):
        caps.add("cache_implicit")
    if model.get("cache_write") or model.get("cache_explicit"):
        caps.add("cache_explicit")
    if model.get("code_interpreter"):
        caps.add("code_interpreter")

    family = (family or "").lower()
    if "embedding" in family or "embed" in family:
        caps.add("embedding")
    if "rerank" in family or "reranker" in family:
        caps.add("rerank")

    return [cap for cap in CAPABILITY_ORDER if cap in caps]


def is_free_price(price):
    """True when a price map exists and every known component is zero."""
    if not price:
        return None
    known = [value for value in price.values() if value is not None]
    if not known:
        return None
    return all(value == 0 for value in known)
