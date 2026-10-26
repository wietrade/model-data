# cheaperinference 模型数据核实报告

**日期**：2026-10-26　**快照**：`source-data/cheaperinference-20261026.json`　**站点**：`platform.cheaperinference.com`

**成品数据**：`source-data/cheaperinference-20261026.verified.json`（618 KB，527 条 × 29–31 键）

> **时效**：本报告描述的是 2026-10-26 这一期快照。§2（数字统计）与 §3（核实范围）在下次抓取后
> 会变；§4（口径）与 §8（验收清单）跨期有效，可直接给外部核实方用。
> 复核命令：`python -m tools.ops.classify_scope --date 20261026`。

---

## 0. 一句话结论

站点 527 个模型的全部字段已抓取入库，其中 **116 个**逐字段对照官方文档核过并落盘（162 条核实条目，157 处生效）；
**101 个**判为老代不再核实；**48 个**非主流模型因信息残缺直接忽略；剩下 **208 个主流模型**待核，其中目前真正缺数据的只有 **44 个**。

---

## 1. 数据流水线

分三层，职责严格隔离，任何一步出问题都能回退：

```
L1  source-data/cheaperinference-20261026.json             站点原话，detail_* 一字不改
        │  ↑ 抓取自服务端渲染页面（RSC payload），527 条 × 29 键
        │
L2  corrections/20261026/corrections.json          162 条官方核实值（带 source_url / 原文引用）
    corrections/20261026/routing.json              7 条上游路由（servedAs / retiredAt）
        │
L3  source-data/cheaperinference-20261026.verified.json    L1 + L2，供下游消费
```

### 为什么必须分三层

`detail_*` 是**唯一不可再生的数据**——它是站点当时到底写了什么的证据。一旦被"修正后的值"覆盖：

- 站点的原话永久丢失，事后无法判断是站点错了还是我们改错了；
- 抓取器自检失效：原本靠"原文 `'128,000 tokens'` 解析后是否等于数值字段"来验证解析正确性，两边都改成同一个值后这个检查就恒真了。

所以 `detail_*` 只读，修正只作用于我们自己的结构化字段。

### 文件清单

| 文件 | 内容 | 条数 |
|:---|:---|---:|
| `source-data/...20261026.json` | L1 站点原文 | 527 |
| `corrections/20261026/corrections.json` | L2 核实值（**不可再生**） | 162 |
| `corrections/20261026/routing.json` | 上游路由（人工查证） | 7 |
| `corrections/20261026/legacy.json` | 老代不核实清单（派生） | 101 |
| `corrections/20261026/changelog.csv` | 变更表（派生） | 168 |
| `corrections/README.md` | 口径文档 | — |
| `source-data/...20261026.verified.json` | L3 成品 | 527 |
| `tools/ops/fetch_site.py` | L1 生产者（带自检） | — |
| `tools/ops/apply_corrections.py` | L2 → L3 | — |
| `tools/ops/classify_scope.py` | 核实范围划分（`scope.json` 纯派生，不入库） | — |
| `tools/ops/mark_legacy.py` | 老代清单生成 | — |

---

## 2. 核实结果

### 2.1 应用情况

```
162 条核实条目
 ├─ 151 条直接改写字段
 ├─   6 条派生：contextLength 改动后同步 context-128k / context-1m 标签
 │      claude-haiku-5.5、minimax-m3、nemotron-3.5-super-vl、gemini-3-flash（补上 context-1m）
 │      grok-4（去掉 context-1m）、gemma-3-27b-it（补上 context-128k）
 ├─   8 条核对后确认站点原值已正确，无需改动
 │      gpt-oss-20b/120b、glm-4.7、kimi-k3、nemotron-nano-9b-v2 的 maxOutput
 │      gemini-omni-flash-preview、minimax-m3、nano-banana-2 的能力标签已在
 └─   3 条 medium 暂不落盘（待人工过目）
        flux-kontext-max / flux-kontext-pro 上下文 512
        nemotron-3.5-super-vl 最大输出 16,384

共写入 L3：157 行字段变更 + 11 行路由标注
```

