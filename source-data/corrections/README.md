# corrections/ —— 官方核实层（L2）

这里存的是「**站点说错了什么、官方文档说对的应该是什么**」，与抓取快照分开存放。

## 目录约定：按快照隔离

一次抓取一套，放在 `source-data/corrections/<YYYYMMDD>/` 下；`README.md`（本文件）是跨快照的口径，不随日期变：

```
corrections/
├── README.md              口径文档（本文件）
└── 20261026/
    ├── corrections.json   L2 核实值（162 条，不可再生）
    ├── routing.json       上游路由事实（servedAs / retiredAt，人工查证）
    ├── legacy.json        老代不核实清单（101 条，mark_legacy.py 生成）
    └── changelog.csv      变更表（apply_corrections 生成）
```

`scope.json`（527 条定档结果）是纯派生物，**不入库**，需要时随时重跑：

```bash
python -m tools.ops.classify_scope -o /tmp/scope.json
```

三个工具都支持 `--date`，不传则自动取 `source-data/corrections/` 下最新一期：

```bash
python -m tools.ops.apply_corrections --date 20261026
python -m tools.ops.classify_scope    --date 20261026
python tools/ops/mark_legacy.py       --date 20261026
```

## 为什么单独一层

> **这一层只管模型元数据**（上下文、最大输出、能力、生命周期、路由）。
> 价格不在这里，也不该在这里：官方价在 `reference-data/price/pricing.official.json`，
> 我们自己的结算价在私有目录。第三方站点的价格字段在抓取阶段就被剔除了。

抓取快照（`source-data/cheaperinference-<date>.json`）的价值在于**忠实**：它记录站点当时逐字写了什么。
一旦把我们的推断写回快照，这份数据就既不能证明站点说过什么，也不能证明我们查过什么。
所以分三层：

```
L1  source-data/cheaperinference-<date>.json            站点原话，一字不改
L2  source-data/corrections/<date>/corrections.json         官方核实值 + 出处
L3  source-data/cheaperinference-<date>.verified.json   L1 + L2，给下游用
```

L2 是**唯一**允许写入「外部知识」的地方，并且每条都必须能被单独复核。

## 文件格式

```json
{
  "id": "cheaperinference-20261026",
  "source_set": "厂商官方文档（逐条核对，见 source_url）",
  "applies_to": "source-data/cheaperinference-20261026.json",
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

## 当前状态（2026-10-26 那一期）

- 条目 **162 条**，覆盖 **116 个模型**；`confidence` 实测 `high` 159 / `medium` 3
  （文件头 `counts` 里写的 153/3 是生成时的旧值，以条目实际内容为准）
- 来源构成 `origin`：`ours` 107（我方逐页核对官方文档）、`claude` 41、`override` 8
  （直接读官方配置文件）、`claude-batch2` 6
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

`source-data/corrections/20261026/legacy.json` 标记**不再花核实成本**的模型：**快照里仍然保留、字段保留站点原值**，
只是不进 `corrections.json`、不派人去查官方文档。

判定只用两条可复核规则（同家族已有更新代且站点在卖 / 官方已下线），每条都写 `superseded_by`：

| 大类 | 条数 | 例子 |
|:---|--:|:---|
| 落后 ≥2 个体系代 / 上游已下线 | 101 | `gpt-4o`/`gpt-4.1`/`gpt-5`/`gpt-5.1`/`gpt-5.2`、`claude-*-4.x`、`gemini-2.5`/`3.1`、`glm-4.x`、`qwen3`/`qwen3.5`、`kimi-k2`、`deepseek-r1`/`v3`、`grok-4.1`/`4.20`、`mistral-*`（old）、`llama-*`、`nova-*`、`flux-1/2`、`recraft-v2/v3` |

不按代际判老的例外：ASR / TTS / 转写 / OCR / embedding / image / video 这些**专用模型版本节奏不同**，
以及名字带 `next` 的（如 `qwen3-coder-next`）。

效果：411 条未核实里剔掉 101 条，剩 310 条。

其中 2 条是「上游已下线、站点仍在卖」而非代际落后，优先于家族规则判定：`mimo-v2.5`（小米 2026-10-21 下线）、`grok-code-fast-1`（xAI 2026-05-15 退役转发 grok-build-0.1）；同理 `grok-4.1-fast-*` 的取代目标已改为 grok-4.3。

## 两个口径：模型规格 vs 站点实际服务

`contextLength` / `maxOutputTokens` 一律记 **模型自身规格**（有官方出处、可引用、不随上游路由变化）。
同一句话在三个地方可能给出三个数，以规格为准：

| 模型 | 站点原文 `detail_ContextWindow` | 官方规格 | 站点实际服务 |
|:---|:---|:---|:---|
| `grok-4` | 2,000,000 | 256,000（grok-4-0709） | 1,000,000 —— xAI 2026-05-15 退役后转发到 grok-4.3 |
| `gemma-3-27b-it` | 40,000 | 131,072（Google 模型卡） | 某部署截断到 40,000 |
| `claude-haiku-5.5` | 100,000 | 1,000,000 | 1,000,000（站点少打一个 0） |

「站点实际服务」不写进主字段，另存 `source-data/corrections/<date>/routing.json`，应用后成为 L3 的
`servedAs` / `retiredAt` 两个附加键：

```bash
python -m tools.ops.apply_corrections --date 20261026
```

为什么不混进 `contextLength`：上游路由随时会改，写进主字段会让同一个模型的值反复漂移，
且无法再引用任何一个官方页面作为出处。`servedAs` 是提示性的，`contextLength` 是 可引用的。

## 核实范围

`python -m tools.ops.classify_scope` 给 527 条全部定档，
每个模型一个 tier，可随时重跑：

| tier | 条数 | 含义 |
|:---|--:|:---|
| `done` | 116 | 已有官方核实条目 |
| `legacy` | 101 | 老代 / 上游已下线，不再核实（见上节） |
| `main` | 208 | **主流厂商，缺数据也必须核**（其中 44 条目前有缺口） |
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
# 最常用：一条命令走完整套（路径按日期自动推导）
python -m tools.ops.apply_corrections --date 20261026

# 等价于
python -m tools.ops.apply_corrections \
    --snapshot source-data/cheaperinference-20261026.json \
    --corrections source-data/corrections/20261026/corrections.json \
    --routing source-data/corrections/20261026/routing.json \
    --out source-data/cheaperinference-20261026.verified.json \
    --changelog source-data/corrections/20261026/changelog.csv

# 先看会改哪些、还剩多少矛盾，不落盘
python -m tools.ops.apply_corrections --date 20261026 --dry-run

# 连 medium 一起应用（需要人工逐条过一遍）
python -m tools.ops.apply_corrections --date 20261026 --min-confidence medium

# 看核实范围：哪 208 条要核、哪 48 条可忽略
python -m tools.ops.classify_scope
python -m tools.ops.classify_scope --list ignore

# 老代清单（派生）
python tools/ops/mark_legacy.py
```

