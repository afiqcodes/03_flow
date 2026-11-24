"""Editable API catalog and service handlers for the API page.

Replace or register a handler in SERVICE_HANDLERS when a real API is ready.
Each handler receives the validated request fields and returns (JSON data, HTTP status).
Keep credentials on the server, never in the catalog or browser code.
"""

import json
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API_SERVICES = (
    {
        "slug": "api-a",
        "name": "API a",
        "purpose": "User spending lookup",
        "description": "Look up a user's monthly spending and spending band by ID.",
        "version": "v1",
        "auth": "None",
        "latency": "Measured per call",
        "method": "POST",
        "fields": (
            {"name": "user_id", "label": "User ID", "type": "text", "example": "U_1001",
             "help": "Try U_1001 to see a user's spending."},
        ),
        "example_response": {
            "user_id": "U_1001",
            "monthly_spend_myr": 420,
            "spending_band": "Medium",
        },
    },
    {
        "slug": "api-b",
        "name": "API b",
        "purpose": "Weather snapshot",
        "description": "Find sample current conditions for a city.",
        "version": "v1 · sample",
        "auth": "None · sample",
        "latency": "Measured per call",
        "method": "POST",
        "fields": (
            {"name": "city", "label": "City", "type": "text", "example": "Kuala Lumpur",
             "help": "Try Kuala Lumpur to see the sample conditions."},
        ),
        "example_response": {
            "data": {"city": "Kuala Lumpur", "temperature_c": 30,
                     "condition": "Partly cloudy", "humidity_percent": 68},
        },
    },
    {
        "slug": "api-c",
        "name": "API c",
        "purpose": "Budget summary",
        "description": "Retrieve a sample monthly budget summary.",
        "version": "v1 · sample",
        "auth": "None · sample",
        "latency": "Measured per call",
        "method": "POST",
        "fields": (
            {"name": "month", "label": "Month", "type": "month", "example": "2026-10",
             "help": "Try October 2026 to see the sample budget."},
        ),
        "example_response": {
            "data": {"month": "2026-10", "currency": "MYR", "income": 4200,
                     "expenses": {"food": 650, "transport": 300, "bills": 540},
                     "remaining": 2710},
        },
    },
    {
        "slug": "api-d",
        "name": "API d",
        "purpose": "Task status",
        "description": "Check the details and progress of a sample task.",
        "version": "v1 · sample",
        "auth": "None · sample",
        "latency": "Measured per call",
        "method": "POST",
        "fields": (
            {"name": "task_id", "label": "Task ID", "type": "text", "example": "T-204",
             "help": "Try T-204 to see the sample task."},
        ),
        "example_response": {
            "data": {"task_id": "T-204", "title": "Review weekly plan",
                     "priority": "Medium", "completed": False},
        },
    },
    {
        "slug": "api-e",
        "name": "API e",
        "purpose": "Currency quote",
        "description": "Preview a sample conversion quote between two currencies.",
        "version": "v1 · sample",
        "auth": "None · sample",
        "latency": "Measured per call",
        "method": "POST",
        "fields": (
            {"name": "base_currency", "label": "From", "type": "select", "example": "MYR",
             "options": ("MYR", "USD", "EUR"), "help": "Currency to convert from."},
            {"name": "quote_currency", "label": "To", "type": "select", "example": "USD",
             "options": ("MYR", "USD", "EUR"), "help": "Currency to convert to."},
        ),
        "example_response": {
            "data": {"base_currency": "MYR", "quote_currency": "USD",
                     "sample_rate": 0.25, "sample_only": True},
        },
    },
    {
        "slug": "api-f",
        "name": "API f",
        "purpose": "Bookmark details",
        "description": "Fetch a sample saved bookmark and its category.",
        "version": "v1 · sample",
        "auth": "None · sample",
        "latency": "Measured per call",
        "method": "POST",
        "fields": (
            {"name": "bookmark_id", "label": "Bookmark ID", "type": "text", "example": "B-12",
             "help": "Try B-12 to see the sample bookmark."},
        ),
        "example_response": {
            "data": {"bookmark_id": "B-12", "title": "Reference guide",
                     "url": "https://example.com/guide", "category": "Education"},
        },
    },
    {
        "slug": "api-g",
        "name": "API g",
        "purpose": "Subscription plan",
        "description": "View a sample subscription and its next billing date.",
        "version": "v1 · sample",
        "auth": "None · sample",
        "latency": "Measured per call",
        "method": "POST",
        "fields": (
            {"name": "plan_id", "label": "Plan ID", "type": "text", "example": "S-7",
             "help": "Try S-7 to see the sample plan."},
        ),
        "example_response": {
            "data": {"plan_id": "S-7", "name": "Sample streaming plan",
                     "billing_cycle": "monthly", "amount_myr": 19.90,
                     "next_billing_date": "2026-11-15"},
        },
    },
    {
        "slug": "api-h",
        "name": "API h",
        "purpose": "Project overview",
        "description": "Open a sample project's status and linked resources.",
        "version": "v1 · sample",
        "auth": "None · sample",
        "latency": "Measured per call",
        "method": "POST",
        "fields": (
            {"name": "project_id", "label": "Project ID", "type": "text", "example": "P-3",
             "help": "Try P-3 to see the sample project."},
        ),
        "example_response": {
            "data": {"project_id": "P-3", "title": "Personal dashboard",
                     "status": "Ongoing", "links": {"website": "https://example.com"}},
        },
    },
)

API_SERVICE_BY_SLUG = {service["slug"]: service for service in API_SERVICES}


def call_user_api(values):
    """Forward a spending lookup to the local dummy API."""
    api_request = Request(
        "http://dummy-api:4001/v1/spending/lookup",
        data=json.dumps({"user_id": values["user_id"]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        try:
            response = urlopen(api_request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return json.load(response), response.status
    except (OSError, HTTPException):
        return {"error": "Dummy API is unavailable."}, 503
    except ValueError:
        return {"error": "Dummy API returned an invalid JSON response."}, 502


# Register integrations here; each returns (JSON-serializable data, HTTP status).
SERVICE_HANDLERS = {"api-a": call_user_api}


def call_api_service(service, values):
    """Use a registered integration, or serve the catalog's sample record."""
    handler = SERVICE_HANDLERS.get(service["slug"])
    if handler is not None:
        return handler(values)

    if all(
        values[field["name"]].casefold() == field["example"].casefold()
        for field in service["fields"]
    ):
        return service["example_response"], 200

    return {
        "error": "No sample record matches this request.",
        "hint": "Use the example values shown beside the request fields.",
    }, 404
