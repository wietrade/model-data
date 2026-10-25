#!/usr/bin/env bash
# 每日检查「已到生效日」的 upcoming 价格：提升 → 导出 → 交给 new-api 落库 → 重启。
# 由 crontab 调用，日志写入 /var/log/new-api-promote.log。
#
# 安装（服务器 root）：
#   echo '10 3 * * * /opt/model-data/tools/ops/cron-promote-upcoming.sh' | crontab -
#
# NEW_API_DIR 指向 new-api 的源码检出目录（提供 scripts/ops/apply_billing.py）。
set -euo pipefail

cd "$(dirname "$0")/../.."                     # 本仓库根目录
NEW_API_DIR="${NEW_API_DIR:-/www/wwwroot/new-api-src}"
BILLING_BASIS="${BILLING_BASIS:-/opt/model-data-private/billing_basis.json}"
LOG="${PROMOTE_LOG:-/var/log/new-api-promote.log}"
export PATH="/usr/local/go/bin:/usr/local/bun:/usr/local/node22/bin:$PATH"

OUT="$(python3 tools/ops/promote_upcoming_pricing.py --apply 2>&1)"
{
  echo "== $(date -u +%FT%TZ)"
  echo "$OUT"
} >>"$LOG"

if echo "$OUT" | grep -qE "PROMOTED: [1-9]"; then
  python3 -m tools.model_sync.export_billing \
    --basis "$BILLING_BASIS" -o /tmp/billing-upcoming.json >>"$LOG" 2>&1
  (cd "$NEW_API_DIR" && python3 scripts/ops/apply_billing.py -i /tmp/billing-upcoming.json) >>"$LOG" 2>&1
  systemctl restart new-api
  echo "applied + restarted new-api" >>"$LOG"
fi
