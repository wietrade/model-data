# 官方数据源速查

本目录的数据只有两个来源：**厂商官方页/官方 API**（权威）与**聚合站**（models.dev / openrouter，仅补缺口）。
这份表把「去哪里查、取哪几个数、怎么解析」固定下来，换人维护时照做即可。

## 一、价格

| 厂商 | 官方页面 | 形态 | 取什么 |
|:---|:---|:---|:---|
| OpenAI | `https://developers.openai.com/api/docs/pricing.md` | **Markdown 表**（可直接解析） | 短/长上下文档的 input / output / cached input / 30m 写入 / 12h 写入 |
| Anthropic | `https://platform.claude.com/docs/en/about-claude/pricing.md` | **Markdown 表** | Base input / 5m 写入 / 1h 写入 / cache 命中 / output |
| Google | `https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing` | HTML，**但表格结构规整可解析**（65 个 `<table>`，列固定为 `Model / Type / Region / Price`） | Standard 档每 1M token 的 input / text output / cached input，按 **Global / Non-global** 两个地区列 |
| DeepSeek | `https://api-docs.deepseek.com/zh-cn/quick_start/pricing` | HTML，**人民币计价**，按「空闲 / 高峰」两个时段各报一组价 | 缓存命中 / 缓存未命中 / 输出，均按 ¥/1M tokens || Z.AI（智谱） | `https://docs.z.ai/guides/overview/pricing.md` | **Markdown 表**，美元计价 | Input / Cached Input / Output；`Cached Input Storage` 目前限时免费 || Google（开发端 API，旁证） | `https://ai.google.dev/gemini-api/docs/pricing` | HTML（`.md` 返回同一份 HTML，`llms.txt` 404） | 同上，仅 Global 一列；用于交叉核对 |

> **DeepSeek 记的是「高峰价」**。官方按北京时间分峰谷：周一至周五 9:00–12:00、14:00–18:00
> （不含法定节假日）为高峰，其余全天空闲，**空闲价 = 高峰价 × 0.5**。
>
> 我们记的是**高峰价按实时汇率折算的美元值**，保留 4 位小数：
>
> | 模型 | 官方 CNY（命中/未命中/输出，高峰） | USD |
> |:---|:---|:---|
> | `deepseek-flash` 及其别名 | ¥0.04 / ¥2 / ¥8 | 0.006 / 0.2995 / 1.1981 |
> | `deepseek-v4-pro` | ¥0.30 / ¥9 / ¥27 | 0.0449 / 1.3478 / 4.0435 |
>
> **汇率口径（2026-10-26）**：`1 USD = 6.677446 CNY`，取自 `open.er-api.com`，
> 与 ECB 当日 6.6702 偏差 0.11%。换汇率只需重跑折算并把日期写进 `notes`；
> 历史上有过 6.6667 与 6.8182 两套手工汇率并存，已统一。刷新方式：
>
> ```bash
> curl -s https://open.er-api.com/v6/latest/USD | python -c "import json,sys; print(json.load(sys.stdin)['rates']['CNY'])"
> ```

> **DeepSeek 的 Search / Fetch 是单独计费的独立 API**：¥5 / 1000 次成功请求。
> 目前从 DeepSeek Harness / Claude Code / Codex 走 Server 端工具调用时**不收费**，
> **2026-11-01 00:00（北京时间）起按次收取**——我们目录里完全没有这一类维度，
> 若网关会透传这类请求，需要单独核成本。

自动核对（只出报告，不改数据）：

```bash
python -m tools.ops.verify_official_prices \
    --claude /tmp/claude_pricing.md --openai /tmp/openai_pricing.md
# 或现场抓取：--fetch（走 HTTPS_PROXY / --proxy）
```

> **`GEMINI_API_KEY` 帮不上价格**。`generativelanguage.googleapis.com` 是推理接口，返回的字段只有
> `inputTokenLimit` / `outputTokenLimit` / `supportedGenerationMethods` / `thinking` 等元数据，
> **schema 里没有任何价格字段**（2026-10-26 实测）。定价属于商业文档，只能从上面的页面拿。
> 想要机器可读的价格得走 Vertex AI 的 `cloudbilling.googleapis.com` SKU 接口，那需要 GCP 项目 +
> 服务账号，不是 API key。
>
> `pricing.md` 这个 URL 会返回 200，但内容是 **HTML**（和 `pricing` 完全一样，`.md` 后缀被忽略），
> `llms.txt` 是 404。页面里确实有 88 个 `<table>`、价格是可读文本，所以理论上可解析，
> 但每模型重复三列且夹着生效日期与过渡价，目前仍按人工抄录处理。

