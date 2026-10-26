# raw/ —— 第三方站点抓取的原始快照

这个目录**只放"别人写的原话"**，不放我们加工过的数据。
用途是留证：以后要证明"某天某站点确实写了 32,768"，靠的就是这里的文件。

## 这里为什么只有两个文件

| 文件 | 是什么 | 谁生成 |
|:---|:---|:---|
| `cheaperinference-YYYYMMDD.json` | **L1 原始快照**：站点逐字渲染的内容，`detail_*` 一字不改 | `python -m tools.ops.fetch_site` |
| `cheaperinference-YYYYMMDD.verified.json` | **L3 成品**：L1 叠加 `corrections/<YYYYMMDD>/` 里带官方出处的修正 | `python -m tools.ops.apply_corrections` |

`official-metadata-YYYYMMDD.json` 是另一条线：逐模型抓厂商官方页的元数据核对快照，
由 `python -m tools.ops.harvest_official --fetch` 生成，**默认不进 git**（可复现，需要留档时 `git add -f`）。

## 约定

- **每期只保留最新的一份。** 换新快照时直接删掉上一期，历史在 `git log` 里，不需要堆在目录里。
- **中间产物不进这个目录。** 清洗/归一化的结果写到 `/tmp` 或加进 `.gitignore`，不要放在 `raw/` 下让人误以为是原始数据。
- **不要手改 L1。** 要修正数据就写进 `corrections/`，让 `detail_*` 保持可验证。原因见 `corrections/README.md`。
- **不要合并 L1 和 L3。** 两者共存才有意义：L3 能算出来，才证明修正规则是对的。

## 数据怎么流出去

```
raw/…json (L1)  ──apply_corrections──▶  raw/….verified.json (L3)
                                               │
corrections/<date>/*.json (L2, 官方出处) ──────┘
                                               │
                                    人工比对 ──▶ sources/overrides.json ──▶ api/newapi/models.json
```

`raw/` 里的东西是**旁证，不是来源**。第三方聚合站的口径与厂商不同（它记的是对外零售价，
`vision` 只表示能否喂图），不能直接并进模型目录。比对用：

```bash
python -m tools.ops.compare_snapshot raw/cheaperinference-20261026.json
```

## 价格不在这里

快照抓取时**已剔除全部价格字段**。价格只走 `sources/pricing.official.json`（厂商官方价），
结算成本私有不入库。所以在这个目录里找不到任何价格，是设计如此，不是漏抓。
