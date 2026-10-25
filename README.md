# model-data — 模型元数据与价格资料库

独立仓库：模型目录（描述 / 能力 / 模态 / 上下文 / 生命周期）与价格快照（含计费表达式）。
**不再放在 new-api 仓库里**，new-api 只通过两个口子消费：

| 消费方 | 方式 | 落点 |
|:---|:---|:---|
| 运行时模型目录 | HTTP 拉取本仓库发布的 `api/**`（`SYNC_UPSTREAM_BASE`），后台「同步资料」预览 + 应用 | new-api `models` / `vendors` 表 |
| 计费表达式 | `tools/model_sync/export_billing.py` 导出 payload → new-api 侧 `scripts/ops/apply_billing.py` 写 options → 重启 | new-api options（`billing_setting.*`） |

> 目录结构刻意与 `basellm/llm-metadata` 一致（`api/newapi/*.json`、`api/i18n/<lang>/newapi/*.json`），
> 因此把 new-api 的 `SYNC_UPSTREAM_BASE` 指到本仓库即可，无需改代码。

## 目录

```
api/newapi/           models.json / vendors.json / pricing.json / pricing.official.json
                      overrides.json / sync.config.json
api/i18n/{zh,en}/     语言包（模型与供应商描述）
raw/                  未合并的第三方抓取快照
tools/model_sync/     同步、表达式生成、校验（纯 Python，无三方依赖）
tools/ops/            价格维护辅助脚本（一次性脚本、upcoming 价格转正）
.github/workflows/    每日自动同步
```

## 快速开始

```bash
python -m unittest discover -s tools/model_sync/tests -t .   # 单测
python -m tools.model_sync.validate                          # 元数据 + 价格自洽性
python -m tools.model_sync.export_billing -o /tmp/billing.json   # 仅按牌价导出（预览用）
python -m tools.model_sync.export_billing \
    --basis /opt/model-data-private/billing_basis.json -o /tmp/billing.json   # 正式导出（含结算价）
```

计费表达式落库（在 new-api 主机上）：

```bash
python scripts/ops/apply_billing.py -i /tmp/billing.json --dry-run
python scripts/ops/apply_billing.py -i /tmp/billing.json
systemctl restart new-api
```

## 历史

本仓库内容原先位于 `new-api/metadata` 与 `new-api/scripts/model_sync`（2026-10-26 拆分）。
完整提交历史仍保留在 new-api 仓库的对应路径下，可用 `git log -- metadata` 追溯。

---

供 new-api 的「模型元数据同步」使用。目录结构必须与上游一致：

```
/api/newapi/models.json
/api/newapi/vendors.json
/api/i18n/<zh|en>/newapi/models.json
/api/i18n/<zh|en>/newapi/vendors.json
```

## 在 new-api 中启用

```
SYNC_UPSTREAM_BASE=https://raw.githubusercontent.com/wietrade/model-data/main
```

（raw 直连需要代理、较慢，故 `SYNC_HTTP_TIMEOUT_SECONDS=30`；
jsDelivr 备选 `https://cdn.jsdelivr.net/gh/wietrade/model-data@main`，但有约 12h 缓存）

## 模型字段

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `model_name` | string | 必填，模型 ID |
| `vendor_name` | string | 供应商名，需存在于 `vendors.json` |
| `description` | string | 展示文案 |
| `icon` | string | lobe-icons 名称，如 `Claude.Color` / `OpenAI` |
| `tags` | string | **纯展示标签**（逗号分隔），不参与筛选 |
| `capabilities` | string[] | **功能特性**（闭集，见下） |
| `input_modalities` | string[] | **输入模态**（闭集，见下） |
| `output_modalities` | string[] | **输出模态**（闭集，见下） |
| `context_length` | int | 上下文窗口（输入 token 数），如 `1100000` |
| `max_output_tokens` | int | 最大输出 token 数；0 表示未知 |
| `is_free` | bool | 是否免费（免计费模型） |
| `lifecycle` | string | 厂商生命周期：`ga` / `preview` / `legacy` / `deprecated` / `retired`；**空串=未知** |
| `release_date` | string | 官方发布日期 `YYYY-MM-DD`，未知为空 |
| `knowledge_cutoff` | string | 官方知识截止 `YYYY-MM`，未知为空 |
| `endpoints` | null / array / object | 显式协议端点；`null` 表示按渠道类型推断 |
| `name_rule` | int | 0=精确匹配，1=前缀，2=后缀，3=包含 |
| `status` | int | 1=上架，0=下架 |

