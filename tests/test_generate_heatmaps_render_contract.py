import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from unittest import mock


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

yaml_stub = types.ModuleType("yaml")
yaml_stub.safe_load = lambda *_args, **_kwargs: {}
sys.modules.setdefault("yaml", yaml_stub)

import generate_heatmaps  # noqa: E402


class GenerateHeatmapsRenderContractTests(unittest.TestCase):
    def test_year_range_uses_start_date_lookback_or_data(self) -> None:
        with mock.patch("generate_heatmaps.utc_now", return_value=datetime(2026, 2, 14, tzinfo=timezone.utc)):
            years_from_start = generate_heatmaps._year_range_from_config(
                {"sync": {"start_date": "2024-03-01"}},
                {"2025": {}},
            )
            years_from_lookback = generate_heatmaps._year_range_from_config(
                {"sync": {"lookback_years": 2}},
                {"2020": {}},
            )
            years_from_data = generate_heatmaps._year_range_from_config(
                {"sync": {}},
                {"2021": {}, "2023": {}},
            )

        self.assertEqual(years_from_start, [2024, 2025, 2026])
        self.assertEqual(years_from_lookback, [2025, 2026])
        self.assertEqual(years_from_data, [2021, 2022, 2023, 2024, 2025, 2026])

    def test_type_totals_sums_positive_counts_only(self) -> None:
        aggregates_years = {
            "2025": {
                "Run": {
                    "2025-01-01": {"count": 2},
                    "2025-01-02": {"count": 0},
                },
                "Ride": {
                    "2025-01-01": {"count": 3},
                },
            },
            "2026": {
                "Run": {
                    "2026-01-01": {"count": 1},
                }
            },
        }
        self.assertEqual(generate_heatmaps._type_totals(aggregates_years), {"Run": 3, "Ride": 3})

    def test_svg_for_year_contains_expected_labels_and_titles(self) -> None:
        entries = {
            "2025-01-01": {
                "count": 2,
                "distance": 1609.344,
                "moving_time": 3600,
                "elevation_gain": 100,
                "activity_ids": ["a", "b"],
            }
        }
        svg = generate_heatmaps._svg_for_year(
            2025,
            entries,
            {"distance": "mi", "elevation": "ft"},
            generate_heatmaps.DEFAULT_COLORS,
        )

        self.assertIn(">2025</text>", svg)
        self.assertIn(">Jan</text>", svg)
        self.assertIn(">Dec</text>", svg)
        self.assertIn(">Sun</text>", svg)
        self.assertIn(">Sat</text>", svg)
        self.assertIn('data-date="2025-01-01"', svg)
        self.assertIn("<title>2025-01-01\n2 workouts\nDistance: 1.00 mi\nDuration: 1h 0m\nElevation: 328 ft</title>", svg)

    def test_load_activities_filters_invalid_rows_and_parses_hour(self) -> None:
        rows = [
            {
                "date": "2026-02-01",
                "year": 2026,
                "type": "Run",
                "raw_type": "Run",
                "start_date_local": "2026-02-01T09:15:00+00:00",
            },
            {
                "date": "2026-02-02",
                "year": 2026,
                "type": "Ride",
                "raw_type": "Ride",
                "start_date_local": "bad-date",
            },
            {"date": "2026-02-03", "year": 2026, "type": "Run"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            activities_path = os.path.join(tmpdir, "activities_normalized.json")
            with open(activities_path, "w", encoding="utf-8") as handle:
                json.dump(rows, handle)

            with mock.patch("generate_heatmaps.ACTIVITIES_PATH", activities_path):
                activities = generate_heatmaps._load_activities()

        self.assertEqual(len(activities), 2)
        self.assertEqual(activities[0]["hour"], 9)
        self.assertIsNone(activities[1]["hour"])


if __name__ == "__main__":
    unittest.main()