**硬性检查全部通过**：

| 检查项 | 结果 |
|:---|:---|
| `detail_*` 是否被改动 | 0 处 |
| 修正是否都有 `source_url` | 162/162 |
| 是否引入新的 `maxOutputTokens > contextLength` | 0 条 |
| `context-*` 标签与 `contextLength` 是否一致 | 0 处不一致 |
| 数据里是否存在自相矛盾的 token 数值 | 0 条 |
| 单元测试 | 144 个全过 |

### 2.2 按字段统计

| 字段 | 条目数 | 说明 |
|:---|---:|:---|
| `contextLength` | 57 | 上下文窗口 |
| `maxOutputTokens` | 49 | 最大输出 |
| `reasoning` | 29 | 是否支持推理/思考模式 |
| `providerLabel` | 12 | 站点写的是**转售方**，改成实际开发方 |
| 能力标签增删 | 14 | `video-input` 8、`reasoning` 4、`image-input` 2 |
| `vision` | 1 | `o3-mini` 实际不支持图像输入 |

### 2.3 来源构成

| 来源 | 条数 | 含义 |
|:---|---:|:---|
| `ours` | 107 | 我方逐页核对官方文档 |
| `claude` | 41 | Claude 第一批核实 |
| `override` | 8 | 直接读官方配置文件（`sentence_bert_config.json`、`config.json`） |
| `claude-batch2` | 6 | Claude 第二批核实 |

### 2.4 改动幅度最大的几条

**上下文窗口**（22 条被改）：

| 模型 | 站点值 | 改为 | 依据 |
|:---|---:|---:|:---|
| `grok-4` | 2,000,000 | 256,000 | grok-4-0709 规格（站点虚高 8 倍） |
| `claude-haiku-5.5` | 100,000 | 1,000,000 | Anthropic 官方（站点少打一个 0） |
| `minimax-m3` | 200,000 | 1,000,000 | MiniMax 官方 1M |
| `gemini-3-flash` | 256,000 | 1,048,576 | Google 官方 |
| `nemotron-3.5-super-vl` | 262,144 | 1,048,576 | 官方 |
| `gpt-5.2` | 256,000 | 400,000 | OpenAI 官方 |
| `gemma-3-27b-it` | 40,000 | 131,072 | Google 模型卡（40K 是某部署截断值） |
| `qwen3-next-80b-a3b-instruct` | 256,000 | 131,072 | 官方（站点虚高） |

**最大输出**（15 条被改）：

| 模型 | 站点值 | 改为 | 依据 |
|:---|---:|---:|:---|
| `glm-5.3-flash` | 1,048,576 | 131,072 | Z.ai 官方 128K |
| `glm-5.3` | 1,000,000 | 131,072 | Z.ai 官方 128K |
| `deepseek-v4-flash-vision-exp` | 1,048,576 | 393,216 | 站点写的比上下文还大，自相矛盾 |
| `minimax-m3.1-flash` | 1,048,576 | 524,288 | 官方 |
| `qwen3-vl-235b-a22b-instruct` | 262,144 | 32,768 | 官方 |
| `gpt-oss-20b` | **32,768** | 131,072 | OpenAI 官方（32,768 是某云部署值，不是模型规格） |

> `gpt-oss-20b` 这条值得单独说：豆包最初抓的 `32,768` 并非录入错误，而是某个云厂商的部署限额。这说明**第三方站点上的数字不一定错，但一定不是"模型规格"**——必须回官方查。

---

## 3. 核实范围划分

527 条全部定档。机器可读结果由 `classify_scope` 现算，**不存库**（纯派生，快照一换就过期）：

```bash
python -m tools.ops.classify_scope                    # 打摘要
python -m tools.ops.classify_scope --list ignore      # 列某一档
python -m tools.ops.classify_scope -o /tmp/scope.json # 需要时才落盘
```

