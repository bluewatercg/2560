from __future__ import annotations

import sys
import struct
import tempfile
import unittest
from pathlib import Path

from app.api import jobs
from app.api.import_data import _merge_job_progress, _merge_data_range
from app.services.job_orchestrator import ensure_job_tables
from scripts import job_worker
from scripts.import_vipdoc_with_pytdx import scan_vipdoc_files


class JobOrchestrationTests(unittest.TestCase):
    def test_jobs_api_uses_shared_job_schema_helper(self):
        self.assertIs(jobs._ensure_tables, ensure_job_tables)

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


if __name__ == "__main__":
    unittest.main()
