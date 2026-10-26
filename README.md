# model-data — 模型元数据与价格资料库

独立仓库：模型目录（描述 / 能力 / 模态 / 上下文 / 生命周期）与价格快照（含计费表达式）。
**不再放在 new-api 仓库里**，new-api 只通过两个口子消费：

| 消费方 | 方式 | 落点 |
|:---|:---|:---|
| 运行时模型目录 | HTTP 拉取本仓库发布的 `api/**`（`SYNC_UPSTREAM_BASE`），后台「同步资料」预览 + 应用 | new-api `models` / `vendors` 表 |
| 计费表达式 | `tools/model_sync/export_billing.py` 导出 payload → new-api 侧 `scripts/ops/apply_billing.py` 写 options → 重启 | new-api options（`billing_setting.*`） |

> 目录结构刻意与 `basellm/llm-metadata` 一致（`api/newapi/*.json`、`api/i18n/<lang>/newapi/*.json`），
> 因此把 new-api 的 `SYNC_UPSTREAM_BASE` 指到本仓库即可，无需改代码。

> 外部平台接入本数据，只需读下面的 [消费方契约](#消费方契约) 一节；
> 其余目录是维护这套数据的过程记录，不是对外接口。

## 目录

仓库分成**输入**和**发布物**两块：`api/` 下全部是 new-api 直接拉取的结果，`sources/` 是生成它们用的人工/半人工输入，**不发布、不被 new-api 读取**。

```
api/newapi/           【发布】models.json / vendors.json / pricing.json
api/i18n/{zh,en}/     【发布】语言包（模型与供应商描述）
sources/              【输入】overrides.json（人工核对钉值）
                      pricing.official.json（厂商牌价抄录）/ sync.config.json（同步配置）
raw/                  第三方快照（cheaperinference）+ 每日官方快照（后者默认 gitignore）
docs/                 official-sources.md（官方数据源与优先级速查）
tools/model_sync/     多源合并、表达式生成、校验（纯 Python，无三方依赖）
tools/ops/            官方页抓取核对、快照比对、upcoming 价格转正
.github/workflows/    每日自动同步
```

> 为什么分开：`api/` 是**对外契约**——把 `SYNC_UPSTREAM_BASE` 指向它就是 new-api 的模型目录来源，
> 多一个文件都会让「发布了什么」变得含糊。`overrides.json` 里的取舍理由、`pricing.official.json`
> 的抄录原文，都是**生成过程中的中间证据**，放 `sources/` 才不会与发布物混淆。

> 去哪里查官方数据、取哪几个字段、有哪些坑：见 [`docs/official-sources.md`](docs/official-sources.md)。
> 当前待办：见 [`TODO.md`](TODO.md)。

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
4. 拿不准的项先留空，并在 `TODO.md` 记一条待核实，不要先猜一个填上。

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

- 同步只刷新事实字段；`description` / `icon` / `tags` / `endpoints` / `name_rule` / `status` 属于本地字段，永远不会被源覆盖
- 源里为空 / 0 的值不写入，避免把本地值清空
- `tags` 不再承载上下文长度或能力；能力写 `capabilities`，类型写 `modalities`
- `max_output_tokens` 必须 ≤ `context_length`（双方都非 0 时校验）
- 新增能力 / 模态词需与**消费方**同步（new-api 的词表与前端筛选器 `web/src/features/pricing/constants.ts`），否则会被丢弃或无法筛选

## 多源合并

```
厂商逐模型页（.md / HTML） / 官方 models.list / models.dev / openrouter
        │
        │  tools/model_sync 合并（冲突时按下方优先级；最后叠加 sources/overrides.json）
        ▼
api/newapi/models.json + i18n   api/newapi/pricing.json        ← 发布物
        │
        │  git push
        ▼
GitHub ──► new-api「同步资料」（SYNC_UPSTREAM_BASE）
```

| 源 | 提供 | 凭证 | 入口 |
|:---|:---|:---|:---|
| OpenAI / Anthropic 逐模型 `.md` | 上下文、最大输出 | 无 | `tools/ops/harvest_official.py` |
| Google 逐模型页（HTML）+ `models.list` | 上下文、最大输出 | `GEMINI_API_KEY` | 同上 |
| 三家 `models.list` | 模型 id、部分上限 | 各自 key | `sync_models --official` |
| models.dev | 上下文、最大输出、模态、能力、参考价 | 无 | `sync_models` |
| openrouter | 同上 + `max_completion_tokens` | 无 | `sync_models` |
| 人工核对 | 任意字段 | — | `overrides.json` |

**优先级（冲突时）：**

```
overrides.json  >  官方逐模型页 / 官方 API（official:*，需官方内部一致）
                >  聚合源（tie_break = 当前 openrouter）
                >  未解决（写进日志，不猜）
```

- **官方 vs 聚合源**：官方赢。`context_length` / `max_output_tokens` 由厂商真正强制，
  聚合站经常混入 0.9× 折算值（如 58,982）、思考预算（如 943,718）或 `max_completion_tokens`。
- **官方内部矛盾**（页面说 65,536、`models.list` 说 131,072）：不猜，回落到 `tie_break`；
  若该模型已有 override，则 override 说了算。
- **override 钉住**：`harvest_official --apply` 会把「页面与 API 冲突」的字段写进 `overrides.json`，
  否则官方 API 会在下次同步把页面值改回去（当前有四个 Gemini 图像模型属于这种）。
- 每日 02:17 UTC 的 workflow：`harvest_official --fetch --apply` → `sync_models` → `validate` → 开 PR；
  合并前重点看 `overrides.json` 的改动、新增模型与价格涨跌。

各源的具体 URL、取哪几个字段、有哪些坑（例如定价页的括号是**价格档**不是上下文）：
见 [`docs/official-sources.md`](docs/official-sources.md)。

## 消费方契约

> **外部平台只需要这一节列出的文件。** 仓库里其他目录（`sources/` `corrections/` `raw/` `tools/` `docs/`）
> 都是我们维护这套数据的**过程记录**，不是对外接口，随时可能重构。

### 要拉什么

| 文件 | 必需 | 内容 |
|:---|:---:|:---|
| `api/newapi/models.json` | ✅ | 模型元数据（字段见上方「模型字段」） |
| `api/newapi/vendors.json` | ✅ | 供应商字典。`models.json` 里只有 `vendor_name` 字符串，**图标 / 描述 / 展示开关只在这里**，两者必须成对拉 |
| `api/i18n/{zh,en}/newapi/{models,vendors}.json` | 可选 | 翻译版描述，结构同上 |
| `api/newapi/pricing.json` | 可选 | 参考价 + `billing_expr`（由参考价生成，**不含任何采购 / 结算价**；那个 `billing_expr` 只是示例，不是线上计费公式） |

四类文件都是 `{"success": true, "message": "ok", "data": [...]}` 信封，与 `basellm/llm-metadata` 一致
（因此 new-api 只需把 `SYNC_UPSTREAM_BASE` 指过来，无需改代码）。

### 从哪拉

| 用途 | URL | 说明 |
|:---|:---|:---|
| 直连 | `https://raw.githubusercontent.com/wietrade/model-data/main` | 推送即生效；**部署机（东京）用的就是这个** |
| 备选加速 | `https://cdn.jsdelivr.net/gh/wietrade/model-data@main` | 约 12h 缓存，对时效敏感就别用 |

> 没有自建镜像、没有 GitHub Pages（`wietrade.github.io/model-data` 返回 404，Pages 从未启用）。
> 本仓库就是**唯一数据源**：改这里 → 推送 → new-api「同步资料」即拿到，中间不经过任何副本。

#### 为什么不搞本地镜像

2026-10-26 曾经在部署机 nginx 上挂过一个 `/model-data/ → /opt/model-data/` 的镜像，
本意是绕开 raw 直连问题。但部署机在东京，实测 raw **0.5～1.5s / 200 / 字节数一致**，镜像不解决任何问题，
反而当天就暴露了代价：服务器上一次手工 `chmod` 让工作区变脏，`git pull --ff-only`
**连续 21 个 commit 静默失败**，线上一直在拉删不掉的旧供应商。

现已**撤掉镜像入口**，`SYNC_UPSTREAM_BASE` 直指 raw。`/opt/model-data` 这个 checkout 仍保留，
但只作为 cron 脚本（`cron-promote-upcoming.sh`）的执行目录，**不再对外提供数据**。

### 不用拉什么

| 目录 | 是什么 | 为什么不用 |
|:---|:---|:---|
| `sources/overrides.json` | 人工钉值 + 取舍理由 | 结果已烘焙进 `models.json`；单独读会误判（它只记「钉住了什么」，不含多源上下文） |
| `sources/pricing.official.json` | 官方定价页抄录（原文 + `source_url` + `quote`） | 同上，结果已落进 `pricing.json` |
| `sources/sync.config.json` | 我们的多源合并配置 | 实现细节 |
| `corrections/`、`raw/` | 快照原件与逐字段改动台账 | 审计用，给人看；`changelog.csv` 是派生品 |
| `tools/` | 生成上述文件的脚本 | 想自己重算再去 fork |

### 原则：判断发生在构建期，不发生在读取期

`overrides.json` 里确实有我们的口径（哪些模型按 `legacy` 算、哪些不发布），但这些判断在**生成
`models.json` 时就已经落成确定值**。消费者拿到的是拍过板的数据，不需要、也不应该自己重跑一遍合并。

不认同某个判断时的正确做法：fork `sources/overrides.json` 后重跑 `tools/`，而不是读完 `models.json` 再打补丁。

### 两个字段是我们的展示约定

`models.json` 绝大部分是厂商公开事实，只有两个字段依赖我们的前端 / 运营习惯，**外部平台应忽略或自行映射**：

| 字段 | 现状 | 说明 |
|:---|:---|:---|
| `tags` | 中文展示标签（`推理` `工具` `多模态`…） | 与 `capabilities` 重复；`平台命名`、`开源权重` 是我们自造的运营词 |
| `icon` | `Claude.Color` / `Grok` / `ZAI` | lobe-icons 的图标名，不是厂商公开标识 |

`status` 恒为 `1`（本仓库只发布上架模型），不含隐藏判断。

### 时效

每日 `02:17 UTC` 由 GitHub Actions 自动同步一次；人工核实后的改动随 `push` 即时生效（走 jsDelivr 则另有缓存延迟）。

- `api/newapi/pricing.json` 只是价格快照，**不参与** new-api 自动写库；后台能直接写库的仍是“上游倍率预设”与“models.dev 价格预设”两个虚拟渠道。
- 官方 API key 只放**仓库 Secret**（`GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`）与
  本地私有目录 `model-data-private/.env.local`，**绝不写进本仓库文件**。


## 价格文件

| 文件 | 内容 | 维护方式 |
|:---|:---|:---|
| `sources/pricing.official.json` | 厂商官方定价页抄录，`price_kind: vendor_official`，逐条带 `source_url` 与 `quote` | 人工（官方页核对后导入） |
| `api/newapi/pricing.json` | 每个已发布模型的**参考价**（官方优先、聚合源次之）+ 由参考价生成的 `billing_expr` | `tools/model_sync` 生成 |

> **官方价只是参考，不是计费依据。** 它有两个用途：① 给外部一个可核对的厂商牌价；
> ② 作为我们自己算倍率 / 计费表达式的**输入**。
>
> 由此推出三条约束：
> 1. `pricing.json` 里的 `billing_expr` 是「按参考价」推出来的**示例表达式**，不是线上计费公式；
>    `export_billing` 从不读它，而是每次从价格字段重新生成（读完再叠私有结算价）。
> 2. 线上生效的 `billing_setting.billing_expr` 是**用结算价重算**的结果，只存在于部署机，不进仓库。
> 3. 所以 new-api **不需要也不应该**拉 `pricing.json`——它只拉 `models.json` + `vendors.json`。
>    价格走「参考价 → `export_billing --basis` → `apply_billing.py`」这条链，结算价全程不出私域。

### 官方价的机器核对

OpenAI / Anthropic 的文档站提供定价页的 **Markdown 版本**，表格可直接解析，用来复核 `pricing.official.json`：

| 厂商 | Markdown 页面 |
|:---|:---|
| OpenAI | `https://developers.openai.com/api/docs/pricing.md` |
| Anthropic | `https://platform.claude.com/docs/en/about-claude/pricing.md` |

```bash
# 直接用本地下载的页面
python -m tools.ops.verify_official_prices \
    --claude /tmp/claude_pricing.md --openai /tmp/openai_pricing.md

# 或者现场抓取（走 HTTPS_PROXY / --proxy http://127.0.0.1:7897）
python -m tools.ops.verify_official_prices --fetch
```

这个工具**只读**：输出「目录 vs 页面」的逐字段差异、页面多出 / 目录多出的模型，不改任何文件。
同一模型在长上下文、batch、priority 等表里会重复出现，解析器只取第一张主表，避免被倍率表覆盖；
Anthropic 的括号说明（如 `Claude Haiku 5.5 (for prompts up to 100,000 tokens)`）会作为
`context_limit_hint` 保留，可用来核对上下文上限。

Google 的 `https://ai.google.dev/gemini-api/docs/pricing.md` 返回的仍是 HTML（0 个表格行），暂不支持。

### 元数据（上下文 / 最大输出）的官方核对

三个厂商的「口供」形式不同，核对路径也不同：

| 厂商 | 权威来源 | 取哪两个数 |
|:---|:---|:---|
| OpenAI | `https://developers.openai.com/api/docs/models/<id>.md` | `- N context window` / `- N max output tokens` |
| Anthropic | `https://platform.claude.com/docs/en/models/<slug>/overview.md`（slug 去掉 `claude-` 前缀） | `Context window: NK tokens · Max output: NK tokens` |
| Google | 逐模型页 `https://ai.google.dev/gemini-api/docs/models/<id>` | `Input token limit` / `Output token limit` |
| Google（无逐模型页时） | `models.list` 的 `inputTokenLimit` / `outputTokenLimit` | 同上 |

规则：**有逐模型官方页就以页为准**（页是给人看的、更新及时）；没有页面（preview / 已下线 id）才用 `models.list`。
两者冲突时同样取页，并在 `overrides.json` 的 `note` 里写明冲突与取舍。定价页里的限定语不要当上下文上限读——
例如 Anthropic 定价表的 `Claude Haiku 5.5 (for prompts up to 100,000 tokens)` 是**价格档**，
其上下文是 1M（Models overview 与逐模型页一致）。

### 公开仓库的边界

本仓库是**公开**的，只放牌价，不放任何采购/结算信息：

| 内容 | 位置 | 是否公开 |
|:---|:---|:---|
| 模型目录、能力/模态、生命周期 | `api/newapi/models.json`、`api/i18n/**` | ✅ |
| 厂商官方牌价 | `sources/pricing.official.json` | ✅ |
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

> **词表缺口（待补）**：第三方快照里有 45 个视频模型（按视频 / 按视频秒）和 14 个 TTS 模型（按字符），
> 我们的 `dim` 还没有 `output_video` / `output_character`，`unit` 也没有 `video` / `character`。
> 将来引入这类模型（或对它们定价）时需要先扩词表，并确认计费引擎能否按这些维度结算。

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

`raw/` 存放**未合并**的第三方抓取快照，供人工比对后决定是否并入 `api/newapi/models.json`。
命名统一为 `cheaperinference-<YYYYMMDD>[-限定词].json`；L3 用 `<YYYYMMDD>.verified.json` 后缀。

| 文件 | 来源 | 内容 |
|:---|:---|:---|
| `cheaperinference-20261023-partial.json` | `platform.cheaperinference.com/markets`（2026-10-23，**376 条**） | 首轮试抓，模型事实字段（上下文、最大输出、模态、能力标记），**已剔除全部价格字段** |
| `cheaperinference-20261023-full.json` | 同上（同日全量重抓，**505 条**；2026-10-26 补抓） | 同上，另含 `detail_*` 原文（端点数、上下文/输出/类型/推理/视觉/编辑原文、支持参数），价格字段同样已剔除。**清洗版会合并掉 7 个重复字段** |
| `cheaperinference-20261026.json` | 同一个站点，**527 条**，由 `tools/ops/fetch_site.py` 直接抓取（市场页 + 每个模型详情页） | 汇总字段 + 13 个 `detail_*`（多了 `detail_Provider` = **卖方/上游**，不是模型厂商）；价格字段已剔除；`fetch` 块记录抓取耗时与失败页 |
| `cheaperinference-20261026.verified.json` | 上一条 + `corrections/20261026/corrections.json` | 应用了有官方出处的修正（157 处字段 + 11 处路由，上下文/最大输出/能力标签/厂商）；`detail_*` 与 L1 逐字节相同，`max>context` 已归零 |
| `official-metadata-<YYYYMMDD>.json` | `tools/ops/harvest_official.py --fetch`（**默认 gitignore**） | 官方逐模型页的核对快照，每跑一次覆盖一次；需要留档时 `git add -f` |

### 快照分三层，不要合并

```
L1  raw/cheaperinference-<date>.json            站点原话，一字不改
L2  corrections/<date>/corrections.json         官方核实值 + source_url + quote
L3  raw/cheaperinference-<date>.verified.json   L1 + L2，给下游用
```

> 一次快照一套，放在 `corrections/<YYYYMMDD>/`；口径文档固定在 `corrections/README.md`。
> 三个工具都支持 `--date`（不传取最新一期），路径自动推导：
> `python -m tools.ops.apply_corrections --date 20261026`

| 工具 | 作用 |
|:---|:---|
| `tools/ops/fetch_site.py` | 抓 `/markets` + `/models/<id>`，产出 L1；内置自检（字段齐全、端点形态、身份一致性、数值冲突） |
| `tools/ops/apply_corrections.py` | 把 L2 应用到 L1 得到 L3；**拒绝修改 `detail_*`**、拒绝无 `source_url` 的条目、`medium` 以下默认不应用、剩余 `max>context` 逐条列出 |

为什么不让「修数据」直接改快照：`detail_*` 是站点逐字渲染的原文，是这份数据里唯一不可再生的部分。
一旦被我们的推断覆盖，就既无法证明站点当时写了什么，也无法验证解析是否还正确（原文串与数值字段的一致性是抓取自检的基准）。
详见 `corrections/README.md`。

快照只作**旁证**：第三方聚合站的口径与厂商官方不同（例如它记的是对外零售价、`vision` 只表示能否喂图），
不能直接并入目录。用下面的脚本生成差异清单，再对照官方文档决定改哪边：

```bash
python -m tools.ops.compare_snapshot raw/cheaperinference-20261023-full.json
```

比对四个维度：`context_length`、`max_output_tokens`、`input_modalities`、`output_modalities`、`capabilities`。
原始快照会先过 `normalize_snapshot`，所以 token 的过度声明不会造成假差异；若某个快照值本身是推出来的
（`input_source=type` 或 `capabilities_source=tokens`），结果里会标「弱证据」。

当前差异概况：命中 52 / 未命中 17，**85 处**字段不一致（能力 30、上下文 17、最大输出 21、输入模态 17），
其中 6 处属于快照侧弱证据。上下文/最大输出的差异基本都是聚合站口径（long-decode 上限、0.9× 折算值），
以官方文档为准，不必反向对齐。

### 清洗：同一个事实不要三套字段

原始快照里一个事实常有多套字段，且会互相矛盾（2026-10-26 对 505 条实测）：

| 冗余 / 冲突 | 现象 | 处理 |
|:---|:---|:---|
| `capabilities` 里的 `context-128k` / `context-1m` | 126 条**同时带两个**（是「≥阈值」累积标签），201 条一个都没带 | 与 `contextLength` 重复，丢弃 |
| `detail_ContextWindow` / `contextLength` | 两边都有 354 条、**0 处不一致**；2 条只有原文（已回填）；150 条两边都没有 | **合并**：只留 `contextLength`（数值），`detail_ContextWindow` 整键删除 |
| `detail_MaximumOutput` / `maxOutputTokens` | 两边都有 352 条、**0 处不一致**；151 条两边都没有；**19 条输出上限 > 上下文** | **合并**：只留 `maxOutputTokens`；超过上下文的只在 `--report` 统计，不擅自截断 |
| `vision` vs `image-input` token vs `detail_VisionInput` | token 过度声明 21 条（bool 与原文都说没有） | 以 bool + 原文为准，token 降为旁证 |
| `detail_Type` / `type` | `type` 8 个值、`detail_Type` 8 个值，除 2 条原文为空外一一对应；但 `realtime`（9 条）在原文里也写作 `Text generation` | **合并**：只留 `type`（更细，能区分 `text` / `realtime`），`detail_Type` 整键删除 |
| `detail_Reasoning` / `reasoning` | 503 条一致、**0 处冲突**；2 条原文为空 | **合并**：只留 `reasoning`（bool），`detail_Reasoning` 整键删除 |
| `detail_VisionInput` / `vision` | 503 条一致、**0 处冲突**；2 条原文为空 | **合并**：只留 `vision`（bool） |
| `detail_ImageEditing` / `imageEdit` | 503 条一致、**0 处冲突**；2 条原文为空 | **合并**：只留 `imageEdit`（bool） |
| `label` / `id` | **505/505 完全相同**（`label` 就是 `id` 的拷贝） | **合并**：只留 `id` |
| `Supported` / `Not supported` / `Not reported` 字面值 | 505 条里共 1439 处站点词汇，与 `null` 混用 | **转成 JSON 原生值**：`true` / `false` / `null`（未知不当 false）；`"None has passed a live request yet"`（4 条）同样转 `null` |
| `detail_Input` 只写 `text`，但 `detail_VisionInput = Supported` | 13 条（多模态模型，**文本和截图都能输**） | 补上 `image`，来源记 `detail+vision` |
| `reasoning` 同理 | token 过度声明 27 条 | 同上 |
| `detail_Input` vs 输入 token | 65 处矛盾 | 以 `detail_Input` 为准；`Not reported` = 未知，不当 false |
| `free` 字段 | 505 条里只有 1 条为 true | 不采信（`:free` 是聚合源命名约定） |
| `type` / `kind` / `group` | 三套分类，只有 87 条三者一致 | 只保留 `type` |

```bash
python -m tools.ops.normalize_snapshot --report                              # 只打印审计
python -m tools.ops.normalize_snapshot -o raw/cheaperinference-normalized.json
```

> 工具分工：
>
> | 工具 | 干什么 | 产出 |
> |:---|:---|:---|
> | `tools/ops/normalize_snapshot.py` | **仅为我们目录比对**做的适配：把站点值映射到本仓库词表、补计费维度、标 `*_source`（会改结构）。不传 `-i` 时自动取 `raw/` 下最新一期 | `raw/cheaperinference-normalized.json`（默认 gitignore） |
>
> 要和 `api/newapi/models.json` 对账 → 用 `compare_snapshot`（内部会调 `normalize_snapshot`）。
>
> > **已移除**：`tools/ops/clean_snapshot.py`（2026-10-26）。它的职责（删 `context-*` 冗余 token、合并与字段重复的 `detail_*`、`Supported`/`Not reported` 转布尔）已经在
> > `fetch_site.py` 产出 L1 时完成，`apply_corrections.py` 又会做 `context-*` 标签同步，留着反而会和现行 29 键结构冲突。

产物每条只留一组事实：`id / provider / type / context_length / max_output_tokens /
input_modalities / output_modalities / capabilities / image_edit / endpoints`，另外两个溯源字段：

| 字段 | 含义 |
|:---|:---|
| `input_source` | `detail` / `detail+vision`（原文只写 text，但视觉支持，补了 image）/ `type` / `type+vision` / `none`（strict 模式：原文没报就留空） |
| `output_source` | `detail`（原文给的）/ `type`（原文没报，按 `type` 推的） |
| `context_source` / `max_output_source` | `numeric`（原始数字字段）/ `detail`（从 `"128,000 tokens"` 这类文本解析）/ `none`（两边都没有） |
| `capabilities_source` | `params`（据 `detail_SupportedParameters`）/ `tokens`（参数表没公布时的弱证据） |
| `billing_dimension` | 计费维度：`tokens` / `image`（按张）/ `video`（按视频）/ `audio_character`（TTS 按字符）/ `audio_second`（ASR 按秒）。由端点判定，端点没报时按 `type` 兜底 |
| `conflicts[]` | 数值字段与原文不一致时的原始值（不猜，只留证） |
| `unknown[]` | 该站没报、也没有可靠推导依据的维度 |

`type` 是该站的 8 类用途分类（`text` / `embedding` / `video` / `image` / `transcription` / `speech` /
`decision` / `realtime`），其中前 6 类可由模态唯一推出（见 `normalize_snapshot.model_type`），
`decision` / `realtime` 推不出来——我们目录只用到 `text` 与 `image` 两类。
清洗产物默认被 gitignore（可从 raw 快照重算）。

默认会「原文没报时按 `type` / `vision` 推一个值」，并如实标在 `input_source` / `output_source`
（实测 103/505 条的模态是推出来的）。只想要站点原文、不想要任何推断时：

```bash
python -m tools.ops.normalize_snapshot --strict -o raw/cheaperinference-strict.json
```

strict 模式下这 103 条的 `input_modalities` 直接留空（同时进 `unknown[]`），
`capabilities` 也不再从 token 回退——适合「宁缺毋滥」的对比。

抓取脚本（`fetch_cheaperinference.py` / `merge_cheaperinference.py`）未随本次拆分保留；
`raw/` 里的快照是历史抓取结果，需要更新时按下方规则人工重跑并核对。

`derived` 块记录当时的推导结果，规则如下（抓取/合并脚本未随拆分保留，`derived` 只作参考，不直接采信）：

- `kind` 为 `text` / `decision` 时，`image` 模态只信 `vision` 布尔；`image` / `video` / `retrieval` 仍信 `image-input` token（图生视频、多模态 embedding 的 `vision` 常为 false）
- 输出模态不含 `text` 时丢弃 `structured-output`（站点对图片 / 语音 / 转写模型也一律打了这个 token）
- `context-128k` / `context-1m` 只是尺寸提示，`image-edit` 我方词表暂无对应项，三者都不写入目录

合并前先跑一次对比，确认差异是针对模型事实（context / modalities / capabilities），价格一律不采用。

## 历史

本仓库内容原先位于 `new-api/metadata` 与 `new-api/scripts/model_sync`（2026-10-26 拆分）；
`new-api` 侧只保留落库脚本 `scripts/ops/`。更早的历史可在本次拆分前的 new-api 仓库追溯。
