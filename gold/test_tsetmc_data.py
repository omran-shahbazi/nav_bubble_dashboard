import tempfile
import unittest
from pathlib import Path

import pandas as pd

import tsetmc_data


class MarketDateHistoryTests(unittest.TestCase):
    def test_snapshots_with_the_same_market_date_are_one_observation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            original_data_dir = tsetmc_data.DATA_DIR
            original_history_path = tsetmc_data.HISTORY_CSV_PATH
            try:
                tsetmc_data.DATA_DIR = Path(temporary_directory)
                tsetmc_data.HISTORY_CSV_PATH = Path(temporary_directory) / "history.csv"
                snapshots = pd.DataFrame(
                    [
                        {
                            "symbol": "طلا", "fund_name": "طلا", "observed_at": "2026-09-01T15:00:00+03:30",
                            "market_date": "20260901", "last_price": 101, "nav": 100, "nav_bubble": 1,
                        },
                        {
                            "symbol": "طلا", "fund_name": "طلا", "observed_at": "2026-09-02T15:00:00+03:30",
                            "market_date": "20260901", "last_price": 102, "nav": 100, "nav_bubble": 2,
                        },
                    ]
                )
                tsetmc_data.append_daily_snapshot(snapshots.iloc[[0]])
                history = tsetmc_data.append_daily_snapshot(snapshots.iloc[[1]])
            finally:
                tsetmc_data.DATA_DIR = original_data_dir
                tsetmc_data.HISTORY_CSV_PATH = original_history_path

        self.assertEqual(len(history), 1)
        self.assertEqual(history.iloc[0].market_date, "2026-09-01")
        self.assertEqual(history.iloc[0].nav_bubble, 2)


if __name__ == "__main__":
    unittest.main()
