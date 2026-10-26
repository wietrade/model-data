# 存疑清单（待官方页确认后再改）

有些值两边（我们 vs Claude 的整理版）不一致，但**都拿不出官方原文**。
在拿到原文之前不改目录——宁可留空/留旧值，也不要用推断覆盖。

判定规则：**能从官方页抄到原文才算确定**；拿不到就留在这里，并写清「要查哪个页面」。

状态标记：`待查` → `已确认`（附原文）→ 改数据 → 从本表删除。

---

## 1. grok-4.5 / grok-4.6 的输出上限与知识截止

| 项 | 我们现在的值 | 对方主张 | 依据情况 |
|:---|:---|:---|:---|
| `max_output_tokens` | `500000` | `0`（未知） | 两边的值都**没有 override 记录**，说明是聚合源带来的 |
| `knowledge_cutoff` | `2026-05` | `""` | 同上，无官方记录 |

**为什么存疑**：`grok-4.7` 的官方页能确认 `max_output_tokens = 500000`（已写进
`reference-data/metadata/overrides.json`），但 4.5 / 4.6 的页面没核过。
对方把 4.5/4.6 清成 `0`（未知），我们保留 500000——**两边都在猜**。

**要查什么**

- `https://docs.x.ai/developers/models/grok-4.5` 与 `/grok-4.6`（`.md` 版）里是否写
  `Max output` / `Output tokens` / `Knowledge cutoff`；
- 若写了 → 抄原文进 overrides 的 `note`，按页面值改；
- 若没写 → 按口径「官方无值置 0 / 空串」，不要沿用聚合源的 500000。

**附带问题**：`grok-4.7` 的 `max_output_tokens = 500000` 也**没有 override 钉住**，
下次同步可能被聚合源改掉，需要一并补钉。

---

## 2. gemini-3.8-flash-tiered 的 release_date / lifecycle

| 项 | 我们现在的值 | 对方主张 | 依据情况 |
|:---|:---|:---|:---|
| `release_date` | `2026-10-13` | `""` | 这是**平台命名**，官方没有这个 id |
| `lifecycle` | `ga` | `""` | 同上 |

**为什么存疑**：`gemini-3.8-flash-tiered` 是我们对 `gemini-3.8-flash` 的阶梯计价另起的名字
（已在 overrides 里写清）。它的型号规格借用了 `gemini-3.8-flash` 的官方页，
但「发布日期」和「生命周期」是**这个 id 特有的属性**，官方页上并不存在。

对方的处理是清空 + 打 `平台命名` 标签，逻辑自洽。

**要查什么**

- 决定口径：平台命名模型的 `release_date` 记「上游开始售卖日」还是留空？
  - 若留空 → 把这两个字段清掉，并打 `平台命名` 标签；
  - 若记售卖日 → 需要上游的启用日期，不能沿用基础型号的发布日期。

**建议**：留空 + 打 `平台命名` 标签（与 `gpt-image-*` 那次处理一致），但需要你确认口径。

---

## 3. 顺带发现的两个实质问题（不是存疑，是要改的）

### 3.1 阶梯边界差 1 token

xAI 官方写的是「prompt **reaches** 200k」，即 **≥ 200,000** 进高档；
而 `tools/model_sync/expr.py` 生成的是：

```python
expr = f"len <= {thresholds[index]} ? {leaves[index]} : {expr}"
```

→ 恰好 200,000 token 的请求会落到**低档**。金额差一倍。

影响面：所有带 `tiers[].prompt_tokens_at_least` 的模型（不只是 grok）。
需要先确认各厂商的措辞到底是 `>` 还是 `≥`，再决定改 `<=` 还是 `<`。

### 3.2 OpenAI 5.6/6.x 的输入上限

官方另写 `Maximum input tokens: 922,000`，我们的 `context_length` 记的是 `1,050,000`
（上下文窗口）。若网关按 `context_length` 放行输入，超过 922,000 的请求会被上游拒绝。

**要查什么**：确认 new-api 是否有按 `context_length` 做前置拦截；若有，需要区分
「上下文窗口」与「最大输入」两个字段。

---

## 4. 对方列出的未留证项（我们这边也要补）

来自 `official/verification-20261026.json` 的 `open_items`，与上面不重复的部分：

| 项 | 状态 | 要查什么 |
|:---|:---|:---|
| `kimi-k3` / `kimi-k3.1-pro` 价格 | 官方价格表是 JS 渲染，抓不到 | 打开 `platform.kimi.com/docs/pricing/chat` 人工截图留证；`kimi-k3.1-pro` 目前仍是 `unpriced` |
| `gemini-3-pro-image` 的 `release_date` | 2026-06-18 与模型页「Latest model update: November 2025」互证不上 | 官方 changelog |
| `gemini-nano-banana-2.1` / `gemini-4-argon` / `gemini-3.8-flash` / `qwen3.8-flash` / MiniMax 的 `release_date` | 本轮未找到官方原文，保留原值 | 各厂商 changelog |
| `MiniMax-M3` / `minimax-m3.1-flash` 的 `max_output_tokens = 524288` | 官方只写 1M context，没写输出上限 | MiniMax API 文档的 `max_tokens` 说明 |
| `nemotron-3.5-lightning:free` 的 `context_length = 262144` | 疑为「免费路由的部署上限」，官方规格写 1M | NVIDIA 模型卡 |
| `gemma-4-*:free` 的价格行 | 没有 `quote` | `ai.google.dev` 定价页的 Gemma 4 段 |
| `inkling:free` / `nemotron-3.5-content-safety:free` / `xing4.0-29b-a4b:free` 的 `release_date` | 引用只写「发布日」，没有 URL | 各厂商发布公告 |
| DeepSeek 峰谷计费 | 表达式只按星期判断，**未排除中国法定节假日**（官方：节假日全天按空闲价） | 需要节假日表 + 表达式支持日期集合 |
