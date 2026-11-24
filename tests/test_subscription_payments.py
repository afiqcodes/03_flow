"""Subscription payment routes, schedules, and transaction behavior."""

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import psycopg2
from werkzeug.exceptions import NotFound

import app as todo

TODAY = date(2026, 11, 4)
DUE = date(2026, 10, 31)


def subscription_record():
    return dict(
        id=7, name="Music", price=Decimal("19.90"), billing_cycle="monthly",
        next_billing_date=DUE, subscription_type="Streaming", active=True,
    )


class SubscriptionPaymentTests(unittest.TestCase):
    def setUp(self):
        todo.app.config["TESTING"] = True
        self.client = todo.app.test_client()
        today = patch.object(todo, "local_today", return_value=TODAY)
        today.start()
        self.addCleanup(today.stop)
        self.form = {"due_on": DUE.isoformat(), "paid_on": TODAY.isoformat()}

    def test_subscription_payment_form_and_history_links(self):
        plan = subscription_record()
        with patch.object(todo, "fetch_all", return_value=[plan]):
            page = self.client.get("/subscriptions?pay=7").get_data(as_text=True)
        self.assertIn('href="/expenses?subscription=7"', page)
        self.assertIn('action="/subscriptions/pay/7"', page)
        self.assertIn('name="due_on" value="2026-10-31"', page)
        self.assertIn('max="2026-11-04" value="2026-11-04"', page)
        self.assertIn("$19.90", page)

    def test_success_and_stale_or_duplicate_payment(self):
        with patch.object(todo, "record_subscription_payment", return_value=True) as record:
            response = self.client.post("/subscriptions/pay/7", data={**self.form, "amount": "1"})
        self.assertEqual(response.location, "/subscriptions?saved=1&paid=1")
        record.assert_called_once_with(7, DUE, TODAY)
        for outcome in (False, psycopg2.errors.UniqueViolation()):
            with self.subTest(outcome=outcome), \
                    patch.object(todo, "fetch_all", return_value=[]), \
                    patch.object(todo, "record_subscription_payment") as record:
                if isinstance(outcome, Exception):
                    record.side_effect = outcome
                else:
                    record.return_value = outcome
                response = self.client.post("/subscriptions/pay/7", data=self.form)
                self.assertEqual(response.status_code, 409)
                self.assertIn(b"already recorded", response.data)

    def test_invalid_dates_do_not_record_expenses(self):
        cases = ({"paid_on": "bad"}, {"paid_on": "2026-11-05"},
                 {"paid_on": "1999-12-31"}, {"due_on": "2026-02-30"},
                 {"due_on": "2201-01-01"})
        with patch.object(todo, "fetch_all", return_value=[]), \
                patch.object(todo, "record_subscription_payment") as record:
            for changes in cases:
                with self.subTest(changes=changes):
                    response = self.client.post("/subscriptions/pay/7", data={**self.form, **changes})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(b'role="alert"', response.data)
            record.assert_not_called()

    def test_month_end_year_end_and_leap_year_schedules(self):
        cases = (
            (date(2026, 1, 31), "monthly", 31, date(2026, 2, 28)),
            (date(2026, 2, 28), "monthly", 31, date(2026, 3, 31)),
            (date(2024, 1, 31), "monthly", 31, date(2024, 2, 29)),
            (date(2026, 12, 15), "monthly", 15, date(2027, 1, 15)),
            (date(2024, 2, 29), "yearly", 29, date(2025, 2, 28)),
            (date(2027, 2, 28), "yearly", 29, date(2028, 2, 29)),
        )
        for due_on, cycle, day, expected in cases:
            with self.subTest(due_on=due_on, cycle=cycle):
                self.assertEqual(todo.next_subscription_billing_date(due_on, cycle, day), expected)
        with self.assertRaises(ValueError):
            todo.next_subscription_billing_date(date(2200, 12, 1), "monthly")

    def connection(self, plan):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = plan
        return connection, cursor

    def test_payment_uses_saved_price_and_commits_before_closing(self):
        connection, cursor = self.connection(subscription_record())
        with patch.object(todo, "get_connection", return_value=connection):
            self.assertTrue(todo.record_subscription_payment(7, DUE, TODAY))
        queries = cursor.execute.call_args_list
        self.assertIn("FOR UPDATE", queries[0].args[0])
        self.assertEqual(queries[1].args[1], (
            "Music", Decimal("19.90"), TODAY,
            "Monthly subscription bill due 2026-10-31.", 7, DUE,
        ))
        self.assertEqual(queries[2].args[1], (date(2026, 11, 30), 31, 7))
        connection.__exit__.assert_called_once_with(None, None, None)
        connection.close.assert_called_once_with()

    def test_schedule_failure_rolls_back_payment(self):
        connection, cursor = self.connection(subscription_record())
        cursor.execute.side_effect = [None, None, RuntimeError("Schedule failed")]
        with patch.object(todo, "get_connection", return_value=connection):
            with self.assertRaises(RuntimeError):
                todo.record_subscription_payment(7, DUE, TODAY)
        self.assertIs(connection.__exit__.call_args.args[0], RuntimeError)
        connection.close.assert_called_once_with()

    def test_stale_paused_free_and_missing_plans_cannot_record(self):
        plans = [subscription_record(), {**subscription_record(), "active": False},
                 {**subscription_record(), "price": Decimal("0")}, None]
        for index, plan in enumerate(plans):
            connection, cursor = self.connection(plan)
            with self.subTest(plan=plan), patch.object(todo, "get_connection", return_value=connection):
                if index == 0:
                    self.assertFalse(todo.record_subscription_payment(7, date(2026, 9, 30), TODAY))
                elif plan is None:
                    with todo.app.test_request_context():
                        with self.assertRaises(NotFound):
                            todo.record_subscription_payment(7, DUE, TODAY)
                else:
                    with self.assertRaises(ValueError):
                        todo.record_subscription_payment(7, DUE, TODAY)
            self.assertEqual(cursor.execute.call_count, 1)

    def test_payment_history_filters_month_but_keeps_monthly_totals(self):
        transaction = dict(
            id=4, title="Music", kind="expense", category="bills", amount=Decimal("19.90"),
            occurred_on=TODAY, description="Monthly bill", subscription_id=7,
            subscription_due_on=DUE, subscription_name="Music",
        )
        with patch.object(todo, "fetch_all", side_effect=[
            [{"id": 7, "name": "Music"}], [transaction],
            [{"kind": "expense", "category": "bills", "total": Decimal("39.80")}], [],
        ]) as read:
            response = self.client.get("/expenses?subscription=7&month=2026-11")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(read.call_args_list[1].args[1], (date(2026, 11, 1), date(2026, 12, 1), 7, 7))
        self.assertIn(b'Payment history for', response.data)
        self.assertIn(b'$39.80', response.data)
        self.assertIn(b'name="subscription" value="7"', response.data)
        self.assertIn(b'/subscriptions#subscription-7', response.data)

    def test_linked_payment_cannot_be_changed_to_income(self):
        with patch.object(todo, "fetch_all", return_value=[{
            "subscription_id": 7, "subscription_due_on": DUE,
        }]), patch.object(todo, "render_expenses", return_value=("Invalid", 400)), \
                patch.object(todo, "execute_write") as write:
            response = self.client.post("/expenses/save", data={
                "id": "4", "title": "Music", "kind": "income", "category": "refunds",
                "amount": "19.90", "occurred_on": TODAY.isoformat(),
            })
        self.assertEqual(response.status_code, 400)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
