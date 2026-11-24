"""Task type route checks; these do not require a database connection."""

import re
import unittest
from datetime import datetime
from unittest.mock import patch

import app as todo


class TaskTypeTests(unittest.TestCase):
    def setUp(self):
        self.client = todo.app.test_client()

    def test_tasks_render_under_their_types_with_icons(self):
        created_at = datetime(2026, 9, 29, 12, 0)
        tasks = [
            dict(id=3, title="Buy groceries", description="Milk", due_at=None,
                 priority="Low", difficulty="Easy", task_type="Errands",
                 created_at=created_at, done=False),
            dict(id=2, title="Pay bills", description="Electricity", due_at=None,
                 priority="Medium", difficulty="Easy", task_type="Finance",
                 created_at=created_at, done=False),
            dict(id=4, title="Clean kitchen", description="Sweep floors", due_at=None,
                 priority="Medium", difficulty="Easy", task_type="Home",
                 created_at=created_at, done=False),
            dict(id=1, title="Old task", description="Before types", due_at=None,
                 priority="Medium", difficulty="Medium", task_type="Others",
                 created_at=created_at, done=False),
        ]

        with patch.object(todo, "fetch_all", return_value=tasks):
            page = self.client.get("/").get_data(as_text=True)

        self.assertEqual(page.count('class="task-category"'), 4)
        self.assertIn('class="task-category-icon task-category-errands"', page)
        self.assertIn('class="task-category-icon task-category-finance"', page)
        self.assertIn('class="task-category-icon task-category-home"', page)
        self.assertIn('class="task-category-icon task-category-others"', page)
        sections = page.split('<section class="task-category"')[1:]
        self.assertIn('id="task-category-finance"', sections[0])
        self.assertIn("Pay bills", sections[0])
        self.assertNotIn("Buy groceries", sections[0])
        self.assertIn('id="task-category-home"', sections[1])
        self.assertIn("Clean kitchen", sections[1])
        self.assertIn('id="task-category-errands"', sections[2])
        self.assertIn("Buy groceries", sections[2])
        self.assertIn('id="task-category-others"', sections[3])
        self.assertIn("Old task", sections[3])
        self.assertIn('<select id="task-type" name="task_type" required>', page)
        self.assertEqual(todo.TASK_TYPES, (
            "Work", "Finance", "Home", "Personal", "Health", "Errands", "Others"
        ))
        for task_type in todo.TASK_TYPES:
            self.assertIn(f'<option value="{task_type}"', page)
        self.assertNotIn('<option value="Study"', page)

    def test_empty_task_list_keeps_empty_message(self):
        with patch.object(todo, "fetch_all", return_value=[]):
            page = self.client.get("/").get_data(as_text=True)
        self.assertIn("no tasks yet.", page)

    def test_tasks_sort_by_priority_then_difficulty_within_each_type(self):
        created_at = datetime(2026, 9, 29, 12)

        def task(task_id, priority, difficulty, task_type):
            return dict(id=task_id, title=f"Task {task_id}", description="Details",
                        due_at=None, priority=priority, difficulty=difficulty,
                        task_type=task_type, created_at=created_at, done=False)

        tasks = [
            task(4, "Low", "Hard", "Work"),
            task(6, "High", "Easy", "Home"),
            task(3, "High", "Hard", "Work"),
            task(9, "Urgent", "Easy", "Work"),
            task(5, "Medium", "Medium", "Work"),
            task(8, "High", "Hard", "Home"),
            task(7, "High", "Easy", "Work"),
            task(10, "Urgent", "Hard", "Work"),
            task(12, "High", "Hard", "Work"),
        ]
        with patch.object(todo, "fetch_all", return_value=tasks):
            page = self.client.get("/").get_data(as_text=True)

        sections = page.split('<section class="task-category"')[1:]
        work, home = sections[:2]
        self.assertEqual(re.findall(r'class="task-priority task-priority-([^"]+)"', work),
                         ["urgent", "high", "medium", "low"])
        self.assertEqual(re.findall(r'class="task-priority task-priority-([^"]+)"', home),
                         ["high"])
        self.assertEqual(re.findall(r'data-task-id="(\d+)"', work),
                         ["10", "9", "12", "3", "7", "5", "4"])
        self.assertEqual(re.findall(r'data-task-id="(\d+)"', home), ["8", "6"])
        for level, expected_ids in {
            "urgent": ["10", "9"], "high": ["12", "3", "7"],
            "medium": ["5"], "low": ["4"],
        }.items():
            priority_section = work.split(f'class="task-priority task-priority-{level}"', 1)[1]
            priority_section = priority_section.split("</section>", 1)[0]
            self.assertEqual(re.findall(r'data-task-id="(\d+)"', priority_section), expected_ids)
        self.assertNotIn('<small class="priority-', page)
        self.assertEqual(page.count('<small class="difficulty-'), len(tasks))

        priority_select = page.split('id="task-priority"', 1)[1].split("</select>", 1)[0]
        difficulty_select = page.split('id="task-difficulty"', 1)[1].split("</select>", 1)[0]
        self.assertEqual(re.findall(r'<option value="([^"]+)"', priority_select),
                         ["Urgent", "High", "Medium", "Low"])
        self.assertEqual(re.findall(r'<option value="([^"]+)"', difficulty_select),
                         ["Hard", "Medium", "Easy"])

    def test_tasks_do_not_show_feedback_notices(self):
        with patch.object(todo, "fetch_all", return_value=[]):
            page = self.client.get("/?saved=1").get_data(as_text=True)
        self.assertNotIn('class="save-notice"', page)
        self.assertNotIn('id="task-feedback"', page)

    def test_add_task_saves_valid_type_and_rejects_unknown_type(self):
        form = dict(title="Plan week", description="Set goals", due_at="2026-10-01T10:00",
                    priority="Medium", difficulty="Easy", task_type="Finance")
        with patch.object(todo, "execute_write") as write:
            response = self.client.post("/add", data=form)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, "/")
            self.assertEqual(write.call_args.args[1][-1], "Finance")
            self.assertEqual(self.client.post("/add", data={**form, "task_type": "Home"}).status_code, 302)
            self.assertEqual(write.call_args.args[1][-1], "Home")
            write.reset_mock()
            self.client.post("/add", data={**form, "task_type": "Unknown"})
            self.client.post("/add", data={**form, "task_type": "Study"})
            write.assert_not_called()

    def test_edit_task_prefills_form_and_updates_fields(self):
        task = dict(id=7, title="Plan week", description="Set goals", due_at=datetime(2026, 10, 1, 10),
                    priority="Medium", difficulty="Easy", task_type="Finance",
                    created_at=datetime(2026, 9, 29, 12), done=False)
        with patch.object(todo, "fetch_all", return_value=[task]):
            page = self.client.get("/?edit=7").get_data(as_text=True)
        self.assertIn('action="/tasks/edit/7"', page)
        self.assertIn('value="Plan week"', page)
        self.assertIn('value="2026-10-01T10:00"', page)
        self.assertIn("save changes", page)

        changes = dict(title="Plan weekend", description="Rest", due_at="2026-10-03T11:00",
                       priority="High", difficulty="Medium", task_type="Personal")
        with patch.object(todo, "execute_write", return_value=1) as write:
            response = self.client.post("/tasks/edit/7", data=changes)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")
        self.assertEqual(write.call_args.args[1],
                         ("Plan weekend", "Rest", datetime(2026, 10, 3, 11),
                          "High", "Medium", "Personal", 7))

    def test_edit_task_rejects_invalid_fields_and_missing_record(self):
        changes = dict(title="Plan weekend", description="Rest", due_at="2026-10-03T11:00",
                       priority="High", difficulty="Medium", task_type="Personal")
        with patch.object(todo, "execute_write") as write:
            response = self.client.post("/tasks/edit/7", data={**changes, "task_type": "Unknown"},
                                        headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(response.status_code, 400)
        write.assert_not_called()

        with patch.object(todo, "execute_write", return_value=0):
            response = self.client.post("/tasks/edit/7", data=changes)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
