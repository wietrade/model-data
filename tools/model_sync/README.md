# 模型元数据 / 官方价格自动同步

一个入口、两个产物，共用同一套抓取、vendor 归一化与合并逻辑：

| 产物 | 用途 | 是否被 new-api 自动消费 |
|:---|:---|:---|
| `api/newapi/models.json`、`vendors.json`（含 `i18n/zh`、`i18n/en`） | 模型元数据（描述、能力、模态、上下文、最大输出、免费标记） | 是，走「模型元数据同步」（预览 + 字段级应用） |
| `api/newapi/pricing.json` | 当前牌价（USD / 每 1M tokens），逐条 `price_kind` 标明来源，附按牌价生成的 `billing_expr` | **否**；上线由部署机 `export_billing --basis <私有结算价>` 导出后 `apply_billing.py` 落库 |
| `api/newapi/pricing.official.json` | 厂商官方定价页抄录（输入源，人工维护） | **否**，由 `pricing.json` 消费 |

价格优先级：`pricing.official.json` > 聚合源（models.dev / OpenRouter）> 目录 `is_free`。
官方有条目的模型一律用官方价，聚合价只用来补官方未覆盖的模型；目录标为免费但两边都没报价的，
直接写 `0`（`price_kind: free`）。每条 `pricing.json` 记录都用 `price_kind` 标明来源。
这样「聚合站最低价」不会在无人察觉的情况下替掉厂商牌价。

非 token 计费（按张 / 按秒 / 按次 / 按 credit）写在官方条目的 `meters[]` 里，原样透传到
`pricing.json`；字段语义见仓库根 `README.md`。

分开的原因：元数据变更风险低、可自动应用；价格变更直接影响实收，必须人工过目，
且厂商调价频率远高于新模型发布。两者失败也互不影响。

> 本仓库是**公开**的，只放牌价。上游结算价（我方采购成本）在部署机的私有文件里，
> 由 `export_billing --basis <文件>` 叠加后生成线上表达式；`pricing.json` 里的
> `billing_expr` 只是按牌价算出来的参考值。

## 用法

```bash
# 只看会发生什么（不写文件）
python3 -m tools.model_sync.sync_models --dry-run

# 只刷新已有模型 + 生成 pricing.json（默认行为，不新增模型）
python3 -m tools.model_sync.sync_models

# CI 守卫：有未提交变更则 exit 1
python3 -m tools.model_sync.sync_models --check

# 只同步元数据 / 只同步价格
python3 -m tools.model_sync.sync_models --only metadata
python3 -m tools.model_sync.sync_models --only pricing

# 允许新增最近发布的模型（避免把厂商历史模型全量灌进广场）
python3 -m tools.model_sync.sync_models --allow-new --min-release-date 2026-01-01

# 只新增指定模型（推荐：逐个确认，可控补全）
python3 -m tools.model_sync.sync_models --allow-new \
  --allow-new-models claude-haiku-4-5,glm-5,gpt-5.4

# 冲突/变动预览（不写文件，列出血缘冲突）
python3 -m tools.model_sync.sync_models --dry-run

# 同时查询厂商官方 API（存在对应环境变量才生效）
OPENAI_API_KEY=... ANTHROPIC_API_KEY=... GEMINI_API_KEY=... \
  python3 -m tools.model_sync.sync_models --official
```

单元测试：

```bash
python3 -m unittest discover -s tools/model_sync/tests -t . -v
```

## 数据源

| 类型 | 源 | 提供 | 凭证 |
|:---|:---|:---|:---|
| 聚合 | `models.dev` | 上下文、最大输出、模态、能力布尔值、单价（每 1M） | 无 |
| 聚合 | `openrouter` | 上下文、最大输出、模态、supported_parameters、单价（每 token，脚本已换算） | 无 |
| 官方 | OpenAI `/v1/models` | 模型 ID 存在性 | `OPENAI_API_KEY` |
| 官方 | Anthropic `/v1/models` | 模型 ID + display name | `ANTHROPIC_API_KEY` |
| 官方 | Gemini `generativelanguage/models` | 模型 ID + 输入/输出 token 上限 | `GEMINI_API_KEY` |
| 官方 | OpenAI / Anthropic 定价页 `.md` | **只核对价格**，不入库；见 `tools/ops/verify_official_prices.py` | 无 |