## 聚合站的典型伪值：943,718 / 0.9× / `max_completion_tokens`

聚合站会把**思考预算**或**折算值**当成 `max_output_tokens` 写进目录，实例：

| 模型 | 聚合站给的 max | 官方实际 |
|:---|---:|---:|
| `gemini-3.8-flash-tiered` | 943,718 | 该模型并不存在（3.8 Flash 平价，无分档版） |
| `deepseek-v4.1-flash` | 943,718 | 384,000（官方「输出最大 384K」） |
| 多个 OpenAI 模型 | 58,982 一类 | 官方 65,536（聚合站做了 0.9× 折算） |

判断方法：看到 `943,718` / `0.9×` 折算值 / `max_completion_tokens` 这类数字，
**先当聚合站伪值处理**，回官方页确认后再落盘。

## 三个容易记错的字段口径

**embedding 模型**：站点把最大输入填进了 `maxOutputTokens`（如 `bge-m3` 两个字段都是 8,192）。
embedding 没有「输出 token」，输出是向量 → `maxOutputTokens` 一律 `null`，输入上限记在 `contextLength`。

**`detail_Provider` ≠ `providerLabel`**：详情页的 Provider 是**卖方/上游**（Venice AI、SpaceXAI 之类），
不是模型开发方。`providerLabel` 记开发方（OpenAI、Anthropic、ByteDance…），站点原文留在 `detail_Provider`。
已修 12 条，例如 `tts-1` / `whisper-1` 站点写 "Venice AI"，实际是 OpenAI。

**布尔值映射**：`detail_VisionInput` 这类字段——

| 站点写法 | 含义 | 转为 |
|:---|:---|:---|
| `Supported` | 支持 | `true` |
| `Not supported` | 不支持 | `false` |
| `Not reported` | 站点没报 | `null` |

## 站点侧已知问题（照实记录，不去猜）

| 问题 | 数量（2026-10-26 快照） | 处理 |
|:---|:---|:---|
| `detail_Input` / `detail_Output` 为 `Not reported` | 125 / 125 | 保留；用 `capabilities` 表达能力 |
| `detail_SupportedParameters` 为 `Not reported` | 255 | 保留 |
| 端点写占位符 `None has passed a live request yet` | 4 | 转为 `null` |
| `servedAt` 为 `null`（无人调用过） | 57 | 保留 |
| `providerSlug` / `costPlus` 为 `null` | 250 / 451 | 保留 |
| `vision: true` 但 Input 里没有 image | 48 | 两处都留，冲突登记 |
| 有 `video-input` 标签但 Input 里没有 video | 68 | 同上 |

> **站点数据是动态计算的。** 相隔 20 分钟的两次抓取，有 9 处不同
> （`capabilities` 6 处、`detail_Endpoints` 3 处）——端点和能力按近期真实流量算出来。
> 所以：每次核实必须绑定一个**具体快照**；跨快照比较时这两个字段的差异
> **不能当成错误**。

## 验收清单（每批新修正必须全部通过）

1. `detail_*` 零改动 —— 动了就是废掉证据链，直接打回
2. 每条都有 `source_url`，且是官方域名（第三方只能标 `third-party`，不能进 `high`）
3. `expected_old` 必须等于当前 L1 的实际值（防止上游已变、修正在改空气）
4. 不得引入 `maxOutputTokens > contextLength`
5. 不得自造枚举值（`"embedding"`、`"Realtime (speech-to-speech)"` 这类站点没出现过的字符串）
6. `providerLabel` 必须是模型开发方，不是转售方
7. 拿不准的一律进 `pending`，不允许用 `low` 置信度硬写盘
8. 聚合站的值不得覆盖任何官方值；冲突时以官方为准并在备注记下差异
9. 不得出现 `943,718` / `0.9×` 折算值 / `max_completion_tokens` 这类聚合站伪值

> 这套闸门在第一轮拦下过一批问题：518 处 `detail_*` 被覆盖、新增 `maxOutputTokens > contextLength`、
> 靠「多数投票」删掉官方确认支持的能力、以及 449 条 `costPlus: false` 的凭空猜测。