## 数据确定性原则

目录里只放**能追溯到官方原文**的值：

1. 官方没写就留空（`""` / `null` / `0`），**不要**按同系列比例或历史習慣推断；
2. 每条事实都应能对应到 `pricing.official.json` 的 `quote` 或 `overrides.json` 的 `note`（含来源链接与核对日期）；
3. 聚合源（models.dev / OpenRouter）只能当旁证，不得覆盖官方值，且 `confidence` 最多 `medium`；
4. 拿不准的项写进 `docs/doubao-verification-round2.md` 交外部核实，不要先猜一个填上。

### `lifecycle` 取值映射

| 官方原文措辞 | 写入值 |
|:--|:--|
| current lineup / generally available / 稳定版 | `ga` |
| preview / 预览版 / experimental | `preview` |
| legacy / previous generation / 仍可调用旧款 | `legacy` |
| deprecated / 已弃用 | `deprecated` |
| retired / shut down / 已关停 | `retired` |
| 含糊不清 / 无状态说明 | `""`（未知） |

> 注意：`lifecycle` 与 `status`（我方展示开关，1=展示）不同。官方把模型标为 deprecated 但仍在售时，应保留 `status=1`、只改 `lifecycle`。

## capabilities（功能特性，闭集）

| key | 含义 |
|:---|:---|
| `reasoning` | 推理（思维链 / 高算力档） |
| `tools` | 工具 / 函数调用 |
| `web_search` | 联网搜索 |
| `code_interpreter` | 代码执行 |
| `chat` | 对话（一般不需要写，由输出模态推导） |
| `vision` / `files` / `audio` | 旧值，等价信息请写进 `input_modalities` |
| `image_generation` / `video_generation` | 旧值，等价信息请写进 `output_modalities` |
| `embedding` / `rerank` | **用途判别键**：向量 / 重排模型必填其一 |
| `cache_implicit` | 上下文自动缓存（如 OpenAI / DeepSeek 的提示缓存），无需显式声明 |
| `cache_explicit` | 需要显式开启的缓存（如 Anthropic `cache_control`、Gemini cached content） |

## modalities（模态，闭集）

- `input_modalities`：`text` / `image` / `audio` / `video` / `file`
- `output_modalities`：`text` / `image` / `audio` / `video`

> 生成类模型写 `output_modalities`，理解类模型写 `input_modalities`。
> 例：Claude = `["text","image","file"]` → `["text"]`；文生图 = `["text"]` → `["image"]`。

## 广场筛选器如何由字段推导（任务语义，互不排斥）

| 筛选项 | 判定 |
|:---|:---|
| 对话 | 输出含 `text`，且 `capabilities` 不含 `embedding`/`rerank` |
| 图像理解 | 输入含 `image` 且输出含 `text` |
| 图像生成 | 输出含 `image` |
| 音频 | 输入或输出含 `audio` |
| 视频 | 输入或输出含 `video` |
| 文件 | 输入含 `file` |
| 向量 | `capabilities` 含 `embedding` |
| 重排 | `capabilities` 含 `rerank` |
| 免费 | `is_free = true` |

> 一个模型可以同时命中多项（例如 Claude 同时属于「对话 / 图像理解 / 文件」），这是预期行为。

### 生命周期（lifecycle）在链路上的消费方式

| 层 | 位置 | 行为 |
|:---|:---|:---|
| 数据源 | `models.json` / `overrides.json` | `lifecycle` 空串表示官方未声明；人工核对值必须在 `overrides.json` 写 `note` |
| 校验 | `tools/model_sync/validate.py` | 词表校验、`tags` 与 lifecycle 矛盾、`retired` 但仍在售、overrides 是否真的生效、语言包事实字段是否与基准一致 |
| 后端 | `GET /api/pricing?lifecycle=ga,legacy` | 逗号分隔；支持 `unknown`（表示未声明）。不传 = 不过滤；供脚本/后台使用 |
| 后台 | 模型管理列表 + 元数据详情 | 显示生命周期徽标、发布日、知识截止；**由管理员据此决定 `status`（是否上架广场）**，系统不自动下架 |
| 前台 | 模型详情页 | 仅在详情页显示生命周期徽标；`deprecated`/`retired` 额外给出迁移提示；列表页不展示、不筛选 |

> `lifecycle` 不参与计费与路由限流，只用于展示、筛选与运营提示。是否允许调用仍由 `status` 与渠道决定。