| 档位 | 条数 | 含义 |
|:---|---:|:---|
| `done` | 116 | 已有官方核实条目 |
| `legacy` | 101 | 老代 / 上游已下线，不再投入核实成本 |
| `main` | 208 | **主流厂商，缺数据也必须核**（其中 44 条目前有缺口） |
| `ignore` | 48 | **非主流 + 信息残缺 ⇒ 直接忽略** |
| `review` | 40 | 非主流但信息齐全，站点数据够用 |
| `media` | 14 | 非主流图像/视频/语音，信息齐全 |

### 3.1 主流厂商名单

**海外**：OpenAI、Anthropic、Google、xAI、Meta、Mistral、Cohere、Perplexity、NVIDIA
**国产**：DeepSeek、通义（含 Wan）、Kimi、智谱、字节 Seed、腾讯混元、文心、MiniMax、零一、阶跃、小米、蚂蚁 Ling、美团 LongCat、快手可灵、FLUX、Microsoft

带 `e2ee-` / `uncensored-` / `venice-` 前缀的转售壳子**不算主流**（基座是主流，但转售方不是）。

### 3.2 老代模型（101 条，不核实）

判定只用两条可复核规则，每条都写了 `superseded_by`：

1. 同家族已有更新代，且站点确实在卖更新代；
2. 官方已下线 / 退役。

| 被谁取代 | 条数 | 代表 |
|:---|---:|:---|
| `gpt-6.1` 系列 | 23 | `gpt-4o`、`gpt-4.1`、`gpt-5`、`gpt-5.1`、`gpt-5.2` |
| `qwen3.8` 系列 | 13 | `qwen3-14b`、`qwen3-235b`、`qwen3-coder`、`qwen3.5-*` |
| 站点无更新代但明显落后 | 10 | `llama-3.x/4`、`nova-lite/micro/pro` |
| `grok-4.7` | 7 | `grok-4.1-fast-*`、`grok-4.20-*` |
| `claude-*-5.5` | 6 | `claude-haiku-4.5`、`claude-opus-4.6/4.7/4.8` |
| `glm-5.3` | 5 | `glm-4.5`、`glm-4.6`、`glm-4.7-flashx` |
| `mistral-large-4` | 5 | `mistral-large`、`nemotron`、`small` |
| 其他 | 32 | `deepseek-r1`/`v3`、`gemini-2.5`/`3.1`、`gemma-3`、`kimi-k2`、`flux-1/2`、`recraft-v2/v3` 等 |

**特意排除的**：ASR / TTS / 转写 / OCR / embedding / image / video 这些专用模型（版本节奏与对话模型不同），以及名字带 `next` 的（如 `qwen3-coder-next` 是新一代）。

### 3.3 忽略清单（48 条）

判据：**非主流 + 至少有一项关键信息缺失**。缺失分两类：

- **数值缺失**：`text`/`realtime`/`decision` 缺 `contextLength` 或 `maxOutputTokens`；`embedding` 缺 `contextLength`
- **描述缺失**：`detail_Input` / `detail_Output` / `detail_SupportedParameters` 三项全为 `Not reported`

| 类别 | 条数 | 例子 |
|:---|---:|:---|
| 转售壳子（e2ee / uncensored / venice） | 12 | `e2ee-qwen3.6-35b-a3b`、`uncensored-wan-2.7`、`venice-uncensored-1.2` |
| 小众决策模型 | 9 | `d1`、`jev`、`laya`、`mammoth-1`、`elephant-1` |
| 小众视频/图像/语音 | 20 | `kling` 系、`wan-2.6/2.7`、`tts-orpheus`、`luma-uni-1` |
| 小众文本模型 | 7 | `aion-3.0`、`macaron-v1-*`、`moondream3`、`wizardlm-2-8x22b` |

