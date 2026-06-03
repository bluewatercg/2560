from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.job_runtime_store import JobProgressReporter, JobRuntimeStore
from app.api import jobs


class JobRuntimeStoreTests(unittest.TestCase):
    def test_progress_snapshot_round_trips_with_runtime_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobRuntimeStore(Path(tmp))

            written = store.write_progress(
                123,
                {
                    "status": "running",
                    "done": 7,
                    "total": 10,
                    "success_count": 6,
                    "failed_count": 1,
                    "current_code": "sh.600000",
                    "message": "batch 2/3",
                },
            )

            self.assertEqual(written["job_id"], 123)
            self.assertEqual(written["done"], 7)
            self.assertIn("updated_at", written)
            self.assertEqual(store.read_progress(123), written)

    def test_missing_progress_snapshot_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobRuntimeStore(Path(tmp))

            self.assertIsNone(store.read_progress(404))

    def test_tail_log_returns_last_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobRuntimeStore(Path(tmp))
            log_path = store.log_path(9)
            log_path.write_text("a\nb\nc\nd\n", encoding="utf-8")

            self.assertEqual(store.tail_log(9, 2), ["c", "d"])

    def test_log_path_is_per_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobRuntimeStore(Path(tmp))

            self.assertEqual(store.log_path(55), Path(tmp) / "job_55.log")
            self.assertEqual(store.progress_path(55), Path(tmp) / "job_55.progress.json")

    def test_progress_reporter_writes_every_snapshot_and_throttles_mysql(self):
        now = [100.0]

        with tempfile.TemporaryDirectory() as tmp:
            store = JobRuntimeStore(Path(tmp))
            reporter = JobProgressReporter(123, store, mysql_interval_seconds=5, clock=lambda: now[0])

            self.assertTrue(reporter.report({"done": 1, "total": 10}))
            self.assertEqual(store.read_progress(123)["done"], 1)

            now[0] = 101.0
            self.assertFalse(reporter.report({"done": 2, "total": 10}))
            self.assertEqual(store.read_progress(123)["done"], 2)

            now[0] = 106.0
            self.assertTrue(reporter.report({"done": 3, "total": 10}))

            now[0] = 107.0
            self.assertTrue(reporter.report({"done": 4, "total": 10}, force_mysql=True))

    def test_jobs_api_progress_prefers_runtime_snapshot(self):
        row = {
            "id": 77,
            "status": "running",
            "progress_current": 1,
            "progress_total": 100,
            "success_count": 1,
            "failed_count": 0,
            "current_code": "old",
            "message": "old message",
            "elapsed_seconds": 20,
        }
        runtime = {
            "job_id": 77,
            "status": "running",
            "done": 40,
            "total": 100,
            "success_count": 39,
            "failed_count": 1,
            "current_code": "sh.600000",
            "message": "runtime message",
        }

        merged = jobs._build_progress_response(row, runtime)

        self.assertEqual(merged["done"], 40)
        self.assertEqual(merged["progress_current"], 40)
        self.assertEqual(merged["success_count"], 39)
        self.assertEqual(merged["current_code"], "sh.600000")
        self.assertEqual(merged["message"], "runtime message")
        self.assertEqual(merged["percent"], 40.0)

    def test_jobs_api_log_file_prefers_runtime_log_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobRuntimeStore(Path(tmp))
            store.ensure_log_file(88)

            resolved = jobs._resolve_execution_log_file({"log_file": "/old/shared.log"}, 88, store)

            self.assertEqual(resolved, Path(tmp) / "job_88.log")

    def test_error_log_falls_back_to_runtime_log(self):
        original_store = jobs.RUNTIME_STORE
        with tempfile.TemporaryDirectory() as tmp:
            store = JobRuntimeStore(Path(tmp))
            store.append_log_line(91, "first")
            store.append_log_line(91, "failure")
            jobs.RUNTIME_STORE = store
            try:
                result = jobs.execution_error_log(91)
            finally:
                jobs.RUNTIME_STORE = original_store

            self.assertTrue(result["ok"])
            self.assertIn("failure", result["content"])
            self.assertEqual(result["message"], "stderr is merged into job log")


if __name__ == "__main__":
    unittest.main()
