import unittest

from app.services.annotation_engine_2568 import AnnotationEngine2568


class Annotation2568FreshnessTests(unittest.TestCase):
    def test_indicator_freshness_marks_recalculated_stock(self):
        engine = AnnotationEngine2568(db=None)

        fields = engine._freshness_fields(
            indicator={"date": 20260512, "updated_at": "2026-05-12 18:30:00"},
            latest_indicator_date=20260512,
            latest_signal={"batch_id": 20260512190000, "signal_time": 20260512143000},
            latest_batch={"batch_id": 20260512190000, "run_time": "2026-05-12 19:00:00"},
        )

        self.assertEqual(fields["indicator_freshness_status"], "已重算")
        self.assertEqual(fields["indicator_date"], 20260512)
        self.assertEqual(fields["indicator_recalculated_at"], "2026-05-12 18:30:00")
        self.assertEqual(fields["latest_2560_status"], "命中")
        self.assertEqual(fields["latest_2560_batch_id"], 20260512190000)
        self.assertEqual(fields["latest_2560_run_time"], "2026-05-12 19:00:00")
        self.assertEqual(fields["latest_2560_signal_time"], 20260512143000)

    def test_indicator_freshness_marks_stale_stock(self):
        engine = AnnotationEngine2568(db=None)

        fields = engine._freshness_fields(
            indicator={"date": 20260510, "updated_at": "2026-05-10 18:30:00"},
            latest_indicator_date=20260512,
            latest_signal=None,
            latest_batch={"batch_id": 20260512190000, "run_time": "2026-05-12 19:00:00"},
        )

        self.assertEqual(fields["indicator_freshness_status"], "未更新到最新")
        self.assertEqual(fields["latest_2560_status"], "未命中")

    def test_indicator_freshness_marks_missing_stock(self):
        engine = AnnotationEngine2568(db=None)

        fields = engine._freshness_fields(
            indicator=None,
            latest_indicator_date=20260512,
            latest_signal=None,
            latest_batch=None,
        )

        self.assertEqual(fields["indicator_freshness_status"], "缺指标")
        self.assertEqual(fields["indicator_date"], None)
        self.assertEqual(fields["indicator_recalculated_at"], None)
        self.assertEqual(fields["latest_2560_status"], "未计算")


if __name__ == "__main__":
    unittest.main()