> **注意**：忽略 ≠ 删除。这 48 条的站点数值和 `detail_*` 都完整保留在 L1/L3 里，只是不再派人去查官方文档。以后要用，从清单里摘掉重核即可。

### 3.4 主流缺口（44 条，下一步的目标）

**A. 缺数值（15 条）**

| 模型 | 缺什么 |
|:---|:---|
| `gpt-realtime-2` / `-mini` / `-1.5` | context + max output |
| `gpt-live-1` | context + max output |
| `gemini-3.8-live` / `-extended-thinking` | context + max output |
| `grok-voice-3.0` / `grok-voice-think-fast-2.0` | context + max output |
| `text-embedding-005`、`gemini-embedding-2`、`codestral-embed`、`text-multilingual-embedding-002` | context（embedding 输入上限） |
| `gpt-6-luna-decisions`、`pplx-decider-v1.2`、`pplx-decider-flash-v1.2` | max output |

**B. 站点连模态都没填（29 条）**

`gpt-6-sol-pro`、`gpt-6.1-sol-pro`、`gpt-6-luna-pro`、`grok-imagine-quality`、`qwen3-asr-*`、`qwen-image-2.1-turbo`、`qwen-mt-plus`、`tts-qwen3-*`、`tts-gemini-3-1-flash`、`seed-2.0-code`、`longcat`、`deepseek-ocr-2`、`whisper-large-v3-turbo`、`xai-stt-v1` 等。

---

## 4. 口径定义

### 4.0 数据源优先级：官方是权威，聚合站最低

任何字段冲突都按下面这条链裁决，**不存在"两边都记录一下"的中间态**：

```
人工钉值（overrides）
    ↓ 高于
厂商官方逐模型页 / 官方 API
    ↓ 高于
厂商官方定价页 / 官方托管页（如 Google Cloud）
    ↓ 高于
聚合站（models.dev、openrouter 等）—— 最低优先，只补缺口
```

- **聚合站只能在官方没有数据时补位**，不得覆盖任何官方值；
  标 `price_kind: aggregator_reference` / `confidence: medium`，不能进 `high`。
- 官方源之间互相矛盾时**不猜**，回落到既定的次选口径，并把分歧记进备注。
- 聚合站给出的数一旦与官方冲突，**以官方为准，并把差异记下来**——差异本身就是情报。

#### 各厂商的官方源

| 厂商 | 元数据（上下文 / 最大输出 / 模态） | 价格 |
|:---|:---|:---|
| OpenAI | `developers.openai.com/api/docs/models/<id>.md` | `developers.openai.com/api/docs/pricing.md` |
| Anthropic | `platform.claude.com/docs/en/models/<slug>/overview.md` | `platform.claude.com/docs/en/about-claude/pricing.md` |
| **Google** | `ai.google.dev/gemini-api/docs/models/<id>` + `models.list` | **`cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing`**（主）<br>`ai.google.dev/gemini-api/docs/pricing`（旁证） |
| xAI | `docs.x.ai/developers/models/<id>.md` | 同左（`.md` 内含完整 Pricing 表） |
| DeepSeek | `api-docs.deepseek.com/zh-cn/quick_start/pricing` | 同左（人民币计价，峰谷两档） |

> **Google Cloud 那页为什么是主源**：它把 Gemini 与**合作方模型**（Claude / Qwen / Llama / DeepSeek / Mistral / gpt-oss / Grok）放在同一张表里，
> 且提供 `Global` / `Non-global` 两个地区列（后者严格 = 前者 × 1.1）、`Standard` / `Priority` / `Flex·Batch` 三档服务等级，
> 还标出促销期与生效日期。`ai.google.dev` 只有 Global 单列、无服务等级，所以只作旁证。

#### 聚合站错得最典型的一类：944K / 943,718

聚合站反复把**思考预算**当成 `max_output_tokens` 写进目录，实例：

