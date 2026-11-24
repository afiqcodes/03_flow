"""Regression checks for form validation and consistent local dates."""

import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import app as todo


class FormValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = todo.app.test_client()

    def test_subscription_prices_fit_database_without_rounding(self):
        form = dict(name="Service", price="10", billing_cycle="monthly",
                    next_billing_date="2026-11-04", subscription_type="Software")
        with patch.object(todo, "execute_write", return_value=1) as write:
            for price in ("100000000", "99999999.995", "1.001", "-1", "NaN",
                          "sNaN", "Infinity", "1e999999", "1e-999999", "bad", ""):
                with self.subTest(price=price):
                    response = self.client.post("/subscriptions/add", data={**form, "price": price})
                    self.assertEqual(response.status_code, 302)
                    self.assertNotIn("saved=1", response.location)
            for day in ("1999-12-31", "2201-01-01"):
                self.client.post("/subscriptions/add", data={**form, "next_billing_date": day})
            write.assert_not_called()
            for price in ("0", "10.000", "99999999.99"):
                response = self.client.post("/subscriptions/add", data={**form, "price": price})
                self.assertIn("saved=1", response.location)
                self.assertEqual(write.call_args.args[1][1], Decimal(price))

    def test_all_budget_fields_reject_overflow_and_fractional_cents(self):
        form = dict(year="2026", month="11", **dict.fromkeys(todo.BUDGET_FIELDS, "0"))
        with patch.object(todo, "execute_write", return_value=1) as write:
            for field in todo.BUDGET_FIELDS:
                for value in ("10000000000", "9999999999.999", "0.001", "NaN", "1e999999"):
                    with self.subTest(field=field, value=value):
                        response = self.client.post("/budgets/set", data={**form, field: value})
                        self.assertNotIn("saved=1", response.location)
            write.assert_not_called()
            response = self.client.post("/budgets/set", data={**form, "income": "9999999999.99"})
            self.assertIn("saved=1", response.location)
            self.assertEqual(write.call_args.args[1][2], todo.MAX_MONEY)

    def test_extreme_transaction_amounts_return_validation_errors(self):
        form = dict(title="Lunch", kind="expense", category="food", occurred_on="2026-11-04")
        with patch.object(todo, "fetch_all", return_value=[]), \
                patch.object(todo, "execute_write") as write:
            for amount in ("1e999999", "1e-999999", "sNaN", "9999999999.999"):
                with self.subTest(amount=amount):
                    response = self.client.post("/expenses/save", data={**form, "amount": amount})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(b'role="alert"', response.data)
            write.assert_not_called()

    def test_malformed_links_are_rejected_and_valid_links_are_normalized(self):
        invalid = ("https://[broken", "https://example.com:bad", "https://example.com:65536",
                   "https://user@", "https://example.com/\npath", "https://example.com/\x00",
                   "https://example.com\\path", "javascript:alert(1)", "ftp://example.com")
        for url in invalid:
            with self.subTest(url=url):
                self.assertIsNone(todo.normalize_url(url))
                with patch.object(todo, "execute_write") as write:
                    response = self.client.post("/bookmarks/add", data={"title": "Link", "url": url})
                self.assertEqual(response.location, "/bookmarks")
                write.assert_not_called()
        for raw, expected in (
            ("example.com/docs", "https://example.com/docs"),
            (" //example.com/docs ", "https://example.com/docs"),
            ("http://localhost:5000", "http://localhost:5000"),
            ("https://[::1]:443/docs", "https://[::1]:443/docs"),
        ):
            with self.subTest(url=raw):
                self.assertEqual(todo.normalize_url(raw), expected)

    def test_missing_records_return_404_for_record_actions(self):
        paths = ("/toggle/999", "/delete/999", "/subscriptions/toggle/999",
                 "/subscriptions/delete/999", "/bookmarks/delete/999", "/budgets/delete/999",
                 "/notes/pin/999", "/notes/delete/999", "/expenses/delete/999")
        with patch.object(todo, "execute_write", return_value=0):
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(self.client.post(path).status_code, 404)


class LocalDateTests(unittest.TestCase):
    def setUp(self):
        self.client = todo.app.test_client()

    def test_budget_and_logbook_use_the_same_local_date(self):
        with patch.object(todo, "local_today", return_value=date(2027, 1, 1)), \
                patch.object(todo, "fetch_all", return_value=[]):
            budget = self.client.get("/budgets").get_data(as_text=True)
            logbook = self.client.get("/logbook").get_data(as_text=True)
        self.assertIn('value="2027" required', budget)
        self.assertIn('value="2027-01-01"', logbook)

    def test_task_minimum_date_uses_local_time(self):
        now = datetime(2027, 1, 1, 0, 15, tzinfo=todo.LOCAL_TIMEZONE)
        with patch.object(todo, "local_now", return_value=now), \
                patch.object(todo, "fetch_all", return_value=[]):
            response = self.client.get("/")
            self.assertEqual(todo.local_today(), date(2027, 1, 1))
        self.assertIn(b'min="2027-01-01T00:15"', response.data)

    def test_task_due_dates_with_offsets_are_stored_as_local_time(self):
        form = dict(title="Call", description="Team meeting", due_at="2026-11-04T16:30:00+00:00")
        with patch.object(todo, "execute_write", return_value=1) as write:
            response = self.client.post("/add", data=form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(write.call_args.args[1][2], datetime(2026, 11, 5, 0, 30))

    def test_task_due_date_conversion_cannot_overflow_the_calendar(self):
        form = dict(title="Call", description="Team meeting", due_at="9999-12-31T23:00:00+00:00")
        with patch.object(todo, "execute_write") as write:
            response = self.client.post("/add", data=form,
                                        headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(response.status_code, 400)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
