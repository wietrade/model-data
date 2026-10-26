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
