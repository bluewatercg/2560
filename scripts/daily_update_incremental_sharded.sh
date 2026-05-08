
#!/usr/bin/env bash
# v4 一键并行调度：按分片并行执行 run_2560_analysis
# 用法：SHARDS=4 MARKET=all bash daily_update_incremental_sharded.sh

set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SHARDS=${SHARDS:-4}
MARKET=${MARKET:-all}

cd "$ROOT"
source .venv/bin/activate 2>/dev/null || true
export PYTHONPATH=$PWD

echo "[v4] shards=$SHARDS market=$MARKET"

# 获取股票列表（按 market）
CODES=$(python - <<'PY'
from app.db.session import SessionLocal
from sqlalchemy import text
import os
market=os.environ.get('MARKET','all')
def where(mt):
    if mt=='sh': return "code LIKE 'sh.%'"
    if mt=='sz': return "code LIKE 'sz.%'"
    return "(code LIKE 'sh.%' OR code LIKE 'sz.%')"
with SessionLocal() as db:
    rows=db.execute(text(f"SELECT code FROM stock_info WHERE {where(market)} ORDER BY code")).fetchall()
    print(','.join(r[0] for r in rows))
PY
)

IFS=',' read -ra ARR <<< "$CODES"
TOTAL=${#ARR[@]}
PER=$(( (TOTAL + SHARDS - 1) / SHARDS ))

pids=()
for ((i=0;i<SHARDS;i++)); do
  START=$(( i*PER ))
  END=$(( START+PER ))
  SLICE=("${ARR[@]:START:PER}")
  [ ${#SLICE[@]} -eq 0 ] && continue
  ( python scripts/run_2560_analysis.py --codes "$(IFS=,; echo "${SLICE[*]}")" --market-type $MARKET ) &
  pids+=("$!")
  echo "Shard $i started (${#SLICE[@]} codes)"
done

for p in "${pids[@]}"; do wait $p; done

echo "[v4] all shards done"
