# v4 Patch Summary

新增 `daily_update_incremental_sharded.sh`
- 一键并行调度 run_2560_analysis
- 通过 SHARDS 控制并发分片数
- 自动按 market 拆分股票池

用法：
```
SHARDS=4 MARKET=all bash scripts/daily_update_incremental_sharded.sh
```
