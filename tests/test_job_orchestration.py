from __future__ import annotations

import sys
import struct
import tempfile
import unittest
from pathlib import Path

from app.api import jobs
from app.api.import_data import _merge_job_progress, _merge_data_range
from app.services.job_orchestrator import ensure_job_tables
from app.core.market_scope import market_sql_where
from scripts import job_worker
from scripts.import_vipdoc_with_pytdx import scan_vipdoc_files


class JobOrchestrationTests(unittest.TestCase):
    def test_jobs_api_uses_shared_job_schema_helper(self):
        self.assertIs(jobs._ensure_tables, ensure_job_tables)

    def test_market_scope_never_selects_exchange_wide_security_types(self):
        self.assertEqual(
            market_sql_where("code", "sh"),
            "(code LIKE 'sh.60%' OR code LIKE 'sh.68%')",
        )
        self.assertEqual(
            market_sql_where("code", "sz"),
            "(code LIKE 'sz.00%' OR code LIKE 'sz.30%')",
        )

    def test_import_batch_progress_prefers_job_execution(self):
        batch = {
            "id": 9,
            "total_files": 10,
            "success_files": 1,
            "failed_files": 0,
        }
        job = {
            "id": 44,
            "status": "running",
            "progress_current": 5,
            "progress_total": 10,
            "success_count": 4,
            "failed_count": 1,
            "current_code": "sh.600000",
        }

        merged = _merge_job_progress(batch, job)

        self.assertEqual(merged["job_id"], 44)
        self.assertEqual(merged["progress_url"], "/api/jobs/executions/44/progress")
        self.assertEqual(merged["done_files"], 5)
        self.assertEqual(merged["progress_percent"], 50.0)
        self.assertEqual(merged["job_status"], "running")
        self.assertEqual(merged["batch_done_files"], 1)

    def test_import_batch_merge_includes_data_range(self):
        batch = {"id": 12, "total_files": 1, "success_files": 1, "failed_files": 0}
        data_range = {"data_start": 20260501, "data_end": 20260511}

        merged = _merge_data_range(batch, data_range)

        self.assertEqual(merged["data_start"], 20260501)
        self.assertEqual(merged["data_end"], 20260511)
        self.assertEqual(merged["data_range"], "20260501 - 20260511")

    def test_scan_vipdoc_files_reports_day_file_date_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            lday = Path(tmp) / "sh" / "lday"
            lday.mkdir(parents=True)
            with (lday / "sh688001.day").open("wb") as f:
                for date in (20260508, 20260511):
                    f.write(struct.pack("<IIIIIfII", date, 100, 110, 90, 105, 1000.0, 200, 0))

            scan = scan_vipdoc_files(tmp, "sh68", "lday")

        self.assertEqual(scan["total_files"], 1)
        self.assertEqual(scan["file_data_start"], 20260508)
        self.assertEqual(scan["file_data_end"], 20260511)
        self.assertEqual(scan["file_data_range"], "20260508 - 20260511")

    def test_worker_builds_import_runner_command(self):
        payload = {
            "job_execution_id": 12,
            "import_batch_id": 34,
            "source_dir": "/data/vipdoc",
            "market": "sh",
            "import_type": "all",
            "start": "2026-05-01",
            "end": "2026-05-10",
            "workers": 8,
        }

        cmd, env = job_worker.build_job_command("import_vipdoc", payload)

        self.assertEqual(cmd, [
            sys.executable,
            str(job_worker.PROJECT_ROOT / "scripts" / "import_job_runner.py"),
            "--job-id",
            "12",
            "--batch-id",
            "34",
            "--source-dir",
            "/data/vipdoc",
            "--market",
            "sh",
            "--import-type",
            "all",
            "--workers",
            "8",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-10",
        ])
        self.assertEqual(env["PYTHONPATH"], str(job_worker.PROJECT_ROOT))

    def test_worker_builds_30m_runner_command_with_dry_run(self):
        payload = {
            "job_execution_id": 56,
            "import_batch_id": 78,
            "market": "all",
            "start": "2026-05-01",
            "workers": 4,
            "limit_codes": 100,
            "dry_run": True,
        }

        cmd, _ = job_worker.build_job_command("build_30m", payload)

        self.assertEqual(cmd, [
            sys.executable,
            str(job_worker.PROJECT_ROOT / "scripts" / "build_30m_job_runner.py"),
            "--job-id",
            "56",
            "--batch-id",
            "78",
            "--market",
            "all",
            "--workers",
            "4",
            "--start",
            "2026-05-01",
            "--limit-codes",
            "100",
            "--dry-run",
        ])

    def test_worker_passes_run_2560_limit_codes_to_runner_env(self):
        payload = {
            "job_execution_id": 90,
            "market": "sh60",
            "shards": 1,
            "limit_codes": 1,
        }

        cmd, env = job_worker.build_job_command("run_2560", payload)

        self.assertEqual(cmd, [
            sys.executable,
            str(job_worker.PROJECT_ROOT / "scripts" / "progress_run_now.py"),
        ])
        self.assertEqual(env["JOB_ID"], "90")
        self.assertEqual(env["MARKET"], "sh60")
        self.assertEqual(env["SHARDS"], "1")
        self.assertEqual(env["LIMIT_CODES"], "1")

    def test_jobs_page_requests_only_2560_execution_types(self):
        page_js = (jobs.PROJECT_ROOT / "app" / "static" / "jobs_page_bootstrap.js").read_text(encoding="utf-8")
        monitor_js = (jobs.PROJECT_ROOT / "app" / "static" / "job_progress_monitor.js").read_text(encoding="utf-8")

        self.assertIn("/api/jobs/executions?job_type=run_2560&job_type=run_2560_now&limit=50", page_js)
        self.assertIn("/api/jobs/executions?job_type=run_2560&job_type=run_2560_now&limit=1", page_js)
        self.assertIn("/api/jobs/executions?job_type=run_2560&job_type=run_2560_now&limit=1", monitor_js)
        self.assertIn("const APP_LOAD_JOBS = window.loadJobs", page_js)
        self.assertIn("await APP_LOAD_JOBS()", page_js)

    def test_jobs_page_separates_active_and_history_executions(self):
        page_js = (jobs.PROJECT_ROOT / "app" / "static" / "jobs_page_bootstrap.js").read_text(encoding="utf-8")

        self.assertIn('当前/待执行任务（running / queued）', page_js)
        self.assertIn('历史执行记录（已结束）', page_js)
        self.assertIn('isActiveExecution', page_js)
        self.assertIn('renderExecutionTable(activeTable, activeRows', page_js)
        self.assertIn('renderExecutionTable(historyTable, historyRows', page_js)

    def test_main_job_queue_table_shows_market_scope(self):
        app_js = (jobs.PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('function jobQueueMarket', app_js)
        self.assertIn('function jobQueueExecutionId', app_js)
        self.assertIn('function jobQueueShards', app_js)
        self.assertIn('{ label: "市场范围", render: jobQueueMarket }', app_js)
        self.assertIn('{ label: "执行ID", render: jobQueueExecutionId }', app_js)
        self.assertIn('{ label: "并发数", render: jobQueueShards }', app_js)
        self.assertIn('/api/jobs/queue?job_type=run_2560', app_js)
        self.assertIn('/api/jobs/executions?job_type=run_2560&job_type=run_2560_now', app_js)
        self.assertIn('renderJobExecutions(execs || [], execId, queueId)', app_js)
        self.assertIn('/api/jobs/executions/" + id + "/shards', app_js)
        self.assertIn('jobShardTable', app_js)
        self.assertIn('function renderShardProgress', app_js)
        self.assertIn('{ label: "完成进度", render: renderShardProgress }', app_js)
        self.assertIn('已完成 ${done} / 该组总数 ${total}', app_js)
        self.assertIn('运行中 ${running}，待执行 ${pending}', app_js)
        self.assertIn('Shard 汇总（每行是一组并发线程）', app_js)
        self.assertIn('{ label: "运行中", key: "running_count" }', app_js)
        self.assertIn('{ label: "待执行", key: "pending_count" }', app_js)
        self.assertIn('function isActiveJobStatus', app_js)
        self.assertIn('function startJobAutoRefresh', app_js)
        self.assertIn('function stopJobAutoRefresh', app_js)
        self.assertIn('setInterval(refreshSelectedJob, 5000)', app_js)
        self.assertIn('state.selectedJobExecutionId', app_js)
        self.assertIn('itemPanel.style.display = "none"', app_js)
        self.assertNotIn('await loadJobItems(id)', app_js)
        self.assertIn('run_2560_now', app_js)

    def test_jobs_queue_filter_builds_whitelist_query(self):
        clause, params = jobs._queue_job_type_filter(["run_2560", "build_30m"])

        self.assertEqual(clause, "WHERE job_type IN :job_types")
        self.assertEqual(params, {"job_types": ("run_2560", "build_30m")})

    def test_data_prep_page_does_not_start_2560_jobs(self):
        static_dir = jobs.PROJECT_ROOT / "app" / "static"
        addon_js = (static_dir / "data_import_type_addon.js").read_text(encoding="utf-8")
        page_js = (static_dir / "data_import_page.js").read_text(encoding="utf-8")
        combined = addon_js + "\n" + page_js

        self.assertNotIn("run2560AfterImportBtn", combined)
        self.assertNotIn("跑2560", combined)
        self.assertNotIn("/api/jobs/run-now", combined)
        self.assertIn("指标完成后，到“计算任务 → 创建批量任务”执行 2560 扫描", addon_js)

    def test_data_import_page_uses_execution_and_shard_hierarchy(self):
        static_dir = jobs.PROJECT_ROOT / "app" / "static"
        page_js = (static_dir / "data_import_page.js").read_text(encoding="utf-8")
        addon_js = (static_dir / "data_import_type_addon.js").read_text(encoding="utf-8")
        combined = page_js + "\n" + addon_js

        self.assertIn("任务执行记录（job_execution）", page_js)
        self.assertIn("Shard 汇总（每行是一组并发线程）", page_js)
        self.assertIn("importExecutionTable", page_js)
        self.assertIn("importShardTable", page_js)
        self.assertIn("importFilePanel", page_js)
        self.assertIn("toggleImportFilesBtn", page_js)
        self.assertIn("importFilePanel.style.display = 'none'", combined)
        self.assertIn("Asia/Shanghai", addon_js)
        self.assertIn("defaultChinaMarketDate", addon_js)
        self.assertIn("setImportDateDefaults", addon_js)
        self.assertIn("日期范围怎么选", addon_js)
        self.assertIn("从5m生成30m：日常增量选当天", addon_js)
        self.assertIn("首次补历史或30m不足25根", addon_js)
        self.assertIn("重算指标：时间范围跟30m构建保持一致", addon_js)
        self.assertNotIn("setInterval(boot, 1000)", combined)
        self.assertIn("setInterval(function(){", addon_js)
        self.assertIn("}, 5000)", addon_js)

    def test_nested_menu_is_static_without_auto_collapse(self):
        static_dir = jobs.PROJECT_ROOT / "app" / "static"
        menu_js = (static_dir / "nested_menu_reorg.js").read_text(encoding="utf-8")
        module_js = (static_dir / "module_reorg.js").read_text(encoding="utf-8")
        menu_css = (static_dir / "nested_menu_reorg.css").read_text(encoding="utf-8")

        self.assertIn("nav.dataset.staticMenuApplied", menu_js)
        self.assertIn("nav-static-group", menu_js)
        self.assertNotIn("collapsed", menu_js)
        self.assertNotIn("userExpandedGroups", menu_js)
        self.assertNotIn("setInterval(boot", menu_js)
        self.assertNotIn("setInterval(boot", module_js)
        self.assertNotIn(".nav-group.collapsed", menu_css)

    def test_jobs_execution_order_prioritizes_active_tasks(self):
        self.assertIn("CASE status WHEN 'running' THEN 0 WHEN 'cancelling' THEN 1 WHEN 'queued' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END", jobs._execution_order_sql())

    def test_jobs_queue_order_prioritizes_running_then_recent_tasks(self):
        order_sql = jobs._queue_order_sql()

        self.assertIn("CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'pending' THEN 1 ELSE 2 END", order_sql)
        self.assertIn("created_at DESC", order_sql)
        self.assertIn("id DESC", order_sql)
        self.assertNotIn("priority ASC", order_sql)

    def test_jobs_execution_filter_builds_whitelist_query(self):
        clause, params = jobs._execution_job_type_filter(["run_2560", "run_2560_now", "import_vipdoc"])

        self.assertEqual(clause, "WHERE job_type IN :job_types")
        self.assertEqual(params, {"job_types": ("run_2560", "run_2560_now", "import_vipdoc")})

    def test_jobs_execution_filter_ignores_empty_values(self):
        clause, params = jobs._execution_job_type_filter(["", "  ", None])

        self.assertEqual(clause, "")
        self.assertEqual(params, {})


if __name__ == "__main__":
    unittest.main()
