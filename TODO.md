# 待办

按优先级排列；做完就删掉对应条目。

## 0. ~~`gpt-oss-120b` 没有官方价~~ —— 2026-10-26 已下架

开源权重模型没有厂商牌价（OpenAI 页面只有模型卡，Google Cloud 列的是自己的托管价），
它的结算价也没在私有 `billing_basis.json` 里，导致每次导出都算不出来。已直接从目录删除：

- 从 `api/**/models.json` 与 `api/newapi/pricing.json` 移除条目（模型数 68 → 67）
- 写进 `reference-data/metadata/overrides.json` 的 `excluded`，聚合源再列也带不回来

线上 `billing_setting.billing_expr` / `billing_mode` 里它可能还有旧条目——那只是残留，
不影响任何已上架模型；`push_billing` 的合并模式会原样保留，需要时可手工清。

## 0b. ~~线上有 8 条表达式落后于仓库~~ —— 2026-10-26 已落库

已用 `tools/ops/push_billing.py --apply` 通过管理令牌写入（HTTP，无需重启）：
DeepSeek 四条汇率统一、`gemini-3-pro-image` / `-preview` / `gemini-3.1-flash-image` / `-preview`
补上缓存读价。写入后内存与 DB 均为 73 条（4 个仅内存的 deepseek 默认键已一并固化）。

## 1. 核实 kimi-k3.1-pro 是否涨价

- **发现时间**：2026-10-26
- **现象**：跑 `sync_models --only pricing` 时，models.dev 把 `kimi-k3.1-pro` 的牌价从
  `input 2 / output 10 / cache_write 2` 改成了 `input 4 / output 20 / cache_write 4`（全部翻倍）。
  当时为了不让这次「结算价迁私有」的提交掺入无关变更，已手工回退；每日 02:17 UTC 的
  workflow 会把它作为独立 PR 再提出来。
- **要做什么**：
  1. 去 Moonshot 官方定价页核对 `kimi-k3.1-pro` 现价；
  2. 若确为涨价：更新 `reference-data/price/pricing.official.json`（带 `source_url` + `quote`）→
     `sync_models --only pricing` → `validate`；
  3. **同时检查结算侧**：若上游同步调价，改私有 `billing_basis.json`
     （注意条目必须写全 `BASIS_FIELDS`，缺字段会导致该计费项归零），
     导出后与线上 `billing_setting.billing_expr` 逐条比对，确认影响面再落库；
  4. 若 models.dev 报错（例如把 `cache_write` 单位搞错）：在 `overrides.json` 写死正确值并留 note。
- **参考**：`docs/official-sources.md`

## 2. GitHub 侧清理旧的不可达对象（可选）

2026-10-26 重写历史并强推后，`main` 已不含内部渠道名 / 结算 URL / 采购成本表述，但 GitHub 上
旧提交对象可能仍可通过 SHA 访问一段时间。若在意，可联系 GitHub Support 触发
`git gc` 或把仓库重建后重推。
