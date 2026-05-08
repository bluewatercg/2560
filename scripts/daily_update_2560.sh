#!/usr/bin/env bash
set -e

ROOT="/mnt/d/Project/Miller/strategy2560_project_v2_engine"
VIPDOC="/mnt/e/zd_ciccwm/vipdoc"
START="2025-10-01"
TODAY=$(date +%F)

cd $ROOT
source .venv/bin/activate
export PYTHONPATH=$PWD

echo "===== [1/5] daily 导入（并发） ====="

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $START \
  --end $TODAY \
  --daily \
  --markets sh &

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $START \
  --end $TODAY \
  --daily \
  --markets sz &

wait
echo "✅ daily 完成"

echo "===== [2/5] lc5 导入（并发） ====="

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $START \
  --end $TODAY \
  --lc5 \
  --markets sh &

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $START \
  --end $TODAY \
  --lc5 \
  --markets sz &

wait
echo "✅ lc5 完成"

echo "===== [3/5] 5m → 30m（串行，避免锁冲突） ====="

python scripts/build_30m_from_5m.py \
  --start $START \
  --end $TODAY \
  --market-type all

echo "✅ 30m 完成"

echo "===== [4/5] indicator 重算（并发） ====="

python scripts/rebuild_technical_indicator.py \
  --start $START \
  --end $TODAY \
  --market-type sh \
  --periods daily,5m,30m &

python scripts/rebuild_technical_indicator.py \
  --start $START \
  --end $TODAY \
  --market-type sz \
  --periods daily,5m,30m &

wait
echo "✅ indicator 完成"

echo "===== [5/5] 2560 分析（并发） ====="

python scripts/run_2560_analysis.py --market-type sh &
python scripts/run_2560_analysis.py --market-type sz &

wait
echo "✅ 2560 全部完成"

echo "===== ✅ DAILY UPDATE DONE ====="