人工确认后写进 `sources/pricing.official.json`，每条必须带 `source_url` 与 `quote`（官方原文）。
`pricing.json` 由 `python -m tools.model_sync.sync_models --only pricing` 生成，不要手改。

> **`pricing.json` 记的是厂商牌价，不是我们的进货成本。** 成本（结算价）走私有的
> `billing_basis.json`，由 `export_billing --basis` 在部署机生成，不进本仓库。
> 所以抄价时**不用关心我们从哪进货**——只需回答「厂商自己的定价页写的是多少」。
>
> 例外：**开源权重模型没有厂商牌价**。`gpt-oss-120b` / `gpt-oss-20b` 在 OpenAI 页面只有
> 模型卡（Apache 2.0、HuggingFace 下载），**没有价格表**；Google Cloud 列的是它自己的托管价
> （$0.09 / $0.36）。这类只能记某个托管方的参考价，并在 `notes` 写明是哪一家、哪个日期。
> `gpt-oss-120b` 因无可靠牌价已于 2026-10-26 从目录删除（列入 `overrides.json` 的 `excluded`）。

## 二、元数据（上下文 / 最大输出）

| 厂商 | 官方页面 | 取哪两个数 |
|:---|:---|:---|
| OpenAI | `https://developers.openai.com/api/docs/models/<id>.md` | `- N context window`、`- N max output tokens` |
| OpenAI（索引） | `https://developers.openai.com/api/docs/models.md` | 全部模型 id 清单（链接形式） |
| Anthropic | `https://platform.claude.com/docs/en/models/<slug>/overview.md`（slug = 模型 id 去掉 `claude-` 前缀） | 首段 `Context window: 1M tokens · Max output: 128K tokens` |
| Anthropic（总览） | `https://platform.claude.com/docs/en/about-claude/models/overview.md` | 当前阵容四款的 Context / Max output 对照表 |
| Google | `https://ai.google.dev/gemini-api/docs/models/<id>`（中文加 `?hl=zh-cn`） | `Input token limit`、`Output token limit` |
| Google（无逐模型页时） | `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=200` | `inputTokenLimit` / `outputTokenLimit` |
| xAI | `https://docs.x.ai/developers/models/<id>.md` | **Markdown**，`Context window` / `Pricing` 表（含 ≤200K 与 ≥200K 两档、cached input、Batch 8 折） |
| DeepSeek | `https://api-docs.deepseek.com/zh-cn/quick_start/pricing` | `上下文长度` / `输出长度` / 峰谷两套价 |
| xAI | `https://docs.x.ai/developers/models/<id>.md` | **Markdown**，`Context window` / `Pricing` 表（含 ≤200K 与 ≥200K 两档、cached input、Batch 8 折） |
| DeepSeek | `https://api-docs.deepseek.com/zh-cn/quick_start/pricing`（逐模型详情页同域） | `上下文长度` / `输出长度` / 峰谷两套价 |

调用 Google API 的注意事项（`tools/model_sync/sources.py:_official_google` 已实现）：

- key 走 **`x-goog-api-key` 头**，不要 `?key=`（URL 会进异常信息与 CI 日志）；
- 默认 `pageSize=50` 且返回 `nextPageToken`，**必须翻页**，否则静默漏掉尾部模型；
- 模型 id 带 `models/` 前缀，取用时去掉。

### 优先级与落地

```
逐模型官方页  >  models.list（官方 API）  >  聚合站（models.dev / openrouter）
```

- 冲突时取逐模型官方页，并在 `sources/overrides.json` 的 `note` 里写清「两个来源分别是什么、为何这样取舍、核对日期」；
- 没有逐模型页的 id（preview / 已下线 / 开源权重）才用 `models.list` 或聚合源；
- `overrides.json` 的 `fields` 优先级最高，同步脚本每次都会重新叠加，不会被聚合源冲掉。

### 结构化：一键抓成快照并对账

```bash
# 抓 + 生成快照 + 出差异表（不写任何数据文件）
python -m tools.ops.harvest_official --fetch --check

# 确认后写回 overrides.json（只动 context_length / max_output_tokens）
python -m tools.ops.harvest_official --fetch --apply
```

产出 `raw/official-metadata-<date>.json`（默认被 .gitignore 忽略，需要留档时 `git add -f`），
每个模型一条记录：

