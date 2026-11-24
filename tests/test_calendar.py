"""Calendar rendering and holiday cache behavior without a database connection."""

import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import URLError

import app as todo


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.client = todo.app.test_client()

    def test_leap_year_and_state_holiday_render(self):
        holidays = [{"date": "2028-02-29", "name": "Example Holiday"}]
        with patch.object(todo, "get_public_holidays", return_value=(holidays, None)) as get_holidays:
            page = self.client.get("/calendar?year=2028&state=SBH").get_data(as_text=True)

        get_holidays.assert_called_once_with(2028, "SBH")
        self.assertEqual(page.count('class="year-month"'), 12)
        self.assertIn('datetime="2028-02-29"', page)
        self.assertIn("Example Holiday", page)
        self.assertIn("<strong>Sabah</strong> public holidays", page)
        self.assertIn('href="/calendar?year=2027&amp;state=SBH"', page)
        self.assertIn('aria-label="Open calendar"', page)

    def test_outside_provider_year_still_renders_calendar(self):
        with patch.object(todo, "fetch_all", return_value=[]), patch.object(todo, "urlopen") as opener:
            page = self.client.get("/calendar?year=1&state=KUL").get_data(as_text=True)

        opener.assert_not_called()
        self.assertEqual(page.count('class="year-month"'), 12)
        self.assertIn("Holiday data is available for 2000–2100 only.", page)

    def test_sidebar_groups_holidays_by_month_with_dates_on_right(self):
        holidays = [
            {"date": "2028-12-25", "name": "December Holiday"},
            {"date": "2028-01-20", "name": "Later January Holiday"},
            {"date": "2028-01-01", "name": "January Holiday"},
        ]
        with patch.object(todo, "get_public_holidays", return_value=(holidays, None)):
            page = self.client.get("/calendar?year=2028").get_data(as_text=True)

        sidebar = page.split('<div class="calendar-holiday-list">', 1)[1]
        self.assertLess(sidebar.index("<h4>January</h4>"), sidebar.index("<h4>December</h4>"))
        self.assertNotIn("<h4>February</h4>", sidebar)
        self.assertLess(sidebar.index("<span>January Holiday</span>"),
                        sidebar.index('<time datetime="2028-01-01">'))
        self.assertLess(sidebar.index('datetime="2028-01-01"'),
                        sidebar.index('datetime="2028-01-20"'))

    def test_holidays_are_cached_and_stale_cache_survives_outage(self):
        payload = {"data": [{"date": "2026-05-30", "name": "Pesta Kaamatan"}]}
        response = io.BytesIO(json.dumps(payload).encode())
        with patch.object(todo, "fetch_all", return_value=[]), \
                patch.object(todo, "urlopen", return_value=response), \
                patch.object(todo, "execute_write") as write:
            holidays, message = todo.get_public_holidays(2026, "SBH")

        self.assertIsNone(message)
        self.assertEqual(holidays[0]["name"], "Pesta Kaamatan")
        self.assertIn('"date": "2026-05-30"', write.call_args.args[1][2])

        stale = {"holidays": holidays,
                 "fetched_at": datetime.now(timezone.utc) - timedelta(days=2)}
        with patch.object(todo, "fetch_all", return_value=[stale]), \
                patch.object(todo, "urlopen", side_effect=URLError("offline")):
            saved, message = todo.get_public_holidays(2026, "SBH")

        self.assertEqual(saved, holidays)
        self.assertIn("saved holiday data", message)

    def test_connection_reset_keeps_the_calendar_available(self):
        with patch.object(todo, "fetch_all", return_value=[]), \
                patch.object(todo, "urlopen", side_effect=ConnectionResetError("reset")):
            response = self.client.get("/calendar?year=2026")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Holiday service is unavailable", response.data)


if __name__ == "__main__":
    unittest.main()
