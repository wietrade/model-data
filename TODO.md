# 待办

按优先级排列；做完就删掉对应条目。

## 0. `gpt-oss-120b` 没有官方价，下次落库前必须补私有 basis

- **背景**：2026-10-26 起 `api/newapi/` 只放厂商公开数据，聚合站报价（models.dev / OpenRouter）不再发布。
  `gpt-oss-120b` 只有 openrouter 的 0.15 / 0.6 / 0.075，已随之从 `pricing.json` 移除，
  现在是一行 `{"price_kind": "unpriced"}`。
- **影响**：线上 `billing_setting.billing_expr` 里它还有一条 `p(0.15) + c(0.6) + cr(0.075)`，
  但**重新导出时算不出来**（公开价没了，私有 `billing_basis.json` 里也没有它）。
  拿私有 basis 跑 `export_billing` 得到 67 条，线上是 69 条，差异是
  `gpt-oss-120b` 和已下架的 `glm-5.3-prime`。
- **要做什么**：给它定一个结算价写进私有 `billing_basis.json`（条目必须写全 `BASIS_FIELDS`），
  或者确认要下架它。**在这之前不要用任何“整表替换”的方式落库**（如 `push_billing` 的
  非合并模式、或 new-api 后台「同步价格」的批量应用），否则会静默删掉它的计费配置。
  当前 `push_billing` 默认先 GET 再合并，会把它原样保留。

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
  2. 若确为涨价：更新 `sources/pricing.official.json`（带 `source_url` + `quote`）→
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
