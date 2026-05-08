#!/usr/bin/env bash
set -e

ROOT="/mnt/d/Project/Miller/strategy2560_project_v2_engine"
VIPDOC="/mnt/e/zd_ciccwm/vipdoc"

TODAY=$(date +%F)

# ===== 窗口参数（经验值，稳定） =====
# 行情补数据窗口
DATA_START=$(date -d '30 days ago' +%F)

# 指标回看窗口（30m 足够 MA200 / VOL_MA60）
INDICATOR_START=$(date -d '90 days ago' +%F)

cd $ROOT
source .venv/bin/activate
export PYTHONPATH=$PWD

echo "===== INCREMENTAL UPDATE START ====="
echo "DATA_START=$DATA_START"
echo "INDICATOR_START=$INDICATOR_START"
echo "TODAY=$TODAY"

# --------------------------------------------------
echo "===== [1/5] daily 导入（最近30天，并发） ====="

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $DATA_START \
  --end $TODAY \
  --daily \
  --markets sh &

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $DATA_START \
  --end $TODAY \
  --daily \
  --markets sz &

wait
echo "✅ daily 完成"

# --------------------------------------------------
echo "===== [2/5] lc5 导入（最近30天，并发） ====="

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $DATA_START \
  --end $TODAY \
  --lc5 \
  --markets sh &

python scripts/import_vipdoc_with_pytdx.py \
  --root $VIPDOC \
  --start $DATA_START \
  --end $TODAY \
  --lc5 \
  --markets sz &

wait
echo "✅ lc5 完成"

# --------------------------------------------------
echo "===== [3/5] 5m → 30m（最近30天，串行） ====="

python scripts/build_30m_from_5m.py \
  --start $DATA_START \
  --end $TODAY \
  --market-type all

echo "✅ 30m 完成"

# --------------------------------------------------
echo "===== [4/5] technical_indicator 重算（最近90天，并发） ====="

python scripts/rebuild_technical_indicator.py \
  --start $INDICATOR_START \
  --end $TODAY \
  --market-type sh \
  --periods daily,5m,30m &

python scripts/rebuild_technical_indicator.py \
  --start $INDICATOR_START \
  --end $TODAY \
  --market-type sz \
  --periods daily,5m,30m &

wait
echo "✅ indicator 完成"

# --------------------------------------------------
echo "===== [5/5] 2560 分析（并发） ====="

python scripts/run_2560_analysis.py --market-type sh &
python scripts/run_2560_analysis.py --market-type sz &

wait
echo "✅ 2560 完成"

echo "===== ✅ INCREMENTAL UPDATE DONE ====="