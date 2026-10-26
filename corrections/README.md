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


## 不核实清单（legacy-20261026.json）

`corrections/legacy-20261026.json` 标记**不再花核实成本**的模型：**快照里仍然保留、字段保留站点原值**，
只是不进 `corrections/`、不派人去查官方文档。

判定只用两条可复核规则（同家族已有更新代且站点在卖 / 官方已下线），每条都写 `superseded_by`：

| 大类 | 条数 | 例子 |
|:---|--:|:---|
| 落后 ≥2 个体系代 | 100 | `gpt-4o`/`gpt-4.1`/`gpt-5`/`gpt-5.1`/`gpt-5.2`、`claude-*-4.x`、`gemini-2.5`/`3.1`、`glm-4.x`、`qwen3`/`qwen3.5`、`kimi-k2`、`deepseek-r1`/`v3`、`grok-4.1`/`4.20`、`mistral-*`（old）、`llama-*`、`nova-*`、`flux-1/2`、`recraft-v2/v3` |

不按代际判老的例外：ASR / TTS / 转写 / OCR / embedding / image / video 这些**专用模型版本节奏不同**，
以及名字带 `next` 的（如 `qwen3-coder-next`）。

效果：417 条未核实里剔掉 100 条，剩 317；其中真正有 token 数值、值得核的是 **213** 条（其余 104 条两个数值都是 null，只涉及能力/厂商）。

## 核实范围（scope-20261026.json）

`python -m tools.ops.classify_scope -o corrections/scope-20261026.json` 给 527 条全部定档，
每个模型一个 tier，可随时重跑：

| tier | 条数 | 含义 |
|:---|--:|:---|
| `done` | 115 | 已有官方核实条目 |
| `legacy` | 100 | 老代，不再核实（见上节） |
| `main` | 210 | **主流厂商，缺数据也必须核**（其中 44 条目前有缺口） |
| `ignore` | 48 | **非主流 + 缺数据 ⇒ 直接忽略** |
| `review` | 40 | 非主流但信息齐全（站点数据够用，不另行核实） |
| `media` | 14 | 非主流图像/视频/语音，信息齐全 |

主流名单写在 `tools/ops/classify_scope.py` 的 `VENDOR_RULES`（第三个字段为 True）：
OpenAI、Anthropic、Google、xAI、Meta、Mistral、Cohere、Perplexity、NVIDIA，
以及 DeepSeek、通义（含 Wan）、Kimi、智谱、字节 Seed、腾讯混元、文心、MiniMax、零一、阶跃、小米、蚂蚁 Ling、美团 LongCat、快手可灵、FLUX、Microsoft。

「缺数据」= 下列任一：
- `text`/`realtime`/`decision` 缺 `contextLength` 或 `maxOutputTokens`；`embedding` 缺 `contextLength`
- `detail_Input` / `detail_Output` / `detail_SupportedParameters` 三项全为 `Not reported`

**视频/语音/转写/图像本来就没有上下文窗口**，站点显示 `Not reported` 属于字段不适用，不记为数值缺口。

`e2ee-` / `uncensored-` / `venice-` 前缀的转售型号算非主流（基座厂商不打折）。

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
