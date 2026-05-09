# Strategy2560 最终重构部署包

## 模块边界

- 自选股计算：按自选股/手动代码计算，不导入文件。
- 市场批量任务：按 sh / sz / sh60 / sh68 / sz00 / sz30 批量计算，不导入文件。
- 数据导入：只导入目录文件，不触发计算。
- 查询分析：统一查看数据健康、信号中心、最新结果、结构详情、市场统计、数据质量、2568 标注。

## 统一数据模型

- job_execution：任务执行、进度、日志、取消。
- job_task_item：股票级执行明细。
- analysis_batch：业务批次。
- stock_calc_status：每只股票最后计算时间/批次/任务/状态。
- data_import_batch / data_import_file：数据导入过程。

## 安装

```bash
unzip -o strategy2560_final_reorg_deploy_pack.zip
PYTHONPATH=$PWD python scripts/apply_final_reorg_patch.py
```

## SQL

```bash
mysql -h 192.168.1.254 -P 3306 -u watchlist_decision_support watchlist_decision_support < sql/20260509_final_reorg_schema.sql
```

如果 SQL 工具执行动态 ALTER 报错，先执行 CREATE TABLE 部分，再手工执行注释里的 ALTER。

## 构建部署

```bash
git add .
git commit -m "reorg: unify modules job batch freshness"
git push
```

服务器：

```bash
cd /data1/2560
sudo bash load_deploy.sh ./strategy2560_xxx.tar.gz
```

## 注意

这个包是“最终重构部署叠加包”，会把模块命名、市场范围、统一状态表、部署脚本规整好。现有业务 API 的结果页需要逐步 join stock_calc_status，显示 last_calculated_at / last_batch_id / last_job_id。
