# 官方数据源速查

本目录的数据只有两个来源：**厂商官方页/官方 API**（权威）与**聚合站**（models.dev / openrouter，仅补缺口）。
这份表把「去哪里查、取哪几个数、怎么解析」固定下来，换人维护时照做即可。

## 一、价格

| 厂商 | 官方页面 | 形态 | 取什么 |
|:---|:---|:---|:---|
| OpenAI | `https://developers.openai.com/api/docs/pricing.md` | **Markdown 表**（可直接解析） | 短/长上下文档的 input / output / cached input / 30m 写入 / 12h 写入 |
| Anthropic | `https://platform.claude.com/docs/en/about-claude/pricing.md` | **Markdown 表** | Base input / 5m 写入 / 1h 写入 / cache 命中 / output |
| Google | `https://ai.google.dev/gemini-api/docs/pricing` | HTML（**无** `.md`，`llms.txt` 404） | 按模型分段的 `Input / Output / Context caching` 价，**人工抄录** |

自动核对（只出报告，不改数据）：

```bash
python -m tools.ops.verify_official_prices \
    --claude /tmp/claude_pricing.md --openai /tmp/openai_pricing.md
# 或现场抓取：--fetch（走 HTTPS_PROXY / --proxy）
```

人工确认后写进 `api/newapi/pricing.official.json`，每条必须带 `source_url` 与 `quote`（官方原文）。
`pricing.json` 由 `python -m tools.model_sync.sync_models --only pricing` 生成，不要手改。

## 二、元数据（上下文 / 最大输出）

| 厂商 | 官方页面 | 取哪两个数 |
|:---|:---|:---|
| OpenAI | `https://developers.openai.com/api/docs/models/<id>.md` | `- N context window`、`- N max output tokens` |
| OpenAI（索引） | `https://developers.openai.com/api/docs/models.md` | 全部模型 id 清单（链接形式） |
| Anthropic | `https://platform.claude.com/docs/en/models/<slug>/overview.md`（slug = 模型 id 去掉 `claude-` 前缀） | 首段 `Context window: 1M tokens · Max output: 128K tokens` |
| Anthropic（总览） | `https://platform.claude.com/docs/en/about-claude/models/overview.md` | 当前阵容四款的 Context / Max output 对照表 |
| Google | `https://ai.google.dev/gemini-api/docs/models/<id>`（中文加 `?hl=zh-cn`） | `Input token limit`、`Output token limit` |
| Google（无逐模型页时） | `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=200` | `inputTokenLimit` / `outputTokenLimit` |

调用 Google API 的注意事项（`tools/model_sync/sources.py:_official_google` 已实现）：

- key 走 **`x-goog-api-key` 头**，不要 `?key=`（URL 会进异常信息与 CI 日志）；
- 默认 `pageSize=50` 且返回 `nextPageToken`，**必须翻页**，否则静默漏掉尾部模型；
- 模型 id 带 `models/` 前缀，取用时去掉。

### 优先级与落地

```
逐模型官方页  >  models.list（官方 API）  >  聚合站（models.dev / openrouter）
```

- 冲突时取逐模型官方页，并在 `api/newapi/overrides.json` 的 `note` 里写清「两个来源分别是什么、为何这样取舍、核对日期」；
- 没有逐模型页的 id（preview / 已下线 / 开源权重）才用 `models.list` 或聚合源；
- `overrides.json` 的 `fields` 优先级最高，同步脚本每次都会重新叠加，不会被聚合源冲掉。

## 三、已知的坑

| 坑 | 说明 |
|:---|:---|
| 定价页的括号是**价格档**，不是上下文 | `Claude Haiku 5.5 (for prompts up to 100,000 tokens)` 只说明这档价格适用到 100K；该模型上下文是 1M（见 Models overview） |
| Google 的逐模型页与 `models.list` 会互相矛盾 | 例：`gemini-3-pro-image` 页写 65,536 / API 写 131,072；`gemini-3.1-flash-image` 页写 131,072 / API 写 65,536。按上表规则取**逐模型页** |
| OpenAI 定价页有倍率段 | `Batch` / `Priority` / `Flex` 段是主表的倍率，不是牌价；`Grouped Pricing Table data` 里 `Modality` 列区分 Image / Text 两行 |
| 长上下文档不是「另一个模型」 | OpenAI 的 `Short context` / `Long context` 是同一模型的两个价格档，落到 `tiers[]`（阈值取自 `(<272K context length)`） |
| Gemini 没有机器可读定价 | `pricing.md` 返回 HTML、`llms.txt` 404；价格只能人工抄 |
| 聚合站的 `max_output` 不可信 | 常见 0.9× 折算值（如 58,982）、思考预算（943,718）、`max_completion_tokens` 混入 |

## 四、一次典型的更新流程

1. 抓官方页（`curl --ssl-no-revoke -x <proxy>` 或 `--fetch`）；
2. 价格：`verify_official_prices` 出差异 → 人工确认 → 改 `pricing.official.json`；
3. 元数据：按上表取数 → 记进 `overrides.json`（带 `note`）；
4. `python -m tools.model_sync.sync_models --only metadata`（或 `--only pricing`）；
5. `python -m tools.model_sync.validate`，然后 `python -m unittest discover -s tools/model_sync/tests -t .`；
6. 涉及结算价的改动**只走私有 `billing_basis.json`**，导出后必须与线上 `billing_setting.billing_expr` 逐条比对，确认无意外变化再落库。
