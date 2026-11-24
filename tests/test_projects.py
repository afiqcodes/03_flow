"""Project page checks, with database integration when PROJECT_TEST_DATABASE_URL is set."""
import os
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from PIL import Image
from werkzeug.datastructures import FileStorage

import app as todo


def png_bytes():
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


class ProjectPageTests(unittest.TestCase):
    def setUp(self):
        todo.app.config["TESTING"] = True
        self.client = todo.app.test_client()

    def test_empty_page_and_new_status_choices(self):
        with patch.object(todo, "fetch_all", return_value=[]):
            response = self.client.get("/projects")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("no projects yet", page)
        self.assertIn('value="Ongoing"', page)
        self.assertNotIn('value="Terminated"', page)

    def test_cards_modal_and_edit_status(self):
        project = dict(id=1, title="Sample", description="A project", status="In Review",
                       github_url="https://github.com/example/repo", website_url=None,
                       has_image=False, created_at=datetime.now(timezone.utc),
                       updated_at=datetime.now(timezone.utc))
        def rows(query, params=()):
            if "WHERE id = %s" in query:
                return [project]
            if "FROM projects ORDER BY" in query:
                return [project]
            return []
        with patch.object(todo, "fetch_all", side_effect=rows):
            response = self.client.get("/projects?edit=1")
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="project-card"', page)
        self.assertIn('id="project-dialog-1"', page)
        self.assertIn('value="Terminated"', page)
        self.assertIn("status-in-review", page)
        self.assertIn("GitHub ↗", page)
        self.assertNotIn("website ↗", page)

    def test_rejects_invalid_image_and_unsafe_link_before_write(self):
        with patch.object(todo, "fetch_all", return_value=[]), patch.object(todo, "get_connection") as connection:
            bad_image = self.client.post("/projects/save", data={
                "title": "Test", "description": "Details", "status": "Ongoing",
                "main_image": (BytesIO(b"not an image"), "fake.png"),
            })
            bad_link = self.client.post("/projects/save", data={
                "title": "Test", "description": "Details", "status": "Ongoing",
                "github_url": "javascript:alert(1)",
            })
            bad_id = self.client.post("/projects/save", data={
                "id": "not-a-number", "title": "Test", "description": "Details",
                "status": "Ongoing",
            })
            bad_file_id = self.client.post("/projects/save", data={
                "title": "Test", "description": "Details", "status": "Ongoing",
                "remove_files": "not-a-number",
            })
        self.assertEqual(bad_image.status_code, 400)
        self.assertEqual(bad_link.status_code, 400)
        self.assertEqual(bad_id.status_code, 400)
        self.assertEqual(bad_file_id.status_code, 400)
        connection.assert_not_called()

    def test_valid_image_and_stored_file_response(self):
        original = png_bytes()
        upload = FileStorage(stream=BytesIO(original), filename="cover.png")
        with todo.app.test_request_context():
            filename, mime_type, data = todo.read_validated_image(upload, "The main image")
            response = todo.send_stored_file(data, filename, mime_type, as_attachment=True)
            response.direct_passthrough = False
        self.assertEqual((filename, mime_type, data), ("cover.png", "image/png", original))
        self.assertEqual(response.get_data(), original)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")


@unittest.skipUnless(os.getenv("PROJECT_TEST_DATABASE_URL"), "Requires a disposable PostgreSQL test database")
class ProjectDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_url = os.environ["PROJECT_TEST_DATABASE_URL"]
        cls.schema = "project_test_" + uuid4().hex
        with psycopg2.connect(cls.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute('CREATE SCHEMA "' + cls.schema + '"')
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
        with psycopg2.connect(cls.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute('DROP SCHEMA "' + cls.schema + '" CASCADE')

    def setUp(self):
        self.client = todo.app.test_client()
        todo.execute_write("TRUNCATE projects CASCADE")

    def save(self, **overrides):
        values = dict(title="Portfolio", description="My work", status="Ongoing")
        values.update(overrides)
        return self.client.post("/projects/save", data=values)

    def test_create_show_download_edit_and_remove(self):
        picture = png_bytes()
        document = b"PK test archive"
        response = self.save(
            github_url="github.com/example/repo", website_url="https://example.com",
            main_image=(BytesIO(picture), "cover.png"),
            documents=(BytesIO(document), "source.zip"),
        )
        self.assertEqual(response.status_code, 302)
        page = self.client.get("/projects").get_data(as_text=True)
        self.assertIn("Portfolio", page)
        self.assertIn("https://github.com/example/repo", page)
        self.assertIn("source.zip", page)
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM projects")
                project_id = cursor.fetchone()[0]
                cursor.execute("SELECT id FROM project_files WHERE project_id = %s", (project_id,))
                file_id = cursor.fetchone()[0]
        image = self.client.get(f"/projects/images/{project_id}")
        self.assertEqual(image.data, picture)
        self.assertEqual(image.mimetype, "image/png")
        download = self.client.get(f"/projects/files/{file_id}")
        self.assertEqual(download.data, document)
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(download.headers["X-Content-Type-Options"], "nosniff")
        edit = self.save(id=project_id, title="Portfolio v2", status="Terminated", remove_files=str(file_id))
        self.assertEqual(edit.status_code, 302)
        page = self.client.get("/projects").get_data(as_text=True)
        self.assertIn("Portfolio v2", page)
        self.assertIn("status-terminated", page)
        self.assertEqual(self.client.get(f"/projects/files/{file_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/projects/images/{project_id}").data, picture)

    def test_limits_and_invalid_values_do_not_create_projects(self):
        self.assertEqual(self.save(status="Terminated").status_code, 400)
        self.assertEqual(self.save(documents=(BytesIO(b"x" * (todo.MAX_PROJECT_FILE_BYTES + 1)), "big.bin")).status_code, 400)
        self.assertEqual(self.save(main_image=(BytesIO(b"invalid"), "fake.png")).status_code, 400)
        self.assertEqual(self.save(github_url="javascript:alert(1)").status_code, 400)
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM projects")
                self.assertEqual(cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
