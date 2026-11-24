"""Integration checks. Set LOGBOOK_TEST_DATABASE_URL to a disposable PostgreSQL DB."""
import os
import unittest
from io import BytesIO
from uuid import uuid4
from unittest.mock import patch

import psycopg2
from PIL import Image

import app as todo


def image_bytes(color="red"):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


class LogbookFormTests(unittest.TestCase):
    def test_invalid_ids_are_rejected_before_database_write(self):
        client = todo.app.test_client()
        values = dict(title="Day", location="Home", entry_date="2024-02-29",
                      description="Notes", day_type="Work")
        with patch.object(todo, "render_logbook", return_value=("Invalid form", 400)), \
                patch.object(todo, "save_logbook_entry") as save:
            for invalid in ({"id": "not-a-number"}, {"remove_images": "not-a-number"}):
                response = client.post("/logbook/save", data={**values, **invalid})
                self.assertEqual(response.status_code, 400)
        save.assert_not_called()


@unittest.skipUnless(os.getenv("LOGBOOK_TEST_DATABASE_URL"), "Requires a disposable PostgreSQL test database")
class LogbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_url = os.environ["LOGBOOK_TEST_DATABASE_URL"]
        cls.schema = "logbook_test_" + uuid4().hex
        with psycopg2.connect(cls.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute('CREATE SCHEMA "' + cls.schema + '"')
        cls.connection_patch = patch.object(todo, "get_connection", cls.connect)
        cls.connection_patch.start()
        todo.init_db()
        # Applying the schema twice must preserve all tables and data.
        todo.init_db()
        todo.app.config["TESTING"] = True

    @classmethod
    def connect(cls):
        return psycopg2.connect(cls.database_url, options="-c search_path=" + cls.schema)

    @classmethod
    def tearDownClass(cls):
        cls.connection_patch.stop()
        with psycopg2.connect(cls.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute('DROP SCHEMA "' + cls.schema + '" CASCADE')

    def setUp(self):
        self.client = todo.app.test_client()
        todo.execute_write("TRUNCATE logbook_entries CASCADE")

    def save(self, **overrides):
        values = dict(title="A productive day", location="Home", entry_date="2024-02-29",
                      description="Built a feature.\nTook a walk.", day_type="Work")
        values.update(overrides)
        return self.client.post("/logbook/save", data=values)

    def entry(self, day="2024-02-29"):
        return self.client.get("/logbook/day/" + day).get_json()["entry"]

    def test_calendar_has_all_months_weekends_and_leap_day(self):
        page = self.client.get("/logbook?year=2024").get_data(as_text=True)
        self.assertEqual(page.count('class="calendar-section logbook-month"'), 12)
        self.assertEqual(page.count('data-logbook-day='), 366)
        self.assertIn('data-logbook-day="2024-02-29"', page)
        self.assertIn('is-weekend', page)
        normal = self.client.get("/logbook?year=2025").get_data(as_text=True)
        self.assertEqual(normal.count('data-logbook-day='), 365)

    def test_create_download_original_and_edit_preserves_images(self):
        original = image_bytes()
        response = self.save(images=(BytesIO(original), "memory.png"))
        self.assertEqual(response.status_code, 302)
        entry = self.entry()
        picture = entry["images"][0]
        download = self.client.get(picture["download_url"])
        self.assertEqual(download.data, original)
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(download.mimetype, "image/png")
        self.assertEqual(download.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.client.get(picture["url"]).data, original)
        edit_page = self.client.get(entry["edit_url"])
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b"memory.png", edit_page.data)
        self.assertEqual(self.save(id=entry["id"], title="Updated", day_type="MeTIME").status_code, 302)
        changed = self.entry()
        self.assertEqual(changed["title"], "Updated")
        self.assertEqual(changed["day_type"], "MeTIME")
        self.assertEqual(changed["images"], entry["images"])

    def test_duplicate_date_does_not_overwrite_or_add_images(self):
        self.save()
        duplicate = self.save(title="Replacement", images=(BytesIO(image_bytes()), "new.png"))
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn(b"already has a log", duplicate.data)
        self.assertIn(b'value="Replacement"', duplicate.data)
        self.assertEqual(self.entry()["title"], "A productive day")
        self.assertEqual(self.entry()["images"], [])

    def test_rejected_image_does_not_save_partial_entry(self):
        for data in (b"<svg onload=alert(1)></svg>", image_bytes()[:30]):
            response = self.save(images=[(BytesIO(image_bytes()), "valid.png"), (BytesIO(data), "fake.png")])
            self.assertEqual(response.status_code, 400)
            self.assertIsNone(self.entry())

    def test_future_weekend_past_year_and_all_day_types(self):
        for day, kind in zip(("2020-01-04", "2023-12-31", "2035-06-09", "2035-06-10"), todo.LOGBOOK_DAY_TYPES):
            self.assertEqual(self.save(entry_date=day, day_type=kind).status_code, 302)
            self.assertEqual(self.entry(day)["day_type"], kind)
        page = self.client.get("/logbook?year=2020").get_data(as_text=True)
        for year in (2020, 2023, 2035):
            self.assertIn(f'value="{year}"', page)
        self.assertIn("A productive day", page)

    def test_restores_single_type_after_multi_type_schema(self):
        self.save(day_type="Holiday")
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE logbook_entries ADD COLUMN day_types TEXT[] NOT NULL DEFAULT ARRAY['Work']::TEXT[]")
                cursor.execute("ALTER TABLE logbook_entries ADD COLUMN rating SMALLINT")
                cursor.execute("UPDATE logbook_entries SET day_types = ARRAY['Holiday', 'Family'], rating = 8")
                cursor.execute("ALTER TABLE logbook_entries DROP COLUMN day_type")
        todo.init_db()
        self.assertEqual(self.entry()["day_type"], "Holiday")
        self.assertEqual(self.save(entry_date="2025-01-01").status_code, 302)
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT day_types, rating FROM logbook_entries WHERE entry_date = '2024-02-29'")
                self.assertEqual(cursor.fetchone(), (["Holiday", "Family"], 8))

    def test_move_entry_and_remove_append_images(self):
        self.save(images=(BytesIO(image_bytes()), "old.png"))
        entry = self.entry()
        old_picture = entry["images"][0]
        picture_id = old_picture["url"].rsplit("/", 1)[1]
        response = self.save(id=entry["id"], entry_date="2025-01-01", remove_images=picture_id,
                             images=(BytesIO(image_bytes("blue")), "new.png"))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.entry())
        self.assertEqual(self.entry("2025-01-01")["images"][0]["filename"], "new.png")
        self.assertEqual(self.client.get(old_picture["url"]).status_code, 404)

    def test_duplicate_edit_rolls_back_image_removal(self):
        self.save(images=(BytesIO(image_bytes()), "keep.png"))
        entry = self.entry()
        picture = entry["images"][0]
        self.save(entry_date="2025-01-01")
        response = self.save(id=entry["id"], entry_date="2025-01-01",
                             remove_images=picture["url"].rsplit("/", 1)[1])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.entry()["images"], entry["images"])
        self.assertEqual(self.client.get(picture["url"]).status_code, 200)

    def test_images_from_another_entry_cannot_be_removed(self):
        self.save(images=(BytesIO(image_bytes()), "keep.png"))
        original = self.entry()
        self.save(entry_date="2025-01-01")
        second = self.entry("2025-01-01")
        self.save(id=second["id"], entry_date="2025-01-01",
                  remove_images=original["images"][0]["url"].rsplit("/", 1)[1])
        self.assertEqual(self.entry()["images"], original["images"])

    def test_invalid_fields_missing_entries_and_oversized_upload(self):
        for overrides in ({"entry_date": "2025-02-29"}, {"day_type": "Other"},
                          {"title": " "}, {"location": ""}, {"description": ""}, {"title": "x" * 201},
                          {"id": "not-a-number"}, {"remove_images": "not-a-number"}):
            self.assertEqual(self.save(**overrides).status_code, 400)
        self.assertEqual(self.client.get("/logbook/day/not-a-date").status_code, 404)
        self.assertEqual(self.client.get("/logbook?edit=99999").status_code, 404)
        self.assertEqual(self.save(id=99999).status_code, 404)
        self.assertEqual(self.save(images=(BytesIO(b"x" * (todo.MAX_IMAGE_BYTES + 1)), "big.png")).status_code, 400)
        with patch.dict(todo.app.config, MAX_CONTENT_LENGTH=100):
            self.assertEqual(self.save(description="x" * 1000).status_code, 413)
        self.assertIsNone(self.entry())

    def test_image_count_limit_and_rollback(self):
        self.save(images=[(BytesIO(image_bytes()), f"{index}.png") for index in range(10)])
        entry = self.entry()
        response = self.save(id=entry["id"], title="Do not save", images=(BytesIO(image_bytes()), "extra.png"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.entry()["title"], "A productive day")
        self.assertEqual(len(self.entry()["images"]), 10)
        response = self.save(entry_date="2025-01-01", images=[(BytesIO(image_bytes()), f"{i}.png") for i in range(11)])
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.entry("2025-01-01"))

    def test_escaped_user_content_and_existing_pages(self):
        self.save(title='<script>alert("x")</script>')
        page = self.client.get("/logbook?year=2024").get_data(as_text=True)
        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertIn("&lt;script&gt;", page)
        for path in ("/", "/budgets", "/subscriptions", "/bookmarks"):
            self.assertEqual(self.client.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main()