### 两个约定 tag（纯展示，不参与同步/计费）

| tag | 含义 | 对 lifecycle 的影响 |
|:---|:---|:---|
| `开源权重` | 厂商以开放权重方式发布，可自托管 | 官方通常没有 API 生命周期口径，`lifecycle` 保持空 |
| `平台命名` | 聚合/转售平台自造 ID，官方无该模型 | 永久留空，并在 `overrides.json` 标 `platform_only: true`，不再进入核实队列 |


## 注意

- 同步只覆盖 `sync_official=1` 的模型；手工改过的（`sync_official=0`）不会被覆盖
- 同步按字段比对：预览里 upstream 为空/0 的字段不要勾选，否则会把本地值清空
- `tags` 不再承载上下文长度或能力；能力写 `capabilities`，类型写 `modalities`
- `max_output_tokens` 必须 ≤ `context_length`（双方都非 0 时校验）
- 新增能力 / 模态词需三处同步：本文件、`model/model_metadata_sync.go`、`web/src/features/pricing/constants.ts`

## 本仓库即元数据与价格的唯一事实源

```
厂商官方 API（可选 key）┐
models.dev              ├─► tools/model_sync ─► overrides.json ─► api/newapi/*.json ─► GitHub ─► new-api 同步
openrouter（tie-break）  ┘
```

- 事实字段（上下文 / 最大输出 / 模态 / 能力 / 免费标记）由多源合并；源下不一致时用
  `api/newapi/sync.config.json` 的 `tie_break`（当前 `openrouter`）裁决，裁决结果会打印在同步日志里。
- 人工核对过的值写入 `api/newapi/overrides.json`，优先级最高（请附官方文档链接与核对日期）。
- 发布地址（new-api 通过 `SYNC_UPSTREAM_BASE` 读取）：
  - `https://raw.githubusercontent.com/wietrade/model-data/main`
  - `https://cdn.jsdelivr.net/gh/wietrade/model-data@main`（约 12h 缓存）
  也可用 GitHub Pages（`https://wietrade.github.io/model-data`），目录结构一致。
- `api/newapi/pricing.json` 只是价格快照，**不参与** new-api 自动写库；后台能直接写库的仍是“上游倍率预设”与“models.dev 价格预设”两个虚拟渠道。
- 每日 02:17 UTC 的 GitHub Actions 会自动跑一遍并开 PR；合并前请重点看新增模型与价格涨跌。

## 价格文件

| 文件 | 内容 | 维护方式 |
|:---|:---|:---|
| `api/newapi/pricing.official.json` | 厂商官方定价页抄录，`price_kind: vendor_official`，逐条带 `source_url` 与 `quote` | 人工（官方页核对后导入） |
| `api/newapi/pricing.json` | 每个已发布模型的**牌价**（官方优先、聚合源次之）+ 由牌价生成的 `billing_expr` | `tools/model_sync` 生成 |

### 公开仓库的边界

本仓库是**公开**的，只放牌价，不放任何采购/结算信息：

| 内容 | 位置 | 是否公开 |
|:---|:---|:---|
| 模型目录、能力/模态、生命周期 | `api/newapi/models.json`、`api/i18n/**` | ✅ |
| 厂商官方牌价 | `api/newapi/pricing.official.json` | ✅ |
| 参考牌价与由其生成的表达式 | `api/newapi/pricing.json` | ✅ |
| **上游结算价**（我们的采购成本、汇率折算、分组折扣） | 私有：`/opt/model-data-private/billing_basis.json` | ❌ |
| **线上实际结算表达式**（含结算单价） | 只在部署机上生成，从不提交 | ❌ |

`pricing.json` 里可能出现**没有价格**的行：这类模型没有公开牌价，只有我们自己的采购价，
因此只保留目录信息（名称 / 厂商 / 来源），价格与表达式在私有侧生成。

结算价一旦存在，表达式就**只由结算价决定**（`expr.apply_billing_basis` 会先清空牌价字段再覆盖），
避免聚合源多出来的 `cache_write`、或 token 价出现在按张模型上时漏进表达式。

优先级：**官方 > 聚合源 > 目录免费标记**。官方有条目的模型一律用官方价；聚合源（models.dev / OpenRouter）
补官方未覆盖的模型；目录里 `is_free: true` 但两边都没有报价的模型，直接写 `0`（`price_kind: free`）。
每条 `pricing.json` 记录都用 `price_kind` 标明来源。
这样「某个转售商的最低报价」不会在无人察觉时替掉厂商牌价。

