#!/usr/bin/env python3
"""校验 api/ 下发数据的内部一致性与可复现性。

覆盖三类问题：
  1. 元数据本身（模型清单 / 枚举 / 字段合法性 / 免费标记 / 阶梯阈值）
  2. 价格快照（覆盖完整性 / 表达式可由价格字段复现 / 与官方抄录一致）
  3. 线上漂移（给出 --live 时，对比 new-api options 里实际生效的 billing_expr）
  4. 运维脚本权限（crontab 直接执行的 .sh 必须有可执行位）

用法：
    python -m tools.model_sync.validate
    python -m tools.model_sync.validate --live /tmp/expr.json   # {model: expr}
    python -m tools.model_sync.validate --strict                # 警告也算失败

日志分三级：ERROR（数据错误，退出码 1）、WARN（应尽快修，不阻断）、INFO。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):  # 允许直接 python tools/model_sync/validate.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.model_sync import expr as expr_mod
    from tools.model_sync import merge as merge_mod
    from tools.model_sync.normalize import CAPABILITY_ORDER
else:
    from . import expr as expr_mod
    from . import merge as merge_mod
    from .normalize import CAPABILITY_ORDER

ROOT = Path(__file__).resolve().parents[2]
META = ROOT / "api"

INPUT_MODALITIES = {"text", "image", "audio", "video", "file"}
OUTPUT_MODALITIES = {"text", "image", "audio", "video"}
PRICE_KINDS = {"vendor_official", "aggregator_reference", "free", "unpriced"}
LIFECYCLES = {"", "ga", "preview", "legacy", "deprecated", "retired"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def print(self) -> None:
        for title, items in (("ERROR", self.errors), ("WARN", self.warnings), ("INFO", self.infos)):
            if not items:
                continue
            print(f"\n{title} ({len(items)})")
            for item in items:
                print(f"  - {item}")


def load(path: Path):
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("data", data) if isinstance(data, dict) else data


def check_metadata(models, vendors, report: Report):
    vendor_names = {v.get("name") or v.get("vendor_name") for v in vendors}
    seen: dict[str, int] = {}
    caps_allowed = set(CAPABILITY_ORDER)

    for item in models:
        name = str(item.get("model_name") or "")
        seen[name] = seen.get(name, 0) + 1
        if not name:
            report.error("存在没有 model_name 的记录")
            continue

        vendor = item.get("vendor_name")
        if not vendor:
            report.error(f"{name}: vendor_name 为空")
        elif vendor not in vendor_names:
            report.error(f"{name}: vendor_name「{vendor}」不在 vendors.json 中")

        for cap in item.get("capabilities") or []:
            if cap not in caps_allowed:
                report.error(f"{name}: 未知 capability「{cap}」（不在 normalize.CAPABILITY_ORDER）")
        for value in item.get("input_modalities") or []:
            if value not in INPUT_MODALITIES:
                report.error(f"{name}: 未知 input_modality「{value}」")
        for value in item.get("output_modalities") or []:
            if value not in OUTPUT_MODALITIES:
                report.error(f"{name}: 未知 output_modality「{value}」")

        ctx = item.get("context_length") or 0
        out = item.get("max_output_tokens") or 0
        if ctx and out and out > ctx:
            report.error(f"{name}: max_output_tokens {out} 大于 context_length {ctx}")
        if not ctx:
            report.warn(f"{name}: context_length 缺失（0）")
        if not out:
            report.warn(f"{name}: max_output_tokens 缺失（0）")
        if not (item.get("capabilities") or []):
            report.warn(f"{name}: capabilities 为空")
        if not item.get("tags"):
            report.warn(f"{name}: tags 为空")
        if not item.get("description"):
            report.warn(f"{name}: description 为空")
        if not item.get("icon"):
            report.warn(f"{name}: icon 为空")

        if name.endswith(":free") and not item.get("is_free"):
            report.error(f"{name}: 名称以 :free 结尾，但 is_free 不是 true")

        lifecycle = (item.get("lifecycle") or "").strip().lower()
        if lifecycle not in LIFECYCLES:
            report.error(f"{name}: lifecycle 取值非法「{lifecycle}」（可选 ga/preview/legacy/deprecated/retired）")
        tags_text = item.get("tags") or ""
        if "已弃用" in tags_text and lifecycle != "deprecated":
            report.error(
                f"{name}: tags 写着「已弃用」但 lifecycle={lifecycle or '空'}，请统一用 lifecycle 表达"
            )
        if lifecycle == "deprecated" and "已弃用" not in tags_text:
            report.info(f"{name}: lifecycle=deprecated，建议同时加 tags「已弃用」方便展示")
        status = item.get("status", 1)
        if status not in (0, 1):
            report.error(f"{name}: status 只能是 0/1，实际 {status}")
        rule = item.get("name_rule", 0)
        if rule not in (0, 1, 2, 3):
            report.error(f"{name}: name_rule 只能是 0-3，实际 {rule}")

    for name, count in seen.items():
        if count > 1:
            report.error(f"model_name 重复 {count} 次: {name}")

    # vendors.json 会被发布出去，也没有删除机制（new-api 只 Create/Update）。
    # 本地库遗留的供应商一旦写进来就永远挂着，所以这里把「空壳供应商」挑出来。
    referenced = {str(m.get("vendor_name") or "") for m in models}
    orphan = sorted(v for v in vendor_names if v and v not in referenced)
    if orphan:
        report.warn(
            "vendors.json 有 %d 个供应商没有任何模型引用（发布出去只会是空壳，"
            "通常是本地运维遗留）：%s" % (len(orphan), "、".join(orphan))
        )


def check_i18n(base_models, report: Report):
    base = {m["model_name"]: m for m in base_models}
    for locale in ("en", "zh"):
        path = META / "i18n" / locale / "newapi" / "models.json"
        if not path.exists():
            report.warn(f"缺少 {locale} 语言包: {path.relative_to(ROOT)}")
            continue
        rows = {m["model_name"]: m for m in load(path)}
        if set(rows) != set(base):
            report.error(
                f"{locale} 语言包模型与基准不一致: 多 {sorted(set(rows) - set(base))[:5]} / 少 {sorted(set(base) - set(rows))[:5]}"
            )
        # 事实字段必须与基准逐字一致：语言包只允许翻译描述类文本，
        # 出现过回归（zh 包 context_length 仍是旧值）所以在这里硬校验。
        factual = (
            "lifecycle",
            "release_date",
            "knowledge_cutoff",
            "context_length",
            "max_output_tokens",
        )
        drifted = [
            f"{name}.{field}"
            for name in rows
            if name in base
            for field in factual
            if rows[name].get(field) != base[name].get(field)
        ]
        if drifted:
            report.error(
                f"{locale} 语言包事实字段与基准不一致（{len(drifted)} 处）: {drifted[:6]}"
                "（由 sync_models.py 统一生成，不要手改语言包）"
            )
        same = [
            name
            for name in rows
            if name in base and rows[name].get("description") == base[name].get("description")
        ]
        if same:
            # 当前业务只面向大陆（中文），英文包暂不翻译；降为 INFO 避免长期告警。
            report.info(
                f"{locale} 语言包有 {len(same)} 条描述与基准相同（未翻译），例如 {same[:3]}"
            )


def check_overrides(models, report: Report):
    """确认 overrides.json 里人工核对的权威值真的落到了 models.json。

    每日同步会重写 models.json；如果 overrides 没生效（字段名拼错、
    merge 逻辑回退），数据会静默回到聚合源的旧值——这里做兜底断言。
    """
    path = ROOT / "reference-data" / "metadata" / "overrides.json"
    if not path.exists():
        report.warn("缺少 overrides.json，人工核对值无法固化")
        return
    overrides = json.loads(path.read_text(encoding="utf-8"))
    by_name = {m.get("model_name"): m for m in models}
    for item in overrides.get("models") or []:
        name = str(item.get("model_name") or "")
        record = by_name.get(name)
        if record is None:
            report.error(f"overrides 指定了不存在的模型: {name}")
            continue
        if not (item.get("note") or "").strip():
            report.warn(f"{name}: overrides 缺少 note（依据与复核日期）")
        for field, expected in (item.get("fields") or {}).items():
            if field == "lifecycle":
                value = str(expected or "").strip().lower()
                if value not in LIFECYCLES:
                    report.error(f"{name}: overrides 的 lifecycle「{value}」非法")
            if record.get(field) != expected:
                report.error(
                    f"{name}.{field}: overrides 期望 {expected!r}，models.json 实际 {record.get(field)!r}"
                    "（覆盖未生效或被同步回滚）"
                )


def check_aliases(models, report: Report) -> None:
    """渠道别名表：别名不能出现在目录里，目标必须在目录里。

    ``reference-data/metadata/aliases.json`` 记的是「上游在卖但官方没有」的 id
    （例如 gpt-image-2.5）。它们在目录里没有条目，只借用某个官方模型的计费表达式，
    所以两个方向都要检查：别名不该抢目录名额，目标写错了会导出失败。
    """
    path = ROOT / "reference-data" / "metadata" / "aliases.json"
    if not path.exists():
        return
    document = json.loads(path.read_text(encoding="utf-8"))
    aliases = document.get("aliases") or {}
    if not isinstance(aliases, dict):
        report.error("aliases.json 的 aliases 必须是对象")
        return
    names = {str(m.get("model_name") or "") for m in models}
    for alias, target in aliases.items():
        alias, target = str(alias), str(target)
        if alias in names:
            report.error(f"aliases: {alias} 既是目录条目又是别名，只保留一种")
        if target not in names:
            report.error(f"aliases: {alias} 指向的 {target} 不在 models.json 里")


def check_lifecycle_coverage(models, report: Report):
    total = len(models)
    if not total:
        return
    known = [m for m in models if (m.get("lifecycle") or "").strip()]
    counts: dict[str, int] = {}
    for item in models:
        key = (item.get("lifecycle") or "").strip().lower() or "unknown"
        counts[key] = counts.get(key, 0) + 1
    report.info(
        f"lifecycle 覆盖 {len(known)}/{total}（{counts}），其余为官方未声明"
    )
    retired_on_sale = [
        m.get("model_name")
        for m in models
        if (m.get("lifecycle") or "").strip().lower() == "retired" and m.get("status", 1) == 1
    ]
    if retired_on_sale:
        report.warn(f"lifecycle=retired 但仍在售（status=1）: {retired_on_sale[:6]}")


def check_pricing(models, pricing, official, context_by_name, report: Report):
    model_names = {m["model_name"] for m in models}
    rows = {row["model_name"]: row for row in pricing}
    official_by_name = {row["model_name"]: row for row in official}

    missing = model_names - set(rows)
    extra = set(rows) - model_names
    if missing:
        report.error(f"已发布模型缺价格行: {sorted(missing)[:8]}")
    if extra:
        report.error(f"价格行没有对应模型（死配置）: {sorted(extra)[:8]}")

    for name, row in rows.items():
        kind = row.get("price_kind")
        if kind not in PRICE_KINDS:
            report.error(f"{name}: 未知 price_kind「{kind}」")

        # 公开仓只放官方价。结算价（我们向上游付多少）与它派生的一切都不属于这里，
        # 包括只留下“来源=结算”这层标签——那同样泄露了商业信息。
        leaked = row.get("source") == "settlement" or "billing_basis" in row
        leaked = leaked or any(k.endswith("_cny") for k in row)
        if leaked:
            report.error(
                f"{name}: 公开价格文件出现结算价痕迹（source=settlement / billing_basis / *_cny）"
            )

        # 公开价格文件只放价格。表达式 / 计费模式是我们自己算出来的派生物，
        # 由部署机导出时生成（export_billing），不随数据发布。
        for forbidden in ("billing_expr", "billing_mode", "billing_unexpressible"):
            if forbidden in row:
                report.error(
                    f"{name}: 公开价格文件不应包含 {forbidden}（表达式由部署机导出时生成）"
                )

        # 阶梯阈值高于上下文窗口：官方价目表可能按同系列更大模型给出高档价，
        # 本模型的输入上限却达不到阈值（如 gemini-3-pro-image 上限 65,536 但有 200K 档）。
        # 保留官方对齐，仅提示该档不可达。
        ctx = context_by_name.get(name) or 0
        for tier in row.get("tiers") or []:
            threshold = tier.get("prompt_tokens_at_least") or 0
            if ctx and threshold >= ctx:
                report.info(
                    f"{name}: 阶梯阈值 {threshold} 高于输入上限 {ctx}（该档不可达，保留以对齐官方价目表）"
                )

        if kind == "free" and any((row.get(k) or 0) > 0 for k in ("input", "output")):
            report.error(f"{name}: price_kind=free 但基础价不为 0")

        # upcoming 已过生效日却没提升，说明定时任务没跑或漏了
        from datetime import date as _date

        for item in row.get("upcoming") or []:
            start = item.get("effective_from")
            if start and _date.fromisoformat(start) <= _date.today():
                report.warn(
                    f"{name}: upcoming 价格自 {start} 起生效但尚未提升"
                    "（执行 scripts/ops/promote_upcoming_pricing.py --apply）"
                )

        # 官方抄录是最高优先级，快照必须与之一致
        listed = official_by_name.get(name)
        if listed:
            for field in ("input", "output", "cache_read", "cache_write", "cache_write_1h"):
                want = listed.get(field)
                if want is None:
                    continue
                got = row.get(field)
                if got is None or abs(float(got) - float(want)) > 1e-9:
                    report.error(f"{name}: {field} 与官方抄录不一致（官方 {want} / 快照 {got}）")


def check_live(pricing, live, report: Report, basis=None):
    """Compare the deployed expressions with what this checkout would produce.

    公开目录里没有结算价，表达式只按牌价生成；要比对线上，必须同时给出
    私有结算价文件（``--basis``），否则只有纯牌价模型能对上。
    """
    catalog = {}
    for row in pricing:
        source_row = dict(row)
        if basis:
            entry = merge_mod.basis_for(row["model_name"], basis)
            if entry:
                source_row["billing_basis"] = entry
        expression, _ = expr_mod.build(source_row)
        catalog[row["model_name"]] = expression
    drift = [name for name, value in live.items() if catalog.get(name) != value]
    if drift:
        report.error(
            f"线上生效价格与 catalog 不一致 {len(drift)} 条: {drift[:6]}"
            "（改价必须走 export_billing --basis + push_billing，不要直接改库）"
        )
    unknown = set(live) - set(catalog)
    if unknown:
        report.warn(f"线上存在 catalog 未登记的价格: {sorted(unknown)[:6]}")


def check_cron_scripts(report: Report) -> None:
    """`tools/ops/*.sh` 若存在，git 里必须是 100755。

    2026-10-26 起已无任何定时任务，检查保留以防回归：万一以后再加 shell 脚本，
    权限位错了同样会静默失败（历史上的 `cron-promote-upcoming.sh` 就曾以 100644
    提交，Windows 上看着是 -rwxr-xr-x，Linux checkout 后 cron 直接 Permission denied）。
    查 git index 的 mode 才能跨平台生效，`os.access` 在 Windows 上恒为 True。
    """
    scripts = sorted((ROOT / "tools" / "ops").glob("*.sh"))
    if not scripts:
        return
    try:
        out = subprocess.run(
            ["git", "ls-files", "-s", *[str(p.relative_to(ROOT)) for p in scripts]],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return  # 不是 git 环境或没装 git，跳过
    if out.returncode != 0 or not out.stdout.strip():
        return
    verify_script_modes(report, out.stdout)


def verify_script_modes(report: Report, listing: str) -> None:
    """解析 ``git ls-files -s`` 的输出，对非 100755 的 .sh 报错。

    单独拆出来是为了能脱离仓库内容测试：现在 `tools/ops` 下可能一个 .sh 都没有，
    但这条规则要在将来加回脚本时仍然生效。
    """
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        mode, path = parts[0], parts[3]
        if path.endswith(".sh") and mode != "100755":
            report.error(
                f"{path}: git 模式是 {mode}，计划任务直接执行会 Permission denied"
                f"（修：git update-index --chmod=+x {path}）"
            )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="校验 metadata 与价格快照")
    parser.add_argument("--live", help="线上 billing_expr JSON（{model: expr}），用于检测漂移")
    parser.add_argument("--basis", help="私有结算价文件；比对线上表达式时必填")
    parser.add_argument("--strict", action="store_true", help="把 WARN 也计为失败")
    args = parser.parse_args(argv)

    models = load(META / "newapi" / "models.json")
    vendors = load(META / "newapi" / "vendors.json")
    pricing = load(META / "newapi" / "pricing.json")
    official = load(ROOT / "reference-data" / "price" / "pricing.official.json")

    report = Report()
    check_metadata(models, vendors, report)
    check_overrides(models, report)
    check_aliases(models, report)
    check_lifecycle_coverage(models, report)
    check_i18n(models, report)
    check_cron_scripts(report)

    context = {m["model_name"]: m.get("context_length") or 0 for m in models}
    check_pricing(models, pricing, official, context, report)

    if args.live:
        with open(args.live, encoding="utf-8") as handle:
            basis_doc = merge_mod.load_billing_basis(args.basis) if args.basis else None
            check_live(pricing, json.load(handle), report, basis_doc)

    print(
        f"models={len(models)} vendors={len(vendors)} pricing={len(pricing)} "
        f"official={len(official)}"
    )
    report.print()
    if report.errors or (args.strict and report.warnings):
        print(f"\n失败：{len(report.errors)} 个错误 / {len(report.warnings)} 个警告")
        return 1
    print(f"\n通过：0 个错误 / {len(report.warnings)} 个警告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
