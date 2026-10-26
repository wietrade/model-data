# source-data/ —— 参考数据的来源（原始材料 + 核实台账）

数据从哪来、以及我们拿官方文档核对过什么，都在这个目录。
**最终发布物不在这里**（在 `api/`），我们自己的价也不在这里（在 `reference-data/`、私有目录）。

## 三层，谁都不覆盖谁

| 层 | 文件 | 是什么 | 谁生成 |
|:---|:---|:---|:---|
| **L1** | `cheaperinference-YYYYMMDD.json` | 站点逐字渲染的内容，`detail_*` 一字不改 | `tools/ops/fetch_site.py` |
| **L2** | `corrections/YYYYMMDD/corrections.json` | 官方核实值 + `source_url` + 原文引用 | **人工维护**（核实一次写一条） |
| **L3** | `cheaperinference-YYYYMMDD.verified.json` | L1 叠加 L2 的结果 | `tools/ops/apply_corrections.py` |

```
source-data/
├── cheaperinference-<date>.json            L1 站点原话
├── cheaperinference-<date>.verified.json   L3 成品
├── official-metadata-<date>.json           厂商官方页抓取（默认 gitignore）
└── corrections/
    ├── README.md                          口径：怎么核、什么不能做、验收清单
    └── <date>/
        ├── corrections.json               L2 核实值（不可再生）
        ├── routing.json                   上游路由（servedAs / retiredAt）
        ├── legacy.json                    老代不核实清单（派生）
        └── changelog.csv                  变更表（派生）
```

`legacy.json` 和 `changelog.csv` 是派生物，随时能重跑；
`corrections.json` 和 `routing.json` 是**人工查证的唯一记录，删了就没了**。

改数据前先读 `corrections/README.md`——里面写着什么能改、什么绝对不能改。

## 另外两条线，别和上面混

这个目录里其实有**三条互不相干**的核对线，各自的核对对象不同：

| 文件 | 核对的是谁 | 长什么样 | 会不会重生成 |
|:---|:---|:---|:---|
| `corrections/<date>/corrections.json` | **第三方站点的数据**（527 个模型里的 116 个） | 一条一个字段：`id` / `field` / `value` / `source_url` / `quote` | **不会**，人工核实一次写一条 |
| `cheaperinference-<date>.verified.json` | 上一条的产物 | 整份快照 | 会，`apply_corrections` 随时重算 |
| `official-metadata-<date>.json` | **我们自己的目录**（67 个模型） | 一个模型一条，带 `catalog_*` 用于对比 | 会，`harvest_official --fetch` 每次覆盖 |

所以 `corrections.json` 和 `official-metadata-*.json` **不是同一种东西**，不能合并：

- 覆盖面几乎不重叠（116 个站点模型 vs 40 个目录模型，交集只有 4 个）；
- 修正方向相反——前者是「站点错了、官方是对的」，后者是「我们的目录 vs 官方页」的差异报告；
- 生命周期相反——前者删了就没了，后者随时能重抓，所以默认不进 git。

`official-metadata-*.json` 里 `basis` 的含义：

| `basis` | 含义 | 能不能用来改数据 |
|:---|:---|:---|
| `page` | 逐模型官方页解析成功 | 能，`--apply` 会写进 `reference-data/metadata/overrides.json` |
| `api_only` | 只有 `models.list` 有值，官方页 404 | 不能，只作提示 |
| `none` | 页面 404 或表格解析失败 | 不能，`context_length` 为 `null` 表示**没取到**，不是「官方说是 0」 |

> 看这个文件里的「差异」时先看 `basis`：`basis: none` 那几条的 `null` 只是没数据，
> 不是发现我们目录错了（当前 12 条差异里有 11 条属于这种）。

## 约定

- **每期只留最新一份。** 换新快照时删掉上一期，历史在 `git log` 里，不堆在目录里。
- **不手改 L1。** 要修正就写进 `corrections/<date>/`，让 `detail_*` 保持可验证。
- **L2 与 L3 不合并。** 两者共存才有意义：L3 能由 L1+L2 算出来，才证明修正规则是对的。
- **中间产物不进这里。** 归一化结果写 `/tmp`，不要落到 `source-data/` 让人误以为是原始数据。

## 数据怎么流出去

```
source-data/…json (L1)  ──apply_corrections──▶  source-data/….verified.json (L3)
                                │
source-data/corrections/<date>/ (L2) ───────────┘
                                │
                    人工比对 ──▶ reference-data/metadata/overrides.json ──▶ api/newapi/models.json
```

注意最后一步：**L3 不是发布物**。真正喂给 `api/newapi/models.json` 的是
`reference-data/metadata/overrides.json`——那是我们自己的目录口径，与第三方站点的长尾型号无关。

## 价格不在这里

快照抓取时**已剔除全部价格字段**。价格只走 `reference-data/price/pricing.official.json`（厂商官方价），
结算成本在私有目录。所以在这个目录里找不到任何价格，是设计如此，不是漏抓。
