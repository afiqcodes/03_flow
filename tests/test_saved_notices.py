"""Save confirmations appear on supported sections after a successful redirect."""
import unittest
from unittest.mock import patch

import app as todo


class SavedNoticeTests(unittest.TestCase):
    def setUp(self):
        todo.app.config["TESTING"] = True
        self.client = todo.app.test_client()

    def test_each_section_renders_a_timed_confirmation_only_when_saved(self):
        for path in ("/logbook", "/budgets", "/subscriptions", "/bookmarks", "/projects"):
            with self.subTest(path=path), patch.object(todo, "fetch_all", return_value=[]):
                saved = self.client.get(path + "?saved=1")
                ordinary = self.client.get(path)
            self.assertEqual(saved.status_code, 200)
            self.assertIn(b'data-auto-dismiss="3000"', saved.data)
            self.assertIn(b'class="save-notice" role="status"', saved.data)
            self.assertNotIn(b'data-auto-dismiss="3000"', ordinary.data)

    def test_successful_saves_redirect_with_confirmation(self):
        cases = (
            ("/budgets/set", {"year": "2026", "month": "10", "income": "100",
                               "savings": "10", "food": "0", "transport": "0", "bills": "0",
                               "entertainment": "0"}, "/budgets?saved=1"),
            ("/subscriptions/add", {"name": "Service", "price": "10", "billing_cycle": "monthly",
                                    "next_billing_date": "2026-10-10", "subscription_type": "Software"},
             "/subscriptions?saved=1"),
            ("/bookmarks/add", {"title": "Reference", "url": "https://example.com",
                                 "bookmark_type": "Software"}, "/bookmarks?saved=1"),
        )
        with patch.object(todo, "execute_write") as write:
            for path, data, location in cases:
                with self.subTest(path=path):
                    response = self.client.post(path, data=data)
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.headers["Location"], location)
            self.assertEqual(write.call_count, len(cases))


if __name__ == "__main__":
    unittest.main()