字段语义（schema v2，USD / 每 1M tokens）：

| 字段 | 含义 |
|:---|:---|
| `input` / `output` | 基础价（未达第一个档位阈值时的价） |
| `input_image` / `cache_read_image` | 图像模态的输入 / 缓存读价；仅当与文本价不同才填（如 `chatgpt-image-latest`） |
| `output_text` / `output_image` | 文本 / 图像输出价；仅当与 `output` 不同才填（图像模型必填） |
| `cache_read` / `cache_write` | 缓存读 / 5 分钟缓存写入 |
| `cache_write_1h` | 1 小时缓存写入（Anthropic 等有 TTL 分档的厂商） |
| `cache_write_12h` | 12 小时缓存写入（OpenAI `prompt_cache_retention`）；计费引擎目前只有 30m/1h 两个缓存桶，此字段仅作参考 |
| `tiers[]` | 阈值触发的覆盖价：输入达到 `prompt_tokens_at_least` 时，整条请求按该档计价 |
| `effective_from` / `effective_to` | 该价格的有效期（`YYYY-MM-DD`），长期价写 `null` |
| `upcoming[]` | 已公布但尚未生效的价格（如 `gemini-4-argon` 2026-12-01 涨价） |
| `per_image` | 按张计价；仅当没有 token 价时作为 `fixed()` 兜底，否则只供展示 |
| `billing_mode` / `billing_expr` | **按牌价**生成的计费表达式，由 `tools/model_sync/expr.py` 从上面的价格字段确定性生成。线上实际结算使用结算价重算的版本（部署机导出），与此不同 |
| `billing_unexpressible` | 官方价里无法用引擎变量表达的收费项，逐条列出，绝不猜测 |
| `confidence` / `quote` | 抄录置信度与官方原文片段，用于复核 |

> `tiers` **不是「第 0 档」**：基础价是阈值以下的价，`tiers[i]` 是「达到阈值之后」的价。
> 例：`claude-haiku-5.5` 基础 `input: 0.1`，`tiers[0] = {prompt_tokens_at_least: 100000, input: 0.5}`。

### 非 token 计费：`meters[]`

LLM 的 token 价继续用上面的标量字段；**按张 / 按秒 / 按次 / 按 credit** 的模型用 `meters[]`
记录官方原文里的单价。`meters[]` 是**审计与展示用的事实记录，不参与表达式生成**：
计费引擎能表达的只有 token 变量（含 `img` / `img_o` / `img_cr` / `ai` / `ao`）与
`image_count`，所以图片模型的计费表达式一律走 token 变量。

```json
"meters": [
  { "dim": "output_image", "price": 0.134, "unit": "image",
    "when": { "resolution": "1K-2K" } },
  { "dim": "output_image", "price": 0.24, "unit": "image",
    "when": { "resolution": "4K" } },
  { "dim": "input_image", "price": 0.0011, "unit": "image" }
]
```

| 键 | 含义 |
|:---|:---|
| `dim` | 计量维度：`input_tokens` / `output_tokens` / `cache_read_tokens` / `input_image` / `output_image` / `input_second` / `output_second` / `request` / `credit` |
| `price` | 单价（USD） |
| `unit` | 单位：`1m_tokens` / `image` / `second` / `request` / `credit` |
| `when` | 生效条件，全部命中才算（可为空）：`prompt_tokens_at_least` / `prompt_tokens_below` / `resolution` / `mode` |
| `free` | 免费额度（前 N 张 / 前 N 秒），可选 |
| `note` | 补充说明，可选 |

规则：

- `output_image` 计量的 `meters[]` 会生成 `tier("image", fixed(price)) * image_count`；
  `input_image` 按张目前没有可观测变量，留在 `billing_unexpressible`；
- `when` 只能写网关真正能读到的请求字段（`quality` / `size`），读不到的档位宁可报 `billing_unexpressible`，不猜；
- 同一 `dim` 的多条 rate 用不同 `when` 区分，条件不得重叠；
- **同一行里 token 价优先于按张价**：引擎先看 `p`/`c`，所以纯按张计费的模型不能同时带 token 牌价，
  这类模型的价格只在私有结算价里给（公开行是空价行）；
- `meters` 只描述可直接标价的维度；没有 `meters` 的模型表示只按 token 计费。

