# corrections/ —— 官方核实层（L2）

这里存的是「**站点说错了什么、官方文档说对的应该是什么**」，与抓取快照分开存放。

## 为什么单独一层

抓取快照（`raw/cheaperinference-<date>.json`）的价值在于**忠实**：它记录站点当时逐字写了什么。
一旦把我们的推断写回快照，这份数据就既不能证明站点说过什么，也不能证明我们查过什么。
所以分三层：

```
L1  raw/cheaperinference-<date>.json            站点原话，一字不改
L2  corrections/cheaperinference-<date>.json    官方核实值 + 出处
L3  raw/cheaperinference-<date>.verified.json   L1 + L2，给下游用
```

L2 是**唯一**允许写入「外部知识」的地方，并且每条都必须能被单独复核。

## 文件格式

```json
{
  "id": "cheaperinference-20261026",
  "source_set": "厂商官方文档（逐条核对，见 source_url）",
  "applies_to": "raw/cheaperinference-20261026.json",
  "compiled_at": "2026-10-26",
  "counts": {"high": 41, "medium": 26},
  "corrections": [
    {
      "id": "claude-haiku-5.5",
      "field": "contextLength",
      "value": 1000000,
      "source_url": "https://platform.claude.com/docs/en/build-with-claude/context-windows",
      "quote": "Claude Haiku 5.5 … have a 1M-token context window",
      "confidence": "high",
      "verified_at": "2026-10-26",
      "reason": "站点把计费档位阈值 100,000 当成了上下文窗口"
    }
  ]
}
```

能力标签用 `add_capabilities` / `remove_capabilities`，不要整表替换
（整表替换会顺手抹掉别的正确标签）：

```json
{
  "id": "nano-banana-2",
  "add_capabilities": ["video-input"],
  "source_url": "https://ai.google.dev/gemini-api/docs/image-generation",
  "quote": "Video-to-image generation (Nano Banana 2.1, 3.1 Flash, and 3.1 Flash Lite)",
  "confidence": "high"
}
```

## 硬性规则

| 规则 | 执行方式 |
|:---|:---|
| 只能改结构化字段 | `apply_corrections.py` 有白名单，`detail_*` 一律拒绝 |
| 必须有 `source_url` | 缺了直接报错退出，不会"先应用再补" |
| 必须有 `quote` | 代码不强校验，但 review 时必看：没有原文引用的条目不算核实 |
| `confidence` 分级 | `high` 才自动应用；`medium`/`low` 进待复核清单 |
| 改完仍违反 `maxOutputTokens <= contextLength` | 逐条列进报告，不许静默通过 |

## confidence 的含义

| 值 | 含义 | 处理 |
|:---|:---|:---|
| `high` | 官方文档明确写出的数值/能力 | 自动应用 |
| `medium` | 有官方依据，但结论含一步推断（如「NIM 示例默认值」「社区模型无官方 max output」） | 默认不应用，人工确认后用 `--min-confidence medium` |
| `low` | 只有聚合站/论坛线索 | 不写入本文件，只进疑点清单 |

## 当前状态（2026-10-26）

- 条目 **131 条**，覆盖 84 个模型；`high` 128 / `medium` 3
- 来源：豆包 138 条核实报告（每条带厂商官方 URL）+ Claude 复核稿中**能对上官方页**的 41 条
- 8 条是读官方**配置文件**直接拿到的，优先于任何二手转述：
  `sentence_bert_config.json` 的 `max_seq_length`（MiniLM-L6 256、MiniLM-L12 128、mpnet 384、
  paraphrase-MiniLM 128、clip-multilingual 128、multi-qa-mpnet 512），CLIP `text_config.max_position_embeddings` 77
- 仍未收录：`detail_Input` 的 46 条 video 漏标（站点侧问题，没有统一修法）、`railOnly`/`costPlus` 语义

## 口径：记模型规格，不记某家部署限额

`contextLength` / `maxOutputTokens` 一律记**模型自身规格**：

- 某个云厂商/网关把 1M 上下文的模型压到 131K，那是它的服务限额，不进这里；
- 站点把计费档位阈值（如 Claude 的 100K 定价分档）当上下文窗口，属于录入错误，修正；
- 站点内部自相矛盾（`maxOutputTokens > contextLength`）时，修到能自洽的一侧；
- 站点把同一个 256K 一边写成十进制 256000、一边写成二进制 262144，统一到二进制值。

反例记录：`gpt-oss-20b` 的 32,768 来自某云厂商部署文档，官方页写的是 131,072 → 采用 131,072。

## 用法

```bash
# 只应用 high，产出 L3
python -m tools.ops.apply_corrections \
    --snapshot raw/cheaperinference-20261026.json \
    --corrections corrections/cheaperinference-20261026.json \
    --out raw/cheaperinference-20261026.verified.json \
    --changelog .tmp/changelog-20261026.csv

# 先看会改哪些、还剩多少矛盾，不落盘
python -m tools.ops.apply_corrections --snapshot ... --corrections ... --dry-run

# 连 medium 一起应用（需要人工逐条过一遍）
python -m tools.ops.apply_corrections --snapshot ... --corrections ... \
    --min-confidence medium --out ...
```
