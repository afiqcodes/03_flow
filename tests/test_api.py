"""API catalog and sample request checks; no database is required."""

import unittest
from http.client import IncompleteRead
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import app as todo
import api_services
from api_services import API_SERVICES, SERVICE_HANDLERS


class ApiPageTests(unittest.TestCase):
    def setUp(self):
        todo.app.config["TESTING"] = True
        self.client = todo.app.test_client()

    def test_information_navigation_and_eight_distinct_dialogs(self):
        page = self.client.get("/api")
        html = page.get_data(as_text=True)

        self.assertEqual(page.status_code, 200)
        self.assertEqual(html.count('class="api-card"'), 8)
        self.assertEqual(html.count('class="api-dialog"'), 8)
        self.assertIn('href="/api" class="active"', html)
        for service in API_SERVICES:
            with self.subTest(service=service["slug"]):
                self.assertIn(f'id="api-dialog-{service["slug"]}"', html)
                self.assertIn(f'action="/api/services/{service["slug"]}/request"', html)
                self.assertIn(service["fields"][0]["name"], html)

    def test_each_service_returns_its_own_sample_and_missing_record(self):
        with patch.dict(SERVICE_HANDLERS, {}, clear=True):
            for service in API_SERVICES:
                url = f"/api/services/{service['slug']}/request"
                example = {field["name"]: field["example"] for field in service["fields"]}
                with self.subTest(service=service["slug"]):
                    success = self.client.post(url, data=example)
                    self.assertEqual(success.status_code, 200)
                    self.assertEqual(success.get_json(), service["example_response"])
                    self.assertEqual(success.headers["Cache-Control"], "no-store")

                    first_field = service["fields"][0]["name"]
                    unknown = self.client.post(url, data={**example, first_field: "other"})
                    if service["fields"][0]["type"] == "select":
                        self.assertEqual(unknown.status_code, 400)
                    else:
                        self.assertEqual(unknown.status_code, 404)

    def test_invalid_request_and_unknown_service(self):
        self.assertEqual(self.client.post("/api/services/api-a/request").status_code, 400)
        self.assertEqual(self.client.post("/api/services/missing/request").status_code, 404)
        self.assertEqual(self.client.post("/api/services/api-e/request", data={
            "base_currency": "XYZ", "quote_currency": "USD",
        }).status_code, 400)

    def test_registered_handler_can_return_another_status(self):
        def unavailable(values):
            self.assertEqual(values["user_id"], "U_1001")
            return {"error": "Service unavailable"}, 503

        with patch.dict(SERVICE_HANDLERS, {"api-a": unavailable}):
            response = self.client.post("/api/services/api-a/request", data={"user_id": "U_1001"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "Service unavailable")

    def test_live_service_connection_failures_return_json(self):
        for failure in (TimeoutError(), ConnectionResetError(), URLError("offline"), IncompleteRead(b"{")):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(api_services, "urlopen", side_effect=failure):
                response = self.client.post("/api/services/api-a/request", data={"user_id": "U_1001"})
            self.assertEqual(response.status_code, 503)
            self.assertIn("error", response.get_json())

    def test_live_service_invalid_json_in_success_or_error_is_a_gateway_error(self):
        success = BytesIO(b"<html>Service error</html>")
        success.status = 200
        failure = HTTPError("http://dummy-api", 502, "Bad Gateway", {}, BytesIO(b"upstream error"))
        for response_or_error in (success, failure):
            kwargs = {"side_effect": response_or_error} if isinstance(response_or_error, HTTPError) else {"return_value": response_or_error}
            with self.subTest(response=type(response_or_error).__name__), \
                    patch.object(api_services, "urlopen", **kwargs):
                response = self.client.post("/api/services/api-a/request", data={"user_id": "U_1001"})
            self.assertEqual(response.status_code, 502)
            self.assertIn("invalid JSON", response.get_json()["error"])
            self.assertTrue(response_or_error.closed)

    def test_live_service_preserves_json_http_error_and_closes_response(self):
        failure = HTTPError("http://dummy-api", 404, "Not Found", {}, BytesIO(b'{"error":"Unknown user"}'))
        with patch.object(api_services, "urlopen", side_effect=failure):
            response = self.client.post("/api/services/api-a/request", data={"user_id": "missing"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "Unknown user"})
        self.assertTrue(failure.closed)


if __name__ == "__main__":
    unittest.main()
