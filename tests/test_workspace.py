"""Dashboard, Notes, and Expense Tracker checks, with optional PostgreSQL integration."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql

import app as todo


TODAY = date(2026, 11, 3)
UPDATED = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def note_record():
    return dict(id=1, title="Weekly ideas", content="One useful thought.\nAnother line.",
                pinned=True, project_id=None, task_id=None, project_title=None,
                task_title=None, created_at=UPDATED, updated_at=UPDATED)


class NotesTests(unittest.TestCase):
    def setUp(self):
        todo.app.config["TESTING"] = True
        self.client = todo.app.test_client()

    def test_navigation_places_sections_in_requested_groups(self):
        with patch.object(todo, "fetch_all", return_value=[]):
            page = self.client.get("/notes").get_data(as_text=True)
        shortcuts = page.split('class="titlebar-shortcuts"', 1)[1].split("</header>", 1)[0]
        self.assertLess(shortcuts.index('href="/dashboard"'), shortcuts.index('href="/calendar"'))
        personal = page.split('class="nav-group-label">Personal', 1)[1].split('<div class="nav-group">', 1)[0]
        planning = page.split('class="nav-group-label">Planning', 1)[1].split('<div class="nav-group">', 1)[0]
        finance = page.split('class="nav-group-label">Finance', 1)[1].split('<div class="nav-group">', 1)[0]
        self.assertIn('href="/notes"', personal)
        self.assertNotIn('href="/expenses"', personal)
        self.assertNotIn('href="/expenses"', planning)
        self.assertNotIn('href="/notes"', planning)
        self.assertIn('href="/expenses"', finance)
        self.assertIn('<span>EXPENSEs</span>', finance)

    def test_empty_notes_search_and_save_confirmation(self):
        with patch.object(todo, "fetch_all", return_value=[]) as read:
            page = self.client.get("/notes?saved=1").get_data(as_text=True)
            self.assertIn("No notes yet.", page)
            self.assertIn("Note saved.", page)
            page = self.client.get("/notes?q=100%25_under").get_data(as_text=True)
            self.assertIn("No notes match your search.", page)
            query, params = read.call_args_list[-3].args
            self.assertIn("ILIKE %s", query)
            self.assertEqual(params, ("100%_under", "%100\\%\\_under%", "%100\\%\\_under%"))

    def test_notes_escape_content_and_prefill_edit_form(self):
        note = note_record()
        note.update(title='<script>alert("x")</script>', content="<b>Keep as text</b>",
                    project_id=3, project_title="Project A", task_id=4, task_title="Task A")

        def rows(query, params=()):
            if "FROM notes" in query:
                return [note]
            if "FROM projects" in query:
                return [dict(id=3, title="Project A")]
            return [dict(id=4, title="Task A")]

        with patch.object(todo, "fetch_all", side_effect=rows):
            response = self.client.get("/notes?edit=1")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertIn("&lt;b&gt;Keep as text&lt;/b&gt;", page)
        self.assertIn('value="3" selected', page)
        self.assertIn('value="4" selected', page)
        self.assertIn('name="pinned" value="1" checked', page)
        self.assertIn('href="/projects?edit=3"', page)

    def test_create_and_edit_note_with_valid_links(self):
        data = dict(title="  Notes  ", content="  First line\nSecond line  ", pinned="1",
                    project_id="3", task_id="4")
        with patch.object(todo, "fetch_all", return_value=[{"id": 3}]), \
                patch.object(todo, "execute_write", return_value=1) as write:
            response = self.client.post("/notes/save", data=data)
            self.assertEqual(response.location, "/notes?saved=1")
            self.assertEqual(write.call_args.args[1], ("Notes", "First line\nSecond line", True, 3, 4))
            response = self.client.post("/notes/save", data={**data, "id": "1", "pinned": "0"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(write.call_args.args[1], ("Notes", "First line\nSecond line", False, 3, 4, 1))

    def test_invalid_notes_never_write_and_keep_form_input(self):
        valid = dict(title="My note", content="Keep this draft")
        cases = ({"title": " "}, {"content": ""}, {"title": "x" * 201},
                 {"content": "x" * 20001}, {"id": "bad"}, {"id": "0"},
                 {"project_id": "-1"}, {"task_id": "bad"}, {"project_id": "999"})
        with patch.object(todo, "fetch_all", return_value=[]), \
                patch.object(todo, "execute_write") as write:
            for invalid in cases:
                with self.subTest(invalid=tuple(invalid)):
                    response = self.client.post("/notes/save", data={**valid, **invalid})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(b'role="alert"', response.data)
                    if "content" not in invalid:
                        self.assertIn(b"Keep this draft", response.data)
            write.assert_not_called()

    def test_note_actions_and_missing_records(self):
        with patch.object(todo, "execute_write", return_value=1) as write:
            for action in ("pin", "delete"):
                response = self.client.post(f"/notes/{action}/1?q=idea")
                self.assertEqual(response.location, "/notes?q=idea")
                self.assertEqual(write.call_args.args[1], (1,))
        with patch.object(todo, "execute_write", return_value=0), \
                patch.object(todo, "fetch_all", return_value=[]):
            self.assertEqual(self.client.get("/notes?edit=999").status_code, 404)
            for action in ("pin", "delete"):
                self.assertEqual(self.client.post(f"/notes/{action}/999").status_code, 404)
            self.assertEqual(self.client.post("/notes/save", data={
                "id": "999", "title": "Missing", "content": "Notes",
            }).status_code, 404)


class ExpenseTests(unittest.TestCase):
    def setUp(self):
        todo.app.config["TESTING"] = True
        self.client = todo.app.test_client()
        self.today_patch = patch.object(todo, "local_today", return_value=TODAY)
        self.today_patch.start()
        self.addCleanup(self.today_patch.stop)
        self.form = dict(title="Groceries", kind="expense", category="food", amount="25.50",
                         occurred_on="2026-11-03", description="Weekly shop")

    def test_empty_month_and_invalid_month_fallback(self):
        with patch.object(todo, "fetch_all", return_value=[]):
            for month in ("", "not-a-month", "9999-12", "2024-02"):
                with self.subTest(month=month):
                    response = self.client.get("/expenses?month=" + month)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b"No transactions this month.", response.data)
                    self.assertIn(b"No budget set", response.data)
                    expected = "2024-02-01" if month == "2024-02" else "2026-11-03"
                    self.assertIn(f'value="{expected}"'.encode(), response.data)

    def test_monthly_totals_budget_and_date_boundaries(self):
        totals = [dict(kind="income", category="salary", total=Decimal("1000")),
                  dict(kind="expense", category="food", total=Decimal("75.25")),
                  dict(kind="expense", category="others", total=Decimal("25"))]
        budget = dict(income=Decimal("1000"), savings=Decimal("100"), food=Decimal("50"),
                      transport=Decimal("20"), bills=Decimal("20"), entertainment=Decimal("0"))
        for day, bounds in ((date(2024, 2, 15), (date(2024, 2, 1), date(2024, 3, 1))),
                            (date(2026, 12, 31), (date(2026, 12, 1), date(2027, 1, 1)))):
            with self.subTest(day=day), patch.object(todo, "fetch_all", side_effect=[totals, [budget]]) as read:
                summary = todo.monthly_finances(day)
            self.assertEqual(read.call_args_list[0].args[1], bounds)
            self.assertEqual(summary["spending"], Decimal("100.25"))
            self.assertEqual(summary["income"], Decimal("1000"))
            self.assertEqual(summary["balance"], Decimal("899.75"))
            self.assertEqual(summary["budget_left"], Decimal("-10.25"))
            self.assertEqual(summary["categories"][-1], dict(name="others", spent=Decimal("25"), planned=0))

    def test_create_income_expense_and_update(self):
        with patch.object(todo, "fetch_all", return_value=[{}]), \
                patch.object(todo, "execute_write", return_value=1) as write:
            response = self.client.post("/expenses/save", data=self.form)
            self.assertEqual(response.location, "/expenses?month=2026-11&saved=1")
            self.assertEqual(write.call_args.args[1],
                             ("Groceries", "expense", "food", Decimal("25.50"), TODAY, "Weekly shop"))
            response = self.client.post("/expenses/save", data={
                **self.form, "id": "2", "kind": "income", "category": "salary", "amount": "3000",
            })
            self.assertEqual(response.status_code, 302)
            self.assertIn("UPDATE transactions", write.call_args.args[0])
            self.assertEqual(write.call_args.args[1][-1], 2)

    def test_invalid_transactions_never_write(self):
        invalid = [dict(amount=amount) for amount in
                   ("", "abc", "0", "-1", "NaN", "sNaN", "Infinity", "1.001", "10000000000")]
        invalid += [dict(title=""), dict(title="x" * 201), dict(description="x" * 2001),
                    dict(kind="unknown"), dict(category="salary"), dict(kind="income"),
                    dict(occurred_on="2026-02-30"), dict(occurred_on="1999-12-31"),
                    dict(occurred_on="2201-01-01"), dict(id="bad"), dict(id="-1")]
        with patch.object(todo, "fetch_all", return_value=[]), \
                patch.object(todo, "execute_write") as write:
            for changes in invalid:
                with self.subTest(changes=str(changes)[:80]):
                    response = self.client.post("/expenses/save?month=2026-11", data={**self.form, **changes})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(b'role="alert"', response.data)
            write.assert_not_called()

    def test_edit_prefills_and_escapes_transaction(self):
        transaction = dict(id=2, title="<script>bad</script>", kind="income", category="salary",
                           amount=Decimal("123.45"), occurred_on=date(2026, 11, 2),
                           description="<img src=x onerror=bad>")

        def rows(query, params=()):
            return [transaction] if "SELECT * FROM transactions" in query else []

        with patch.object(todo, "fetch_all", side_effect=rows):
            response = self.client.get("/expenses?month=2026-11&edit=2")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="2026-11-02"', response.data)
        self.assertIn(b'value="123.45"', response.data)
        self.assertIn(b'value="salary" selected', response.data)
        self.assertIn(b"&lt;script&gt;", response.data)
        self.assertNotIn(b"<img src=x", response.data)

    def test_delete_keeps_selected_month_and_missing_records_are_404(self):
        with patch.object(todo, "execute_write", return_value=1):
            response = self.client.post("/expenses/delete/2?month=2024-02")
        self.assertEqual(response.location, "/expenses?month=2024-02")
        with patch.object(todo, "execute_write", return_value=0), \
                patch.object(todo, "fetch_all", return_value=[]):
            self.assertEqual(self.client.get("/expenses?edit=999").status_code, 404)
            self.assertEqual(self.client.post("/expenses/delete/999").status_code, 404)
            self.assertEqual(self.client.post("/expenses/save", data={**self.form, "id": "999"}).status_code, 404)


class DashboardTests(unittest.TestCase):
    def test_dashboard_shows_real_sections_and_empty_states(self):
        stats = dict(open_tasks=0, overdue_tasks=0, active_projects=0, note_count=0)
        with patch.object(todo, "local_today", return_value=TODAY), \
                patch.object(todo, "fetch_all", side_effect=[[stats], [], [], [], [], [], []]):
            response = todo.app.test_client().get("/dashboard")
        self.assertEqual(response.status_code, 200)
        for text in ("Nothing due today.", "No upcoming subscription bills.", "Write your first note.",
                     "No budget set", "Record a transaction", "Log today", "aria-current=\"page\""):
            self.assertIn(text, response.get_data(as_text=True))

    def test_dashboard_links_existing_records_and_formats_totals(self):
        rows = [
            [dict(open_tasks=3, overdue_tasks=1, active_projects=2, note_count=1)],
            [dict(id=7, title="Plan today", due_at=datetime(2026, 11, 3, 15), priority="High")],
            [dict(id=4, name="Music", price=Decimal("9.90"), next_billing_date=date(2026, 11, 5))],
            [dict(id=5, title="A useful day", entry_date=TODAY, day_type="Work")],
            [dict(id=1, title="Pinned idea", pinned=True, updated_at=UPDATED)],
            [dict(kind="expense", category="food", total=Decimal("23.45"))], [],
        ]
        with patch.object(todo, "local_today", return_value=TODAY), \
                patch.object(todo, "fetch_all", side_effect=rows):
            response = todo.app.test_client().get("/dashboard")
        self.assertEqual(response.status_code, 200)
        for text in ("Plan today", "Music", "A useful day", "Pinned idea", "$23.45", '/?edit=7',
                     '/logbook?edit=5', '/notes?edit=1'):
            self.assertIn(text, response.get_data(as_text=True))


@unittest.skipUnless(os.getenv("WORKSPACE_TEST_DATABASE_URL"), "Requires a disposable PostgreSQL test database")
class WorkspaceDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_url = os.environ["WORKSPACE_TEST_DATABASE_URL"]
        cls.schema = "workspace_test_" + uuid4().hex
        with closing(psycopg2.connect(cls.database_url)) as connection, connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.connection_patch = patch.object(todo, "get_connection", cls.connect)
        cls.connection_patch.start()
        todo.init_db()
        todo.init_db()
        todo.app.config["TESTING"] = True

    @classmethod
    def connect(cls):
        return psycopg2.connect(cls.database_url, options="-c search_path=" + cls.schema)

    @classmethod
    def tearDownClass(cls):
        cls.connection_patch.stop()
        with closing(psycopg2.connect(cls.database_url)) as connection, connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        self.client = todo.app.test_client()
        todo.execute_write("TRUNCATE notes, transactions, projects, tasks, budgets, subscriptions, logbook_entries CASCADE")

    def test_notes_save_pin_search_edit_delete_and_keep_links_optional(self):
        todo.execute_write("INSERT INTO projects (title, description, status) VALUES ('Project', 'Notes', 'Ongoing')")
        project_id = todo.fetch_all("SELECT id FROM projects")[0]["id"]
        response = self.client.post("/notes/save", data={
            "title": "100% useful", "content": "An idea", "project_id": project_id,
        })
        self.assertEqual(response.status_code, 302)
        note_id = todo.fetch_all("SELECT id FROM notes")[0]["id"]
        self.client.post("/notes/save", data={"title": "1000 ideas", "content": "Different"})
        page = self.client.get("/notes?q=100%25").get_data(as_text=True)
        self.assertIn("100% useful", page)
        self.assertNotIn("1000 ideas", page)
        self.client.post(f"/notes/pin/{note_id}")
        self.assertTrue(todo.fetch_all("SELECT pinned FROM notes WHERE id = %s", (note_id,))[0]["pinned"])
        todo.execute_write("DELETE FROM projects WHERE id = %s", (project_id,))
        self.assertIsNone(todo.fetch_all("SELECT project_id FROM notes WHERE id = %s", (note_id,))[0]["project_id"])
        response = self.client.post("/notes/save", data={"id": note_id, "title": "Changed", "content": "Edited"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"Changed", self.client.get("/notes").data)
        self.assertEqual(self.client.post(f"/notes/delete/{note_id}").status_code, 302)
        self.assertFalse(todo.fetch_all("SELECT id FROM notes WHERE id = %s", (note_id,)))

    def test_transactions_move_months_and_compare_budgets_without_changing_plan(self):
        todo.execute_write("""
            INSERT INTO budgets (year, month, income, savings, food)
            VALUES (2024, 2, 1000, 100, 50)
        """)
        form = dict(title="Lunch", kind="expense", category="food", amount="12.34", occurred_on="2024-02-29")
        self.assertEqual(self.client.post("/expenses/save", data=form).status_code, 302)
        transaction_id = todo.fetch_all("SELECT id FROM transactions")[0]["id"]
        self.client.post("/expenses/save", data={
            "title": "Pay", "kind": "income", "category": "salary", "amount": "1000", "occurred_on": "2024-02-01",
        })
        summary = todo.monthly_finances(date(2024, 2, 15))
        self.assertEqual(summary["spending"], Decimal("12.34"))
        self.assertEqual(summary["balance"], Decimal("987.66"))
        self.assertEqual(summary["budget_left"], Decimal("37.66"))
        self.assertEqual(self.client.get("/expenses?month=2024-02").status_code, 200)
        self.client.post("/expenses/save", data={**form, "id": transaction_id, "amount": "20.00", "occurred_on": "2024-03-01"})
        self.assertEqual(todo.monthly_finances(date(2024, 2, 1))["spending"], 0)
        self.assertEqual(todo.monthly_finances(date(2024, 3, 1))["spending"], Decimal("20"))
        self.assertEqual(todo.fetch_all("SELECT food FROM budgets")[0]["food"], Decimal("50"))
        self.client.post(f"/expenses/delete/{transaction_id}?month=2024-03")
        self.assertEqual(todo.monthly_finances(date(2024, 3, 1))["spending"], 0)

    def test_dashboard_renders_with_postgresql_aggregates(self):
        todo.execute_write("""
            INSERT INTO tasks (title, description, due_at, done) VALUES
                ('Overdue task', 'Notes', '2026-11-02 15:00', FALSE),
                ('Today task', 'Notes', '2026-11-03 15:00', FALSE),
                ('Future task', 'Notes', '2026-11-04 15:00', FALSE),
                ('Finished task', 'Notes', '2026-11-02 15:00', TRUE)
        """)
        self.client.post("/notes/save", data={"title": "Remember this", "content": "Notes", "pinned": "1"})
        with patch.object(todo, "local_today", return_value=TODAY):
            response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Overdue task", page)
        self.assertIn("Today task", page)
        self.assertNotIn("Future task", page)
        self.assertNotIn("Finished task", page)
        self.assertIn("Remember this", page)
        self.assertIn("1 overdue before today", page)

    def add_subscription(self, cycle="monthly", due_on="2026-10-31"):
        self.client.post("/subscriptions/add", data={
            "name": "Music", "price": "19.90", "billing_cycle": cycle,
            "next_billing_date": due_on, "subscription_type": "Streaming",
        })
        return todo.fetch_all("SELECT id FROM subscriptions")[0]["id"]

    def test_subscription_payment_history_totals_and_duplicate_protection(self):
        subscription_id = self.add_subscription()
        form = {"due_on": "2026-10-31", "paid_on": "2026-11-03"}
        with patch.object(todo, "local_today", return_value=TODAY):
            response = self.client.post(f"/subscriptions/pay/{subscription_id}", data=form)
            self.assertEqual(response.status_code, 302)
            duplicate = self.client.post(f"/subscriptions/pay/{subscription_id}", data=form)
        self.assertEqual(duplicate.status_code, 409)
        transactions = todo.fetch_all("SELECT * FROM transactions")
        self.assertEqual(len(transactions), 1)
        payment = transactions[0]
        self.assertEqual(payment["subscription_id"], subscription_id)
        self.assertEqual(payment["subscription_due_on"], date(2026, 10, 31))
        self.assertEqual(payment["occurred_on"], TODAY)
        self.assertEqual(payment["category"], "bills")
        self.assertEqual(todo.monthly_finances(TODAY)["spending"], Decimal("19.90"))
        self.assertEqual(todo.monthly_finances(date(2026, 10, 1))["spending"], 0)
        self.assertEqual(todo.fetch_all("SELECT next_billing_date FROM subscriptions")[0]["next_billing_date"],
                         date(2026, 11, 30))
        page = self.client.get(f"/expenses?subscription={subscription_id}&month=2026-11")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Music", page.data)
        self.assertIn(b"Subscription payments", page.data)

    def test_subscription_removal_keeps_payment_and_edits_keep_schedule(self):
        subscription_id = self.add_subscription()
        self.client.post(f"/subscriptions/pay/{subscription_id}", data={
            "due_on": "2026-10-31", "paid_on": "2026-11-03",
        })
        payment_id = todo.fetch_all("SELECT id FROM transactions")[0]["id"]
        response = self.client.post("/expenses/save", data={
            "id": payment_id, "title": "Music paid", "kind": "expense", "category": "bills",
            "amount": "18", "occurred_on": "2026-11-02", "description": "Discount",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(todo.monthly_finances(TODAY)["spending"], Decimal("18"))
        self.assertEqual(todo.fetch_all("SELECT next_billing_date FROM subscriptions")[0]["next_billing_date"],
                         date(2026, 11, 30))
        self.client.post(f"/subscriptions/delete/{subscription_id}")
        payment = todo.fetch_all("SELECT * FROM transactions")[0]
        self.assertIsNone(payment["subscription_id"])
        self.assertEqual(payment["subscription_due_on"], date(2026, 10, 31))
        page = self.client.get("/expenses?month=2026-11")
        self.assertIn(b"plan removed", page.data)
        self.assertIn(b"Music paid", page.data)
        self.assertEqual(self.client.get(f"/expenses?month=2026-11&edit={payment_id}").status_code, 200)

    def test_subscription_schedule_preserves_month_end_and_full_yearly_price(self):
        subscription_id = self.add_subscription(due_on="2024-01-31")
        for due_on, paid_on, expected in (
            ("2024-01-31", "2024-01-31", date(2024, 2, 29)),
            ("2024-02-29", "2024-02-29", date(2024, 3, 31)),
        ):
            response = self.client.post(f"/subscriptions/pay/{subscription_id}", data={
                "due_on": due_on, "paid_on": paid_on,
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(todo.fetch_all("SELECT next_billing_date FROM subscriptions")[0]["next_billing_date"],
                             expected)
        todo.execute_write("DELETE FROM subscriptions")
        subscription_id = self.add_subscription(cycle="yearly", due_on="2024-02-29")
        self.client.post(f"/subscriptions/pay/{subscription_id}", data={
            "due_on": "2024-02-29", "paid_on": "2024-02-29",
        })
        plan = todo.fetch_all("SELECT next_billing_date, billing_day FROM subscriptions")[0]
        self.assertEqual(plan["next_billing_date"], date(2025, 2, 28))
        self.assertEqual(plan["billing_day"], 29)
        payment = todo.fetch_all("SELECT amount FROM transactions WHERE subscription_id = %s", (subscription_id,))[0]
        self.assertEqual(payment["amount"], Decimal("19.90"))

    def test_concurrent_subscription_payments_only_record_one_expense(self):
        subscription_id = self.add_subscription()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda _: todo.record_subscription_payment(subscription_id, date(2026, 10, 31), TODAY),
                range(2),
            ))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(len(todo.fetch_all("SELECT id FROM transactions")), 1)

    def test_schedule_update_failure_rolls_back_expense(self):
        subscription_id = self.add_subscription()
        todo.execute_write("""
            ALTER TABLE subscriptions ADD CONSTRAINT test_schedule_limit
            CHECK (next_billing_date <= DATE '2026-10-31')
        """)
        try:
            with self.assertRaises(psycopg2.errors.CheckViolation):
                todo.record_subscription_payment(subscription_id, date(2026, 10, 31), TODAY)
            self.assertEqual(todo.fetch_all("SELECT id FROM transactions"), [])
            self.assertEqual(todo.fetch_all("SELECT next_billing_date FROM subscriptions")[0]["next_billing_date"],
                             date(2026, 10, 31))
        finally:
            todo.execute_write("ALTER TABLE subscriptions DROP CONSTRAINT test_schedule_limit")

    def test_subscription_schema_upgrade_preserves_existing_expenses(self):
        subscription_id = self.add_subscription()
        self.client.post("/expenses/save", data={
            "title": "Existing expense", "kind": "expense", "category": "food",
            "amount": "12", "occurred_on": "2026-11-03",
        })
        todo.execute_write("ALTER TABLE transactions DROP COLUMN subscription_id, DROP COLUMN subscription_due_on")
        todo.execute_write("ALTER TABLE subscriptions DROP COLUMN billing_day")
        todo.init_db()
        todo.init_db()
        self.assertEqual(todo.fetch_all("SELECT title FROM transactions")[0]["title"], "Existing expense")
        self.assertTrue(todo.record_subscription_payment(subscription_id, date(2026, 10, 31), TODAY))
        self.assertEqual(todo.monthly_finances(TODAY)["spending"], Decimal("31.90"))


if __name__ == "__main__":
    unittest.main()