```json
{
  "model": "gemini-4-argon",
  "vendor": "Google",
  "status": "200",
  "source_kind": "official_doc+api",
  "basis": "page",
  "context_length": 1048576,
  "max_output_tokens": 65536,
  "conflicts": [{ "field": "max_output_tokens", "doc": 65536, "api": 32768 }],
  "catalog_context_length": 1048576,
  "catalog_max_output_tokens": 65536
}
```

`basis` 是关键字段：

| basis | 含义 | 能否自动校正 |
|:---|:---|:---|
| `page` | 逐模型官方页解析成功 | ✅ 可以（`--apply` 会写 overrides） |
| `api_only` | 页面缺失/无数据，只有 `models.list` | ❌ 只作提示——它给过错值（两个图像模型的限制被对调过） |
| `none` | 两边都没有 | ❌ 保留目录现值 |

页面与 API 同时有值时以页面为准，并把分歧记在 `conflicts` 里（`--apply` 不写冲突项）。

> 价格**不参与**自动写回：`pricing.official.json` 是人工确认的结果，工具只出报告（`verify_official_prices`）。

## 三、已知的坑

| 坑 | 说明 |
|:---|:---|
| 定价页的括号是**价格档**，不是上下文 | `Claude Haiku 5.5 (for prompts up to 100,000 tokens)` 只说明这档价格适用到 100K；该模型上下文是 1M（见 Models overview） |
| Google 的逐模型页与 `models.list` 会互相矛盾 | 例：`gemini-3-pro-image` 页写 65,536 / API 写 131,072；`gemini-3.1-flash-image` 页写 131,072 / API 写 65,536。按上表规则取**逐模型页** |
| OpenAI 定价页有倍率段 | `Batch` / `Priority` / `Flex` 段是主表的倍率，不是牌价；`Grouped Pricing Table data` 里 `Modality` 列区分 Image / Text 两行 |
| 长上下文档不是「另一个模型」 | OpenAI 的 `Short context` / `Long context` 是同一模型的两个价格档，落到 `tiers[]`（阈值取自 `(<272K context length)`） |
| Gemini 的价格页没有 `.md` | `ai.google.dev` 与 `cloud.google.com` 两个域名的 `.md` 都返回 200 但内容是 HTML（后缀被忽略），`llms.txt` 404。**但 `cloud.google.com` 那页的表格很规整**，标准库 `HTMLParser` 就能抽成行（需处理合并单元格：空单元格表示同上） |
| Gemini 定价有三个我们**不建档**的维度 | ① 区域：`Non-global` 比 `Global` 贵 10%——我们只记 Global；② 服务档：`Priority` ≈1.8×、`Batch` = 0.5×——**请求级参数，不另建档位**（同 `service_tier` 的既有约定）；③ 非 token 计费：Grounding $14/1000 次、Computer Use 按 token |
| Gemini 4 的超长请求计费规则（2026-11-13 起） | “completions 超过 32K token 时，即使请求最终因客户端/服务端超时失败，仍按 retrievable token usage 收费” |
| Google 那页**同时列了合作伙伴模型** | 2026-10-26 逐表核过：合作方共 **33 个**有标准价 —— Grok 7 / DeepSeek 5 / Qwen 4 / GLM 3 / Llama 3 / Mistral 4 / gpt-oss 2 / MiniMax 1 / Kimi 1 / Gemini Flash 3。可作 **旁证**（低于厂商自有页，高于 models.dev / openrouter）。交叉核对：`grok-4.7` 2.0/6.0、`glm-5` 1.0/3.2、`gemini-3.8-flash` 0.75/3.75 与我们目录**完全一致** |
| 该页**不列**的模型（别再白找） | `Grok 4.5`、`GLM-5.3` / `5.3-Prime`、`Qwen 3 4B/8B/14B/32B`、`Llama 3.1 8B / 3.2 1B / 3.2 3B / Llama 4 Scout 17B 16E`。这些只能回各厂商自己的定价页 |
| 合作方模型的**区域价为 Global × 1.1** | 2026-10-26 用豆包从该页抽的 14 个 Claude 模型做严校验：`US-Multi` / `EU-Multi` / `us-east5` / `europe-west1` 四个区域**全部严格 = Global × 1.1**，无例外（input / input_long / output / output_long 四个字段均如此）。所以我们只记 Global，等于记了**最低价**，方向安全 |
| 同一页里**表头相同的表会重复多遍** | Global / Non-global（+10%）/ Priority（≈1.8×）/ Batch（0.5×）**表头完全一样**，只能靠表前小标题或出现顺序区分。按“同一模型取首次出现”取到的是 Global 基准价；拿最后一张会静默得到 +10% 的 Non-global 价 |
| 聚合站的 `max_output` 不可信 | 常见 0.9× 折算值（如 58,982）、思考预算（943,718）、`max_completion_tokens` 混入 |
| 第三方站点的值可能是**部署限额**，不是型号规格 | `gpt-oss-20b` 在某站点写 32,768，OpenAI 官方是 131,072——32,768 是某个云部署的上限。**与官方差一个量级时，先怀疑是部署配置** |
| 上游退役转发：id 还活着，背后已换了模型 | xAI `grok-4` 于 2026-05-15 退役，请求转发到 `grok-4.3`。数值仍按**原型号规格**记，另加 `servedAs` / `retiredAt` 标注，不要按新模型回填 |
| embedding 的「最大输出」其实是**最大输入** | 站点把输入上限填进了 `max_output_tokens`（如 `bge-m3` 两字段都是 8,192）。embedding 输出是向量、无输出 token，该字段应为 0/空 |
| 站点能力/端点会随时间拨动 | 同一站点相隔 20 分钟两次抓取有 9 处不同（`capabilities` 6、`detail_Endpoints` 3）——它们按近期真实流量计算。跨快照比对时这两项差异不算错误 |

