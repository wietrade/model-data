"""一次性脚本：为新登记的多模态图片模型补齐 zh / en 语言包条目。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "api" / "newapi" / "models.json"

DESCRIPTIONS = {
    "zh": {
        "gpt-image-2": "gpt-image-2 图像生成模型",
        "gpt-image-2.5": "gpt-image-2.5 图像生成模型",
        "gpt-image-2.5-flare": "gpt-image-2.5-flare 图像生成模型",
        "gpt-image-medium": "gpt-image-medium 图像生成模型",
        "grok-imagine-image": "grok-imagine-image 图像生成模型",
        "grok-imagine-image-2.0": "grok-imagine-image-2.0 图像生成模型",
        "grok-imagine-image-quality": "grok-imagine-image-quality 图像生成模型",
        "gemini-nano-banana-2.1": "Gemini Nano Banana 2.1 图像生成模型",
    },
    "en": {
        "gpt-image-2": "gpt-image-2 image generation model (served via upstream, billed per image)",
        "gpt-image-2.5": "gpt-image-2.5 image generation model (served via upstream, billed per image)",
        "gpt-image-2.5-flare": "gpt-image-2.5-flare image generation model (served via upstream, billed per image)",
        "gpt-image-medium": "gpt-image-medium image generation model (served via upstream, billed per image)",
        "grok-imagine-image": "grok-imagine-image image generation model (served via upstream, billed per image)",
        "grok-imagine-image-2.0": "grok-imagine-image-2.0 image generation model (served via upstream, billed per image)",
        "grok-imagine-image-quality": "grok-imagine-image-quality image generation model (served via upstream, billed per image)",
        "gemini-nano-banana-2.1": "Gemini Nano Banana 2.1 image generation model (served via upstream, native Gemini protocol)",
    },
}


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    base_rows = base["data"] if isinstance(base, dict) else base
    wanted = {row["model_name"]: row for row in base_rows if row["model_name"] in DESCRIPTIONS["zh"]}

    for lang, descriptions in DESCRIPTIONS.items():
        path = ROOT / "api" / "i18n" / lang / "newapi" / "models.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["data"]
        existing = {row["model_name"] for row in rows}
        added = 0
        for name, description in descriptions.items():
            if name in existing:
                continue
            row = json.loads(json.dumps(wanted[name]))
            row["description"] = description
            rows.append(row)
            added += 1
        payload["data"] = rows
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{lang}: +{added} -> {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
