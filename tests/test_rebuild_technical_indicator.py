import unittest

import pandas as pd

from scripts import rebuild_technical_indicator


class RebuildTechnicalIndicatorTests(unittest.TestCase):
    def test_selects_preferred_source_and_keeps_one_bar_per_date(self):
        df = pd.DataFrame(
            [
                {"code": "sh.600000", "date": 20260401, "source": "tdx", "close": 10.0},
                {"code": "sh.600000", "date": 20260401, "source": "vipdoc", "close": 11.0},
                {"code": "sh.600000", "date": 20260402, "source": "vipdoc", "close": 12.0},
            ]
        )

        out = rebuild_technical_indicator.select_source_rows(df, "vipdoc")

        self.assertEqual(out["date"].tolist(), [20260401, 20260402])
        self.assertEqual(out["source"].tolist(), ["vipdoc", "vipdoc"])
        self.assertEqual(out["close"].tolist(), [11.0, 12.0])


if __name__ == "__main__":
    unittest.main()