| 模型 | 聚合站给的 max | 官方实际 |
|:---|---:|---:|
| `gemini-3.8-flash-tiered` | 943,718 | 该模型并不存在（Google 3.8 Flash 平价，无分档版） |
| `deepseek-v4.1-flash` | 943,718 | 384,000（官方"输出最大 384K"） |

判断方法：**看到 943,718 / 0.9× 折算值（如 58,982）/ `max_completion_tokens` 这类数字，先当聚合站伪值处理**，
回官方页确认后再落盘。

### 4.1 token 字段 = 模型自身规格

同一个数字在三个地方可能不一样，我们只记**官方规格**：

| 模型 | 站点原文 | 官方规格 | 站点实际服务 |
|:---|:---|:---|:---|
| `grok-4` | 2,000,000 | **256,000**（grok-4-0709） | 1,000,000（xAI 2026-05-15 退役 → 转发 grok-4.3） |
| `gemma-3-27b-it` | 40,000 | **131,072**（Google 模型卡） | 某部署截断到 40,000 |
| `claude-haiku-5.5` | 100,000 | **1,000,000** | 1,000,000（站点少打一个 0） |

**为什么不写"实际服务"值**：上游路由随时会改，写进主字段会让同一个模型的值反复漂移，而且再也找不到任何官方页面作为出处。`contextLength` 必须永远能指着文档说"就是这个数"。

实际路由通过附加键表达，不污染主字段：

```json
{
  "id": "grok-4",
  "contextLength": 256000,
  "maxOutputTokens": 256000,
  "servedAs": "grok-4.3",
  "retiredAt": "2026-05-15"
}
```

### 4.2 embedding 模型

站点把**最大输入**填进了 `maxOutputTokens`（例如 `bge-m3` 两个字段都是 8,192）。
embedding 不存在"输出 token"，输出是向量 → `maxOutputTokens` 一律置 `null`，输入上限记在 `contextLength`。

### 4.3 `detail_Provider` ≠ `providerLabel`

详情页的 "Provider" 是**卖方/上游**（Venice AI、SpaceXAI 之类），不是模型开发方。
我们的 `providerLabel` 记开发方（OpenAI、Anthropic、ByteDance…），站点原文单独留在 `detail_Provider`。
已修 12 条，例如 `tts-1`、`whisper-1` 站点写 "Venice AI"，实际是 OpenAI。

### 4.4 布尔值

`detail_VisionInput` 等字段的值统一映射：

| 站点写法 | 含义 | 转为 |
|:---|:---|:---|
| `Supported` | 支持 | `true` |
| `Not supported` | 不支持 | `false` |
| `Not reported` | 站点没报 | `null` |

---

## 5. 站点侧已知问题（保留不动）

以下都是**站点本身的问题**，我们的原则是"照实记录 + 在下游标注"，不去猜：

| 问题 | 数量 | 处理 |
|:---|:---|:---|
| `detail_Input` / `detail_Output` 为 `Not reported` | 125 / 125 | 保留；用 `capabilities` 表达能力 |
| `detail_SupportedParameters` 为 `Not reported` | 255 | 保留 |
| 端点写占位符 `None has passed a live request yet` | 4 | 转为 `null` |
| `servedAt` 为 `null`（无人调用过） | 57 | 保留 |
| `providerSlug` 为 `null` | 250 | 保留 |
| `costPlus` 为 `null` | 451 | 保留 |
| `vision: true` 但 Input 里没有 image | 48 | 两处都留，冲突登记 |
| 有 `video-input` 标签但 Input 里没有 video | 68 | 同上 |
| 三项全为 `null` | 129 | 已被忽略清单筛掉大部分 |

**另一个发现**：站点数据是**动态计算**的。相隔 20 分钟的两次抓取，有 9 处不同（`capabilities` 6 处、`detail_Endpoints` 3 处）——因为端点/能力是根据近期真实流量算出来的。所以：

