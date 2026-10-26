# reference-data/ —— 现有参考数据（构建输入）

这里放**人写的东西**，`api/` 里放**生成的东西**。两者不要互相手改。

## 元数据和价格是两个互不相干的子目录

```
reference-data/
├── metadata/   ← 模型"是什么"
│   ├── overrides.json        人工核对后钉住的权威值（上下文、最大输出、生命周期…）
│   └── sync.config.json      从哪些源合并（models.dev / openrouter / 厂商 API）
└── price/      ← 模型"多少钱"
    ├── pricing.official.json 厂商官方牌价抄录（每条带 source_url + quote）
    └── fx.json               汇率（数据行只存原币，这里集中换算）
```

**没有哪个文件同时装这两类东西**，这是硬约束：

- `api/newapi/models.json` 只有元数据，`api/newapi/pricing.json` 只有价格；
- `pricing.json` 里出现 `billing_expr` / `billing_mode` / `*_cny` 会被 `validate` 直接报错；
- 我们自己的进货价（结算价）**根本不在这里**，在私有目录的 `billing_basis.json`。

## 各文件什么时候改

| 想改什么 | 改这里 | 然后跑 |
|:---|:---|:---|
| 模型的上下文 / 最大输出 / 生命周期 | `metadata/overrides.json` | `sync_models --only metadata` |
| 厂商改价 | `price/pricing.official.json` | `sync_models --only pricing` |
| 汇率 | `price/fx.json` | `export_billing --basis …` |
| 增删厂商、换数据源优先级 | `metadata/sync.config.json` | `sync_models --only metadata` |

改完一律 `python -m tools.model_sync.validate`（0 error 才算过），再提交 `api/` 下的产物。

## `overrides.json` 的两段

```jsonc
{
  "models":   [ { "model_name": "...", "note": "依据 + 核对日期", "fields": { ... } } ],
  "excluded": [ "不发布的模型名" ]
}
```

- `models` 里的 `fields` 优先级最高，每次同步都会重新叠加，聚合源冲不掉。
- `excluded` 是硬删除：被列进去的模型**连条目都不会生成**，防止下次同步被聚合源带回来。
- 每条 `note` 必须写清「依据哪个官方页、哪一天核对的」——半年后没人记得当时为什么这么定。

## 为什么价格不并进 `models.json`

一个模型条目里塞价格，会导致：改一次价就动整个模型文件（diff 噪音）、
拉元数据的人顺带拿到我们不想公开的成本结构、以及「谁的价才是对的」说不清。
现在这条线是：

```
price/pricing.official.json  ──sync_models──▶  api/newapi/pricing.json      （公开，厂商牌价）
                                                     │
私有 billing_basis.json ──export_billing─────────────┴──▶ billing_expr       （不进仓库）
```
