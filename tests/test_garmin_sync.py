"""
Unit-тесты для чистых функций `scripts/garmin_sync.py`.

Запуск:
    python3.11 -m pip install pytest --break-system-packages
    python3.11 -m pytest tests/ -v

Или через стандартный unittest (без установки pytest):
    python3.11 -m unittest tests.test_garmin_sync -v

Что покрыто:
- `_extract_hrv` — все три формата ответа Garmin для HRV.
- `_extract_body_battery` — массив значений + fallback на агрегаты.
- `DEFAULT_HEADERS` — порядок и состав колонок (контракт со Sheets).
- `fetch_garmin_data` через моки — что мягко переживает пустые эндпоинты.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Чтобы импортировать scripts/garmin_sync без установки пакета
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import garmin_sync as gs  # noqa: E402


class ExtractHrvTests(unittest.TestCase):
    def test_none_returns_zero(self):
        self.assertEqual(gs._extract_hrv(None), 0)

    def test_empty_dict_returns_zero(self):
        self.assertEqual(gs._extract_hrv({}), 0)

    def test_no_summary_returns_zero(self):
        self.assertEqual(gs._extract_hrv({"foo": "bar"}), 0)

    def test_last_night_avg_primary(self):
        self.assertEqual(
            gs._extract_hrv({"hrvSummary": {"lastNightAvg": 47}}),
            47,
        )

    def test_falls_back_to_last_night_5min_high(self):
        # Если lastNightAvg отсутствует — fallback на пик
        self.assertEqual(
            gs._extract_hrv({"hrvSummary": {"lastNight5MinHigh": 62}}),
            62,
        )

    def test_falls_back_to_weekly_avg(self):
        self.assertEqual(
            gs._extract_hrv({"hrvSummary": {"weeklyAvg": 41}}),
            41,
        )

    def test_priority_order_avg_over_high(self):
        # lastNightAvg всегда побеждает над lastNight5MinHigh
        self.assertEqual(
            gs._extract_hrv({"hrvSummary": {"lastNightAvg": 50, "lastNight5MinHigh": 80}}),
            50,
        )

    def test_falsy_value_skipped(self):
        # Если lastNightAvg=0/None — переходим к следующему ключу
        self.assertEqual(
            gs._extract_hrv({"hrvSummary": {"lastNightAvg": 0, "lastNight5MinHigh": 70}}),
            70,
        )


class ExtractBodyBatteryTests(unittest.TestCase):
    def test_none_returns_zero_zero(self):
        self.assertEqual(gs._extract_body_battery(None), (0, 0))

    def test_empty_list_returns_zero_zero(self):
        self.assertEqual(gs._extract_body_battery([]), (0, 0))

    def test_not_a_list_returns_zero_zero(self):
        self.assertEqual(gs._extract_body_battery({"foo": "bar"}), (0, 0))

    def test_full_array_max_min(self):
        bb = [{
            "bodyBatteryValuesArray": [
                [1714000000000, "ACTIVE", 80, 1],
                [1714000300000, "ACTIVE", 65, 1],
                [1714000600000, "RESTING", 95, 1],
                [1714000900000, "RESTING", 30, 1],
            ]
        }]
        max_v, min_v = gs._extract_body_battery(bb)
        self.assertEqual((max_v, min_v), (95, 30))

    def test_skips_malformed_entries(self):
        # Перемешиваем валидные точки и мусор — мусор должен игнорироваться
        bb = [{
            "bodyBatteryValuesArray": [
                [1714000000000, "ACTIVE", 80, 1],
                "garbage",
                [1714000300000],            # короткая запись
                [1714000600000, "X", "55"], # значение строкой
                [1714000900000, "Y", 70, 1],
            ]
        }]
        max_v, min_v = gs._extract_body_battery(bb)
        self.assertEqual((max_v, min_v), (80, 70))

    def test_falls_back_to_aggregates_if_array_empty(self):
        bb = [{"bodyBatteryValuesArray": [], "charged": 50, "drained": 12}]
        self.assertEqual(gs._extract_body_battery(bb), (50, 12))

    def test_falls_back_to_aggregates_if_no_array(self):
        bb = [{"charged": 88, "drained": 22}]
        self.assertEqual(gs._extract_body_battery(bb), (88, 22))

    def test_aggregates_default_to_zero(self):
        bb = [{"charged": None, "drained": None}]
        self.assertEqual(gs._extract_body_battery(bb), (0, 0))


class DefaultHeadersTests(unittest.TestCase):
    def test_required_columns_present(self):
        # Контракт: эти колонки точно должны быть. Если кто-то их переименует —
        # мы про это узнаем.
        required = {
            "date", "sleep_hours", "sleep_score",
            "hrv_last_night", "steps", "stress_avg",
            "body_battery_max", "body_battery_min",
        }
        self.assertTrue(required.issubset(set(gs.DEFAULT_HEADERS)))

    def test_date_is_first(self):
        self.assertEqual(gs.DEFAULT_HEADERS[0], "date")


class FetchGarminDataTests(unittest.TestCase):
    """Тестируем агрегацию через моки клиента — без реальных API-вызовов."""

    def _make_client(self, *, sleep=None, stats=None, hrv=None, bb=None):
        client = MagicMock()
        client.get_sleep_data.return_value = sleep or {}
        client.get_stats.return_value = stats or {}
        client.get_hrv_data.return_value = hrv or {}
        client.get_body_battery.return_value = bb or []
        return client

    def test_full_happy_path(self):
        sleep = {"dailySleepDTO": {
            "sleepTimeSeconds": 7 * 3600 + 12 * 60,  # 7,2 ч
            "sleepScores": {"overall": {"value": 78}},
        }}
        stats = {"totalSteps": 8432, "averageStressLevel": 32}
        hrv = {"hrvSummary": {"lastNightAvg": 48}}
        bb = [{"bodyBatteryValuesArray": [
            [1, "A", 82, 1], [2, "B", 18, 1],
        ]}]
        client = self._make_client(sleep=sleep, stats=stats, hrv=hrv, bb=bb)

        result = gs.fetch_garmin_data(client, "2026-04-23")

        self.assertEqual(result["date"], "2026-04-23")
        self.assertAlmostEqual(result["sleep_hours"], 7.2, places=2)
        self.assertEqual(result["sleep_score"], 78)
        self.assertEqual(result["body_battery_max"], 82)
        self.assertEqual(result["body_battery_min"], 18)
        self.assertEqual(result["hrv_last_night"], 48)
        self.assertEqual(result["steps"], 8432)
        self.assertEqual(result["stress_avg"], 32)

    def test_all_endpoints_empty_no_crash(self):
        # Все эндпоинты вернули пусто — должны получить нули, не исключение
        client = self._make_client()
        result = gs.fetch_garmin_data(client, "2026-04-23")
        self.assertEqual(result["sleep_hours"], 0.0)
        self.assertEqual(result["sleep_score"], 0)
        self.assertEqual(result["hrv_last_night"], 0)
        self.assertEqual(result["body_battery_max"], 0)
        self.assertEqual(result["body_battery_min"], 0)
        self.assertEqual(result["steps"], 0)
        self.assertEqual(result["stress_avg"], 0)

    def test_partial_data_only_steps(self):
        # Stats отдал только steps, остальное None / empty — не должно падать
        client = self._make_client(stats={"totalSteps": 12000})
        result = gs.fetch_garmin_data(client, "2026-04-23")
        self.assertEqual(result["steps"], 12000)
        self.assertEqual(result["stress_avg"], 0)

    def test_endpoint_raises_does_not_crash(self):
        # Если один эндпоинт кидает исключение, _safe_call должен его проглотить.
        client = MagicMock()
        client.get_sleep_data.side_effect = RuntimeError("boom")
        client.get_stats.return_value = {"totalSteps": 5000}
        client.get_hrv_data.return_value = {}
        client.get_body_battery.return_value = []

        result = gs.fetch_garmin_data(client, "2026-04-23")
        self.assertEqual(result["sleep_hours"], 0.0)
        self.assertEqual(result["steps"], 5000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