- 每次核实都必须绑定一个**具体快照的 sha256**；
- 跨快照比较时，`capabilities` 和 `detail_Endpoints` 的差异**不能当成错误**。

---

## 6. 剩余待办

### 6.1 数据侧

- [ ] 核实 44 条主流缺口（15 条缺数值优先，其余是站点没填模态）
- [ ] 3 条 `medium` 修正需要人工过目：`flux-kontext-max`/`-pro` 上下文 512、`nemotron-3.5-super-vl` 最大输出 16,384
- [ ] Claude 两批共 45 条"未落盘"结论需要逐条裁决（P0 10 / P1 24 / P2 6 / P3 4）

### 6.2 工程侧

- [ ] **B2** 抓取成功后做 schema 漂移检测（新增/消失字段立刻告警）
- [ ] **B3** L1 → L1 快照 diff 工具（现在只能靠人工比对，站点一直在变）
- [ ] **B4** 确定抓取节奏基线（多久抓一次、变更率多少算异常）
- [x] **B5** ~~`compare_snapshot` 默认路径还指向 10-23 的旧快照~~ → `normalize_snapshot` 改为自动取 `source-data/` 下最新一期（2026-10-26）
- [x] **B6** ~~`clean_snapshot` 默认路径同上~~ → 该工具已移除，职责由 `fetch_site`（产出 L1 时归一）+ `apply_corrections`（同步 `context-*` 标签）承担
- [ ] **B7** `normalize_snapshot` 不认识 `detail_Provider` / `costPlus: null`

### 6.3 发布决策

- [ ] L1 + L3 各约 1.2 MB，每次抓取都要落盘 → 需要定保留策略（按周/按月归档？）
- [ ] L3 目前没有消费方：我们的模型目录只有 69 个模型，527 条里用不到那么多
- [ ] 口径需要单独出文档（现在散落在 `corrections/README.md` 各节）

---

## 7. 复现

```bash
# 1. 抓取（L1）
python -m tools.ops.fetch_site --save-html

# 2. 生成 L3（一条命令：核实值 + 路由标注 + changelog）
python -m tools.ops.apply_corrections --date 20261026

# 3. 看核实范围（哪 208 条要核、哪 48 条可忽略）
python -m tools.ops.classify_scope
python -m tools.ops.classify_scope --list ignore

# 4. 重生成老代清单（派生）
python tools/ops/mark_legacy.py

# 5. 测试
python -m unittest discover -s tools/model_sync/tests -t .
```

> 三个工具都支持 `--date`，不传则自动取 `corrections/` 下最新一期。下一次抓 11 月快照时，
> 新建 `corrections/202611xx/`，把 `corrections.json` / `routing.json` 放进去即可，旧的不动。

---

## 8. 验收清单（给外部核实方）

任何一批新修正必须全部通过才算数：

1. `detail_*` 零改动 —— 动了就是废掉证据链，直接打回
2. 每条都有 `source_url`，且是官方域名（第三方只能标 `third-party`，不能进 `high`）
3. `expected_old` 必须等于当前 L1 的实际值（防止上游已变、修正在改空气）
4. 不得引入 `maxOutputTokens > contextLength`
5. 不得自造枚举值（`"embedding"`、`"Realtime (speech-to-speech)"` 这类站点没出现过的字符串）
6. `providerLabel` 必须是模型开发方，不是转售方
7. 拿不准的一律进 `pending`，不允许用 `low` 置信度硬写盘
8. **聚合站的值不得覆盖任何官方值**；若两者冲突，以官方为准并在备注里记下差异
9. **不得出现 943,718 / 0.9× 折算值 / `max_completion_tokens` 这类聚合站伪值**（见 §4.0）

> 这套闸门在第一轮已经拦下过一批问题：518 处 `detail_*` 被覆盖、`maxOutputTokens > contextLength` 新增、
> 靠"多数投票"删掉官方确认支持的能力、以及 449 条 `costPlus: false` 的凭空猜测。
