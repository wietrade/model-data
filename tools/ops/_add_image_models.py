"""一次性脚本：把 upstream 多模态（图片）模型登记进 models.json 目录。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "api" / "newapi" / "models.json"


def entry(model: str, vendor: str, desc: str, icon: str, caps, tags: str) -> dict:
    return {
        "model_name": model,
        "vendor_name": vendor,
        "description": desc,
        "icon": icon,
        "name_rule": 0,
        "status": 1,
        "tags": tags,
        "capabilities": caps,
        "input_modalities": ["text", "image"],
        "output_modalities": ["image"],
        "context_length": 0,
        "max_output_tokens": 0,
        "is_free": False,
        "endpoints": None,
        "lifecycle": "ga",
        "release_date": "",
        "knowledge_cutoff": "",
    }


WANTED = [
    entry("gpt-image-2", "OpenAI", "gpt-image-2", "OpenAI",
          ["image_generation", "vision"], "图像生成"),
    entry("gpt-image-2.5", "OpenAI", "gpt-image-2.5", "OpenAI",
          ["image_generation", "vision"], "图像生成"),
    entry("gpt-image-2.5-flare", "OpenAI", "gpt-image-2.5-flare", "OpenAI",
          ["image_generation", "vision"], "图像生成"),
    entry("gpt-image-medium", "OpenAI", "gpt-image-medium", "OpenAI",
          ["image_generation", "vision"], "图像生成"),
    entry("grok-imagine-image", "xAI", "grok-imagine-image", "Grok",
          ["image_generation"], "图像生成"),
    entry("grok-imagine-image-2.0", "xAI", "grok-imagine-image-2.0", "Grok",
          ["image_generation"], "图像生成"),
    entry("grok-imagine-image-quality", "xAI", "grok-imagine-image-quality", "Grok",
          ["image_generation"], "图像生成"),
    entry("gemini-nano-banana-2.1", "Google", "gemini-nano-banana-2.1", "Gemini.Color",
          ["image_generation", "vision"], "图像生成"),
]


def main() -> int:
    payload = json.loads(MODELS.read_text(encoding="utf-8"))
    rows = payload["data"] if isinstance(payload, dict) else payload
    existing = {row["model_name"] for row in rows}
    added = 0
    for row in WANTED:
        if row["model_name"] in existing:
            print(f"skip existing: {row['model_name']}")
            continue
        rows.append(row)
        added += 1
        print(f"+ {row['model_name']}")
    if isinstance(payload, dict):
        payload["data"] = rows
    else:
        payload = rows
    MODELS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nadded {added}, total {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