> 「模型规格」与「站点实际服务」不是同一个数，口径定义与 `servedAs` / `retiredAt` 的写法见
> [`../corrections/README.md`](../corrections/README.md)。

## 四、一次典型的更新流程

1. 抓官方页（`curl --ssl-no-revoke -x <proxy>` 或 `--fetch`）；
2. 价格：`verify_official_prices` 出差异 → 人工确认 → 改 `pricing.official.json`；
3. 元数据：按上表取数 → 记进 `overrides.json`（带 `note`）；
4. `python -m tools.model_sync.sync_models --only metadata`（或 `--only pricing`）；
5. `python -m tools.model_sync.validate`，然后 `python -m unittest discover -s tools/model_sync/tests -t .`；
6. 涉及结算价的改动**只走私有 `billing_basis.json`**，导出后必须与线上 `billing_setting.billing_expr` 逐条比对，确认无意外变化再落库。

### 每天自动做的事（workflow）

`sync-model-metadata.yml` 的顺序是：

1. **Align metadata with vendor pages** — `harvest_official --fetch --apply`：把逐模型页的
   `context_length` / `max_output_tokens` 写进 `overrides.json`；页面与 `models.list` 冲突时**钉住页面值**；
2. **Sync** — `sync_models --only metadata --official` + `--only pricing`：多源合并，官方值赢冲突；
3. **Validate** → **Cross-check vendor pricing pages**（只出报告）；
4. 有变化就开 PR（`api/` 下任何文件，含 `overrides.json`）。

### 多源合并的优先级

```
overrides.json（人工/官方页已核对）
        ↓ 高于
官方逐模型页 / 官方 API（official:*，需官方内部一致）
        ↓ 高于
聚合源（models.dev、openrouter；冲突时用 sync.config.json 的 tie_break）
```

- 官方源之间互相矛盾时**不猜**，回落到 `tie_break`，并把字段标为未解决写入日志；
- 官方值与聚合源冲突且没有 override 时，官方直接赢（`resolve_values` 的 `_official_agreement`）；
- 所以「页面与 API 不一致」的模型必须靠 `overrides.json` 钉住页面值，否则下次同步会被 API 改回。

## 五、密钥

官方 API 只在「核对 / 发现新模型」时需要，都只用读权限：

| 变量 | 用在哪 | 备注 |
|:---|:---|:---|
| `GEMINI_API_KEY` | `harvest_official`（`models.list`）、`sync_models --official` | 走 `x-goog-api-key` 头，不要 `?key=` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | `sync_models --official` | 只能列模型 id，不给上下文/输出上限 |

- **CI**：仓库 Settings → Secrets and variables → Actions，名称与上表一致；
- **本地**：放在**私有目录**（与仓库平级的 `model-data-private/.env.local`，不在本仓库内、也不会被 git 跟踪）：

  ```bash
  set -a; . ../model-data-private/.env.local; set +a
  python -m tools.ops.harvest_official --fetch --check
  ```

- ⚠️ **不要把密钥写进本仓库的任何文件**（含文档、脚本、工作流）。本仓库是**公开**的，
  一旦提交就等于泄漏，只能作废重签；密钥泄露后改历史也清不干净。