优先级：`--sources` 的书写顺序（默认 `models.dev,openrouter`），官方 API 最后兜底。
聚合源用于拿到「事实字段」，官方 API 用于发现聚合源漏掉的新模型、以及提示
「本地有但官方列表里没有」的过期条目。

厂商价格页的 HTML **不**抓（改版即断），但 OpenAI / Anthropic 同时提供了 `.md` 版本，表格稳定可解析，
由 `official_pricing.py` 解析、`tools/ops/verify_official_prices.py` 与 `pricing.official.json` 逐字段比对，
**只出报告不改数据**。Gemini 没有 `.md`（返回 HTML），官方价仍靠人工抄录。

## 合并规则

- 只刷新事实字段：`vendor_name`、`capabilities`、`input_modalities`、`output_modalities`、
  `context_length`、`max_output_tokens`、`is_free`
- 本地字段永不覆盖：`description`、`icon`、`tags`（用户自定义）、`endpoints`、`name_rule`、`status`
- 源里为空 / 0 的值不写入，避免把本地值清空
- `max_output_tokens > context_length` 时按 `context_length` 截断
- 源里找不到的已有模型**保留原样**，只在输出里提示 `not in sources`
- 同一归一化 key 命中多条本地记录时报 `ambiguous` 并跳过（安全优先）
- 新模型必须显式 `--allow-new`，可再用 `--min-release-date` 收窄

模型名归一化：去掉 vendor 前缀、`:free`/`:nitro`、`-latest`、日期后缀，
`.` 与 `_` 统一成 `-` ⇒ `claude-haiku-4-5-20251001` ≡ `anthropic/claude-haiku-4.5`。

## 数据正确性保障

1. **多个候选时精确优先**：同一 key 命中多条源记录时，先选 `model_name` 完全相同者，
   再选 `source_id` 以该名结尾者，最后才按 `--sources` 优先级取第一条。
2. **冲突字段不写入**：源之间对 `context_length` / `max_output_tokens` 数值不一致时，
   该字段保持原值（新模型则为 0 = 未知），并在输出里以 `! conflict` 列出。
   宁可缺值，也不写入猜测值。
3. **空值不覆盖**：源里为 `0`/空数组的字段不会清空本地已有值。
4. **新增模型可控**：`--allow-new-models` 按名字白名单创建；
   当源里的 canonical slug 与站内名称不同时（`glm-5-20260211` → `glm-5`），
   以白名单里的名字为准。
5. **描述需人工本地化**：新模型会继承源的英文 `description`，建议提交前改成中文（脚本不会覆写已有描述）。
6. **`tags` 永远属于本地**，脚本不写入、不覆盖。

已知、暂不自动填充的冲突（保持 0 = 未知，需要人工核对官方文档）：
`gemini-3-pro-image(.preview)` 的上下文、`kimi-k3` / `deepseek-v4-pro` / `gemini-3.1-flash-image-preview` 的最大输出。

## GitHub Actions

`.github/workflows/sync-model-metadata.yml`：

- 每天 02:17 UTC 跑一次，也支持手动触发（可勾选「允许新增模型」）
- 先跑单测，再分别执行 `--only metadata` 与 `--only pricing`
- 有差异时推到固定分支 `chore/model-metadata-sync` 并开/更新 PR，
  由人审阅 diff 后合并；**不会**直接推到 `main`
- Fork 仓库需要先在 Actions 页面启用 workflow，并按需配置上述三个 API key secret

## 配套工具

| 脚本 | 用途 |
|:---|:---|
| `tools/ops/compare_snapshot.py` | 把 `raw/` 里的第三方快照与本目录逐字段比对，输出差异清单（只读，不改数据） |
| `tools/ops/promote_upcoming_pricing.py` | 把已到生效日的 `upcoming[]` 价格转正；`cron-promote-upcoming.sh` 每天调用 |
| `export_billing --basis <私有文件>` | 在部署机上生成线上计费表达式（公开仓库不含结算价） |
