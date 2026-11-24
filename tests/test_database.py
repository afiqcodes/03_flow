"""Connection lifecycle checks without a PostgreSQL server."""

import unittest
from datetime import date
from unittest.mock import MagicMock, call, patch

import app as todo


class DatabaseConnectionTests(unittest.TestCase):
    def operations(self):
        logbook = dict(title="Day", location="Home", description="Notes", day_type="Work")
        project = dict(title="Project", description="Notes", status="Ongoing",
                       github_url="", website_url="")
        return (
            ("read", lambda: todo.fetch_all("SELECT 1")),
            ("write", lambda: todo.execute_write("DELETE FROM tasks WHERE id = %s", (1,))),
            ("schema", todo.init_db),
            ("logbook", lambda: todo.save_logbook_entry(
                None, date(2026, 11, 3), logbook, [], [],
            )),
            ("project", lambda: todo.save_project_record(
                None, project, [], None, [], False,
            )),
        )

    def connection(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (1,)
        return connection, cursor

    def test_successful_operations_finish_transaction_before_closing(self):
        for name, operation in self.operations():
            with self.subTest(operation=name):
                connection, _ = self.connection()
                with patch.object(todo, "get_connection", return_value=connection):
                    operation()
                self.assertEqual(connection.mock_calls[-2:], [
                    call.__exit__(None, None, None), call.close(),
                ])
                connection.close.assert_called_once_with()

    def test_failed_operations_roll_back_before_closing(self):
        for name, operation in self.operations():
            with self.subTest(operation=name):
                connection, cursor = self.connection()
                error = RuntimeError("Database operation failed")
                cursor.execute.side_effect = error
                with patch.object(todo, "get_connection", return_value=connection):
                    with self.assertRaises(RuntimeError) as raised:
                        operation()
                self.assertIs(raised.exception, error)
                self.assertEqual(connection.__exit__.call_args.args[:2], (RuntimeError, error))
                self.assertEqual(connection.mock_calls[-1], call.close())
                connection.close.assert_called_once_with()

    def test_transaction_start_failure_still_closes_connection(self):
        connection, _ = self.connection()
        connection.__enter__.side_effect = RuntimeError("Could not start transaction")
        with patch.object(todo, "get_connection", return_value=connection):
            with self.assertRaises(RuntimeError):
                todo.fetch_all("SELECT 1")
        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