> `unresolved[]` 记录官方提到但未给出具体数值的项（例：`gpt-5.5` 高档缓存价未明确），
> 这些字段一律留 `null`，不得按倍率推算填入。

### 从数据源到线上

`pricing.json` 里的 `billing_expr` 只是**按牌价**的表达式。线上按**结算价**计费，
所以要在部署机上用私有 basis 导出一份 payload：

```bash
# 1. 改完元数据/牌价后先自检（CI 也会跑）
python -m tools.model_sync.validate
python -m unittest discover -s tools/model_sync/tests -t .

# 2. 在部署机上导出（--basis 指向私有结算价文件）
python -m tools.model_sync.export_billing \
    --basis /opt/model-data-private/billing_basis.json -o /tmp/billing.json
```

然后到 new-api 仓库落库：

```bash
python scripts/ops/apply_billing.py -i /tmp/billing.json --dry-run   # 先看变更
python scripts/ops/apply_billing.py -i /tmp/billing.json
systemctl restart new-api                                            # options 只在启动时读
```

模型的增删改名同理，见 new-api 仓库的 `scripts/ops/README.md`。每一步都可重复执行，
线上状态因此能从「公开目录 + 私有结算价」两份 git/文件复现，而不依赖谁还记得后台点过什么。

### 校验（改完必跑）

```bash
python -m tools.model_sync.validate                           # 元数据 + 价格快照自洽性
python -m unittest discover -s tools/model_sync/tests -t .    # 单测（含公开边界检查）

# 在部署机上比对线上实际生效的表达式（必须带私有结算价，否则会对不上）
python -m tools.model_sync.validate \
    --live /tmp/expr.json --basis /opt/model-data-private/billing_basis.json
```

检查项：名称唯一、vendor 存在、枚举闭集、`max_output ≤ context`、`:free` 与 `is_free` 一致、
阶梯阈值落在上下文内、`billing_expr` 可由价格字段复现、快照与 `pricing.official.json` 一致、
三份 i18n 文件是否同步。CI 会在每日同步后自动执行。

> **改价红线**：任何价格变更都必须先改 `pricing.official.json` / `pricing.json`（结算成本则改私有
> basis），再走 `export_billing --basis` + `apply_billing.py` 落库。直接调
> `PATCH /api/option/model_pricing` 或改数据库会绕过官方原文校验，`--live` 校验会把这类漂移报成错误。

## 原始第三方快照（raw/）

`raw/` 存放**未合并**的第三方抓取快照，供人工比对后决定是否并入 `api/newapi/models.json`：

| 文件 | 来源 | 内容 |
|:---|:---|:---|
| `cheaperinference.json` | `platform.cheaperinference.com/markets`（2026-10-23，376 条） | 模型事实字段（上下文、最大输出、模态、能力标记），**已剔除全部价格字段** |
| `cheaperinference-20261023-full.json` | 同上（同日全量抓取，**505 条**；2026-10-26 补抓） | 同上，另含 `detail_*` 原文（端点数、上下文/输出原文、支持参数），价格字段同样已剔除 |

快照只作**旁证**：第三方聚合站的口径与厂商官方不同（例如它记的是对外零售价、`vision` 只表示能否喂图），
不能直接并入目录。用下面的脚本生成差异清单，再对照官方文档决定改哪边：

```bash
python -m tools.ops.compare_snapshot raw/cheaperinference-20261023-full.json
```

当前差异概况：命中 52 / 未命中 17，50 处字段不一致（上下文 18、最大输出 22、reasoning 4、图像输入 6）。

抓取脚本（`fetch_cheaperinference.py` / `merge_cheaperinference.py`）未随本次拆分保留；
`raw/` 里的快照是历史抓取结果，需要更新时按下方规则人工重跑并核对。

`derived` 块记录当时的推导结果，规则如下（抓取/合并脚本未随拆分保留，`derived` 只作参考，不直接采信）：

- `kind` 为 `text` / `decision` 时，`image` 模态只信 `vision` 布尔；`image` / `video` / `retrieval` 仍信 `image-input` token（图生视频、多模态 embedding 的 `vision` 常为 false）
- 输出模态不含 `text` 时丢弃 `structured-output`（站点对图片 / 语音 / 转写模型也一律打了这个 token）
- `context-128k` / `context-1m` 只是尺寸提示，`image-edit` 我方词表暂无对应项，三者都不写入目录

合并前先跑一次对比，确认差异是针对模型事实（context / modalities / capabilities），价格一律不采用。
