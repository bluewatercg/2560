
# WebUI 入库计算补丁

把本补丁覆盖到完整项目根目录：

```bash
cp -r strategy2560_webui_run_patch/app .
```

新增能力：

- WebUI 左侧新增“入库计算”菜单；
- 支持从 `stock_info` 搜索股票；
- 支持点击选择股票，也支持手动输入股票代码；
- 点击“计算所选股票”后调用 `POST /api/strategy/2560/run`；
- 后端会执行 `SignalEngine2560.run()`，计算指标、识别结构、写入分析表和标签表；
- 可选择计算后自动重建统计。

启动：

```bash
export PYTHONPATH=$PWD
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问：

```text
http://localhost:8000
```
