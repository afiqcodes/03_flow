import json
import logging
import os
import time
from calendar import Calendar, monthrange
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import psycopg2
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename

from api_services import (
    API_SERVICE_BY_SLUG,
    API_SERVICES,
    SERVICE_HANDLERS,
    call_api_service,
)
from file_conversions import (
    CONVERSION_TOOLS,
    PDF_DPI_VALUES,
    ConversionUnavailable,
    images_to_pdf,
    office_to_pdf,
    pdf_to_images,
)
from uploads import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    read_limited_upload,
    read_validated_image,
    send_stored_file,
)

app = Flask(__name__)
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
app.config["MAX_CONTENT_LENGTH"] = 55 * 1024 * 1024
LOGBOOK_DAY_TYPES = ("Work", "Holiday", "MeTIME", "Family")
MAX_LOGBOOK_IMAGES = 10
MAX_PROJECT_FILES = 10
MAX_PROJECT_FILE_BYTES = 20 * 1024 * 1024
DB_INIT_ATTEMPTS = 10
PROJECT_STATUSES = ("Terminated", "Ongoing", "In Review", "Completed")
NEW_PROJECT_STATUSES = ("Ongoing", "In Review", "Completed")
LOCAL_TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")
MAX_MONEY = Decimal("9999999999.99")
MAX_SUBSCRIPTION_PRICE = Decimal("99999999.99")

ITEM_TYPES = (
    "Gaming",
    "Telecommunications",
    "Streaming",
    "Software",
    "Finance",
    "Productivity",
    "Education",
    "Fitness",
    "Work",
    "Others",
)
ITEM_TYPE_VALUES = frozenset(ITEM_TYPES)

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

EXPENSE_FIELDS = ("food", "transport", "bills", "entertainment")
BUDGET_FIELDS = ("income", "savings", *EXPENSE_FIELDS)
TRANSACTION_CATEGORIES = {
    "expense": (*EXPENSE_FIELDS, "others"),
    "income": ("salary", "freelance", "refunds", "others"),
}
PRIORITY_LEVELS = ("Urgent", "High", "Medium", "Low")
DIFFICULTY_LEVELS = ("Hard", "Medium", "Easy")
TASK_TYPES = ("Work", "Finance", "Home", "Personal", "Health", "Errands", "Others")
HOLIDAY_API_URL = "https://malaysia-holiday.dydxsoft.my/api/v1/holidays"
HOLIDAY_STATES = (
    ("JHR", "Johor"), ("KDH", "Kedah"), ("KTN", "Kelantan"),
    ("MLK", "Melaka"), ("NSN", "Negeri Sembilan"), ("PHG", "Pahang"),
    ("PRK", "Perak"), ("PLS", "Perlis"), ("PNG", "Pulau Pinang"),
    ("SBH", "Sabah"), ("SWK", "Sarawak"), ("SGR", "Selangor"),
    ("TRG", "Terengganu"), ("KUL", "Kuala Lumpur"),
    ("LBN", "Labuan"), ("PJY", "Putrajaya"),
)
HOLIDAY_STATE_NAMES = dict(HOLIDAY_STATES)


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        database=os.getenv("DB_NAME", "todo"),
        user=os.getenv("DB_USER", "todo_user"),
        password=os.getenv("DB_PASSWORD", "todo_password"),
    )


@contextmanager
def database_connection():
    """Commit or roll back a transaction, then always close the connection."""
    with closing(get_connection()) as conn, conn:
        yield conn


def fetch_all(query, params=()):
    """Run a read query and return rows as dictionaries."""
    with database_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def fetch_one_or_404(query, params=()):
    """Return a single record or raise a 404 when it does not exist."""
    rows = fetch_all(query, params)
    if not rows:
        abort(404)
    return rows[0]


def execute_write(query, params=()):
    """Run a write query and return the number of affected rows."""
    with database_connection() as conn, conn.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.rowcount


def execute_write_or_404(query, params=()):
    """Apply a record action, rejecting records that no longer exist."""
    if execute_write(query, params) == 0:
        abort(404)


def read_money(raw_value, *, maximum=MAX_MONEY, minimum=Decimal("0")):
    """Validate money before PostgreSQL can round it or reject an overflow."""
    message = f"Enter an amount from {minimum:,.2f} to {maximum:,.2f} with at most two decimal places."
    try:
        amount = Decimal(raw_value)
        if not amount.is_finite() or not minimum <= amount <= maximum:
            raise ValueError(message)
        rounded = amount.quantize(Decimal("0.01"))
        if amount != rounded:
            raise ValueError(message)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(message) from exc
    return rounded


def optional_form_id():
    """Return the record ID submitted by an edit form, if present."""
    raw_id = request.form.get("id")
    if not raw_id:
        return None
    record_id = int(raw_id)
    if record_id < 1:
        raise ValueError("Choose a valid record to edit.")
    return record_id


def form_values(fields):
    """Read and trim the text fields used by an edit form."""
    return {field: request.form.get(field, "").strip() for field in fields}


def form_ids(field_name):
    """Read IDs of saved attachments selected for removal."""
    ids = [int(value) for value in request.form.getlist(field_name)]
    if any(record_id < 1 for record_id in ids):
        raise ValueError("Choose valid attachments to remove.")
    return ids


def uploaded_files(field_name):
    """Ignore empty browser file inputs when reading a multiple-file field."""
    return [upload for upload in request.files.getlist(field_name) if upload.filename]


def normalize_url(raw_url):
    """Return a safe HTTP(S) URL, adding https:// when needed."""
    if any(ord(character) < 32 or ord(character) == 127 for character in raw_url):
        return None
    normalized = raw_url.strip()
    if normalized.lower().startswith(("javascript:", "data:", "vbscript:", "file:")):
        return None
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"
    elif normalized and "://" not in normalized:
        normalized = f"https://{normalized}"

    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        # Accessing port also validates malformed or out-of-range ports.
        parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or "\\" in normalized
        or any(character.isspace() for character in normalized)
    ):
        return None

    return normalized


def build_year_sections(budget_rows, current_year):
    """Group budget rows into complete 12-month year sections."""
    budgets_by_year = {}
    for budget in budget_rows:
        monthly_budget = dict(budget)
        monthly_budget["expense_total"] = sum(
            (monthly_budget[field] for field in EXPENSE_FIELDS),
            Decimal("0"),
        )
        monthly_budget["remaining"] = (
            monthly_budget["income"]
            - monthly_budget["savings"]
            - monthly_budget["expense_total"]
        )
        budgets_by_year.setdefault(monthly_budget["year"], {})[
            monthly_budget["month"]
        ] = monthly_budget

    budgets_by_year.setdefault(current_year, {})

    sections = []
    for year in sorted(budgets_by_year, reverse=True):
        entries = budgets_by_year[year]
        sections.append(
            {
                "year": year,
                "months": [
                    {
                        "number": month_number,
                        "name": month_name,
                        "budget": entries.get(month_number),
                    }
                    for month_number, month_name in enumerate(MONTH_NAMES, start=1)
                ],
                "total": sum(
                    (budget["income"] for budget in entries.values()),
                    Decimal("0"),
                ),
                "total_expenses": sum(
                    (budget["expense_total"] for budget in entries.values()),
                    Decimal("0"),
                ),
                "total_remaining": sum(
                    (budget["remaining"] for budget in entries.values()),
                    Decimal("0"),
                ),
                "planned_count": len(entries),
            }
        )

    return sections


@app.context_processor
def inject_template_constants():
    return {
        "item_types": ITEM_TYPES,
        "month_names": MONTH_NAMES,
        "expense_fields": EXPENSE_FIELDS,
        "priority_levels": PRIORITY_LEVELS,
        "difficulty_levels": DIFFICULTY_LEVELS,
        "task_types": TASK_TYPES,
    }


def init_db():
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    for attempt in range(DB_INIT_ATTEMPTS):
        try:
            with database_connection() as conn, conn.cursor() as cursor:
                cursor.execute(schema)

            app.logger.info("Database ready.")
            return
        except psycopg2.OperationalError:
            app.logger.warning(
                "Database unavailable (attempt %s/%s).", attempt + 1, DB_INIT_ATTEMPTS
            )
            if attempt + 1 < DB_INIT_ATTEMPTS:
                time.sleep(2)

    raise RuntimeError("Could not connect to database")


def get_public_holidays(year, state_code):
    """Get state holidays, refreshing the PostgreSQL cache at most daily."""
    cached = fetch_all("""
        SELECT holidays, fetched_at FROM public_holiday_cache
        WHERE year = %s AND state_code = %s
    """, (year, state_code))
    cached_row = cached[0] if cached else None
    if cached_row and datetime.now(timezone.utc) - cached_row["fetched_at"] < timedelta(days=1):
        return cached_row["holidays"], None

    if not 2000 <= year <= 2100:
        return (cached_row["holidays"] if cached_row else []), "Holiday data is available for 2000–2100 only."

    url = f"{HOLIDAY_API_URL}?{urlencode({'year': year, 'state': state_code})}"
    try:
        with urlopen(url, timeout=5) as response:
            records = json.load(response)["data"]
        if not isinstance(records, list):
            raise ValueError("Invalid holiday response")
        holidays = []
        for record in records:
            holiday_date = date.fromisoformat(record["date"])
            name = record["name"]
            if holiday_date.year != year or not isinstance(name, str) or not name.strip():
                raise ValueError("Invalid holiday record")
            holidays.append({"date": holiday_date.isoformat(), "name": name.strip()})
        execute_write("""
            INSERT INTO public_holiday_cache (year, state_code, holidays, fetched_at)
            VALUES (%s, %s, %s::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (year, state_code) DO UPDATE
            SET holidays = EXCLUDED.holidays, fetched_at = EXCLUDED.fetched_at
        """, (year, state_code, json.dumps(holidays)))
        return holidays, None
    except (OSError, HTTPException, ValueError, KeyError, TypeError):
        if cached_row:
            return cached_row["holidays"], "Holiday service is unavailable; showing saved holiday data."
        return [], "Holiday service is unavailable; the calendar is still available."


@app.route("/calendar")
def calendar_page():
    today = local_today()
    year = request.args.get("year", today.year, type=int)
    if not 1 <= year <= 9999:
        year = today.year
    state_code = request.args.get("state", "KUL").upper()
    if state_code not in HOLIDAY_STATE_NAMES:
        state_code = "KUL"

    holidays, holiday_message = get_public_holidays(year, state_code)
    holidays_by_date = {}
    holidays_by_month = {month_number: [] for month_number in range(1, 13)}
    for holiday in holidays:
        holidays_by_date.setdefault(holiday["date"], []).append(holiday["name"])
        holidays_by_month[int(holiday["date"][5:7])].append(holiday)
    for month_holidays in holidays_by_month.values():
        month_holidays.sort(key=lambda holiday: holiday["date"])

    calendar = Calendar(firstweekday=0)
    months = [
        {
            "number": month_number,
            "name": month_name,
            "weeks": [
                [date(year, month_number, day) if day else None for day in week]
                for week in calendar.monthdayscalendar(year, month_number)
            ],
        }
        for month_number, month_name in enumerate(MONTH_NAMES, start=1)
    ]
    return render_template(
        "calendar.html",
        active_page="calendar",
        year=year,
        state_code=state_code,
        state_name=HOLIDAY_STATE_NAMES[state_code],
        states=HOLIDAY_STATES,
        months=months,
        today=today,
        holidays_by_date=holidays_by_date,
        holidays_by_month=holidays_by_month,
        holiday_count=len(holidays),
        holiday_message=holiday_message,
    )


def local_now():
    return datetime.now(LOCAL_TIMEZONE)


def local_today():
    return local_now().date()


def monthly_finances(day):
    """Compare recorded transactions with the separately planned monthly budget."""
    start = day.replace(day=1)
    end = start + timedelta(days=monthrange(start.year, start.month)[1])
    totals = fetch_all("""
        SELECT kind, category, SUM(amount) AS total
        FROM transactions WHERE occurred_on >= %s AND occurred_on < %s
        GROUP BY kind, category
    """, (start, end))
    income = sum((row["total"] for row in totals if row["kind"] == "income"), Decimal("0"))
    spending = sum((row["total"] for row in totals if row["kind"] == "expense"), Decimal("0"))
    spent_by_category = {row["category"]: row["total"] for row in totals if row["kind"] == "expense"}
    budgets = fetch_all("""
        SELECT income, savings, food, transport, bills, entertainment
        FROM budgets WHERE year = %s AND month = %s
    """, (start.year, start.month))
    budget = budgets[0] if budgets else None
    planned_expenses = sum((budget[field] for field in EXPENSE_FIELDS), Decimal("0")) if budget else None
    return {
        "income": income,
        "spending": spending,
        "balance": income - spending,
        "budget": budget,
        "planned_expenses": planned_expenses,
        "budget_left": planned_expenses - spending if budget else None,
        "categories": [
            {
                "name": category,
                "spent": spent_by_category.get(category, Decimal("0")),
                "planned": budget.get(category, Decimal("0")) if budget else None,
            }
            for category in TRANSACTION_CATEGORIES["expense"]
        ],
    }


@app.route("/dashboard")
def dashboard():
    today = local_today()
    stats = fetch_all("""
        SELECT COUNT(*) FILTER (WHERE NOT done) AS open_tasks,
               COUNT(*) FILTER (WHERE NOT done AND due_at < %s) AS overdue_tasks,
               (SELECT COUNT(*) FROM projects WHERE status IN ('Ongoing', 'In Review')) AS active_projects,
               (SELECT COUNT(*) FROM notes) AS note_count
        FROM tasks
    """, (today,))[0]
    due_tasks = fetch_all("""
        SELECT id, title, due_at, priority FROM tasks
        WHERE NOT done AND due_at < %s ORDER BY due_at, id DESC LIMIT 6
    """, (today + timedelta(days=1),))
    bills = fetch_all("""
        SELECT id, name, price, next_billing_date FROM subscriptions
        WHERE active AND next_billing_date BETWEEN %s AND %s
        ORDER BY next_billing_date, id DESC LIMIT 5
    """, (today, today + timedelta(days=30)))
    recent_logs = fetch_all("""
        SELECT id, title, entry_date, day_type FROM logbook_entries
        WHERE entry_date <= %s ORDER BY entry_date DESC LIMIT 3
    """, (today,))
    recent_notes = fetch_all("""
        SELECT id, title, pinned, updated_at FROM notes
        ORDER BY pinned DESC, updated_at DESC, id DESC LIMIT 3
    """)
    return render_template(
        "dashboard.html", active_page="dashboard", today=today,
        stats=stats, due_tasks=due_tasks, bills=bills,
        recent_logs=recent_logs, recent_notes=recent_notes,
        finances=monthly_finances(today),
    )


def render_notes(values=None, error=None, status=200):
    search = request.args.get("q", "").strip()[:200]
    pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    saved_notes = fetch_all("""
        SELECT n.id, n.title, n.content, n.pinned, n.project_id, n.task_id,
               n.created_at, n.updated_at, p.title AS project_title, t.title AS task_title
        FROM notes n LEFT JOIN projects p ON p.id = n.project_id
        LEFT JOIN tasks t ON t.id = n.task_id
        WHERE (%s = '' OR n.title ILIKE %s OR n.content ILIKE %s)
        ORDER BY n.pinned DESC, n.updated_at DESC, n.id DESC
    """, (search, pattern, pattern))
    if values is None:
        edit_id = request.args.get("edit", type=int)
        values = dict(fetch_one_or_404("SELECT * FROM notes WHERE id = %s", (edit_id,))) if edit_id is not None else {}
    return render_template(
        "notes.html", active_page="notes", notes=saved_notes,
        form_values=values, search=search, error=error,
        projects=fetch_all("SELECT id, title FROM projects ORDER BY title, id"),
        tasks=fetch_all("SELECT id, title FROM tasks ORDER BY done, id DESC"),
    ), status


@app.route("/notes")
def notes():
    return render_notes()


@app.route("/notes/save", methods=["POST"])
def save_note():
    values = form_values(("title", "content", "project_id", "task_id"))
    values.update(id=None, pinned=request.form.get("pinned") == "1")
    try:
        values["id"] = optional_form_id()
        if not values["title"] or not values["content"]:
            raise ValueError("Enter a title and note content.")
        if len(values["title"]) > 200 or len(values["content"]) > 20000:
            raise ValueError("Use up to 200 characters for the title and 20,000 for the note.")
        for field, query in (
            ("project_id", "SELECT id FROM projects WHERE id = %s"),
            ("task_id", "SELECT id FROM tasks WHERE id = %s"),
        ):
            if values[field]:
                link_id = int(values[field])
                if link_id < 1 or not fetch_all(query, (link_id,)):
                    raise ValueError("Choose an existing project or task to link.")
                values[field] = link_id
            else:
                values[field] = None
        params = (values["title"], values["content"], values["pinned"], values["project_id"], values["task_id"])
        if values["id"] is None:
            execute_write("""
                INSERT INTO notes (title, content, pinned, project_id, task_id)
                VALUES (%s, %s, %s, %s, %s)
            """, params)
        else:
            updated = execute_write("""
                UPDATE notes SET title = %s, content = %s, pinned = %s,
                    project_id = %s, task_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (*params, values["id"]))
            if updated == 0:
                abort(404)
    except (ValueError, psycopg2.errors.ForeignKeyViolation) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "The linked project or task was removed. Choose another link."
        return render_notes(values, message, 400)
    return redirect(url_for("notes", saved=1))


@app.route("/notes/pin/<int:note_id>", methods=["POST"])
def pin_note(note_id):
    execute_write_or_404("UPDATE notes SET pinned = NOT pinned WHERE id = %s", (note_id,))
    return redirect(url_for("notes", q=request.args.get("q", "")[:200]))


@app.route("/notes/delete/<int:note_id>", methods=["POST"])
def delete_note(note_id):
    execute_write_or_404("DELETE FROM notes WHERE id = %s", (note_id,))
    return redirect(url_for("notes", q=request.args.get("q", "")[:200]))


def selected_expense_month():
    try:
        month = date.fromisoformat(request.args.get("month", "") + "-01")
        if 2000 <= month.year <= 2200:
            return month
    except ValueError:
        pass
    return local_today().replace(day=1)


def render_expenses(values=None, error=None, status=200):
    month = selected_expense_month()
    end = month + timedelta(days=monthrange(month.year, month.month)[1])
    subscription_id = request.args.get("subscription", type=int)
    subscription = None
    if subscription_id is not None:
        subscription = fetch_one_or_404(
            "SELECT id, name FROM subscriptions WHERE id = %s", (subscription_id,)
        )
    entries = fetch_all("""
        SELECT t.id, t.title, t.kind, t.category, t.amount, t.occurred_on,
               t.description, t.subscription_id, t.subscription_due_on,
               s.name AS subscription_name
        FROM transactions t LEFT JOIN subscriptions s ON s.id = t.subscription_id
        WHERE t.occurred_on >= %s AND t.occurred_on < %s
          AND (%s IS NULL OR t.subscription_id = %s)
        ORDER BY t.occurred_on DESC, t.id DESC
    """, (month, end, subscription_id, subscription_id))
    if values is None:
        edit_id = request.args.get("edit", type=int)
        if edit_id is not None:
            values = dict(fetch_one_or_404("SELECT * FROM transactions WHERE id = %s", (edit_id,)))
            values["occurred_on"] = values["occurred_on"].isoformat()
        else:
            today = local_today()
            values = {
                "kind": "expense", "category": "food",
                "occurred_on": (today if today.replace(day=1) == month else month).isoformat(),
            }
    return render_template(
        "expenses.html", active_page="expenses", transactions=entries,
        selected_month=month.strftime("%Y-%m"), month_label=month.strftime("%B %Y"),
        finances=monthly_finances(month), categories=TRANSACTION_CATEGORIES,
        form_values=values, error=error, subscription=subscription,
    ), status


@app.route("/expenses")
def expenses():
    return render_expenses()


@app.route("/expenses/save", methods=["POST"])
def save_transaction():
    values = form_values(("title", "kind", "category", "amount", "occurred_on", "description"))
    values["id"] = None
    try:
        values["id"] = optional_form_id()
        if values["id"] is not None:
            existing = fetch_one_or_404(
                "SELECT subscription_id, subscription_due_on FROM transactions WHERE id = %s",
                (values["id"],),
            )
            values.update(existing)
            if values.get("subscription_due_on") and values["kind"] != "expense":
                raise ValueError("A subscription payment must remain an expense.")
        if not values["title"] or len(values["title"]) > 200 or len(values["description"]) > 2000:
            raise ValueError("Enter a title up to 200 characters and details up to 2,000 characters.")
        if values["kind"] not in TRANSACTION_CATEGORIES or values["category"] not in TRANSACTION_CATEGORIES[values["kind"]]:
            raise ValueError("Choose a valid transaction type and matching category.")
        try:
            amount = read_money(values["amount"], minimum=Decimal("0.01"))
            occurred_on = date.fromisoformat(values["occurred_on"])
        except ValueError as exc:
            raise ValueError("Enter a valid amount and date.") from exc
        if not 2000 <= occurred_on.year <= 2200:
            raise ValueError("Choose a date between 2000 and 2200.")
        params = (values["title"], values["kind"], values["category"], amount, occurred_on, values["description"])
        if values["id"] is None:
            execute_write("""
                INSERT INTO transactions (title, kind, category, amount, occurred_on, description)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, params)
        else:
            updated = execute_write("""
                UPDATE transactions SET title = %s, kind = %s, category = %s,
                    amount = %s, occurred_on = %s, description = %s,
                    updated_at = CURRENT_TIMESTAMP WHERE id = %s
            """, (*params, values["id"]))
            if updated == 0:
                abort(404)
    except ValueError as exc:
        return render_expenses(values, str(exc), 400)
    return redirect(url_for(
        "expenses", month=occurred_on.strftime("%Y-%m"), saved=1,
        subscription=request.args.get("subscription", type=int),
    ))


@app.route("/expenses/delete/<int:transaction_id>", methods=["POST"])
def delete_transaction(transaction_id):
    execute_write_or_404("DELETE FROM transactions WHERE id = %s", (transaction_id,))
    return redirect(url_for(
        "expenses", month=selected_expense_month().strftime("%Y-%m"),
        subscription=request.args.get("subscription", type=int),
    ))


@app.route("/")
def index():
    tasks = fetch_all("""
        SELECT id, title, description, due_at, priority, task_type,
               difficulty, created_at, done
        FROM tasks
        ORDER BY id DESC
    """)

    tasks_by_type = {task_type: [] for task_type in TASK_TYPES}
    for task in tasks:
        tasks_by_type[task["task_type"]].append(task)
    for grouped_tasks in tasks_by_type.values():
        grouped_tasks.sort(key=lambda task: (
            PRIORITY_LEVELS.index(task["priority"]),
            DIFFICULTY_LEVELS.index(task["difficulty"]),
            -task["id"],
        ))
    edit_id = request.args.get("edit", type=int)
    editing_task = next((task for task in tasks if task["id"] == edit_id), None)
    if edit_id is not None and editing_task is None:
        abort(404)

    return render_template(
        "index.html",
        tasks=tasks,
        task_sections=[
            (task_type, grouped_tasks)
            for task_type, grouped_tasks in tasks_by_type.items()
            if grouped_tasks
        ],
        minimum_due_at=local_now().strftime("%Y-%m-%dT%H:%M"),
        editing_task=editing_task,
        active_page="tasks",
    )


def read_task_form():
    """Validate the fields shared by task creation and editing."""
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    priority = request.form.get("priority", "Medium")
    difficulty = request.form.get("difficulty", "Medium")
    task_type = request.form.get("task_type", "Others")
    try:
        due_at = datetime.fromisoformat(request.form.get("due_at", ""))
        if due_at.tzinfo is not None:
            due_at = due_at.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Enter a valid due date and time.") from exc
    if not (
        title and description and priority in PRIORITY_LEVELS
        and difficulty in DIFFICULTY_LEVELS and task_type in TASK_TYPES
    ):
        raise ValueError("Enter valid task details.")
    return title, description, due_at, priority, difficulty, task_type


def invalid_task_response():
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return "Enter valid task details.", 400
    return redirect(url_for("index"))


@app.route("/add", methods=["POST"])
def add_task():
    try:
        task_values = read_task_form()
    except ValueError:
        return invalid_task_response()

    execute_write("""
        INSERT INTO tasks
            (title, description, due_at, priority, difficulty, task_type)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, task_values)
    return redirect(url_for("index"))


@app.route("/tasks/edit/<int:task_id>", methods=["POST"])
def edit_task(task_id):
    try:
        task_values = read_task_form()
    except ValueError:
        return invalid_task_response()

    updated = execute_write("""
        UPDATE tasks SET title = %s, description = %s, due_at = %s,
            priority = %s, difficulty = %s, task_type = %s
        WHERE id = %s
    """, (*task_values, task_id))
    if updated == 0:
        abort(404)
    return redirect(url_for("index"))


@app.route("/toggle/<int:task_id>", methods=["POST"])
def toggle_task(task_id):
    execute_write_or_404(
        "UPDATE tasks SET done = NOT done WHERE id = %s",
        (task_id,),
    )

    return redirect(url_for("index"))


@app.route("/delete/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    execute_write_or_404("DELETE FROM tasks WHERE id = %s", (task_id,))

    return redirect(url_for("index"))


def render_subscriptions(error=None, status=200):
    today = local_today()
    plans = fetch_all("""
        SELECT id, name, price, billing_cycle, next_billing_date,
               subscription_type, active
        FROM subscriptions
        ORDER BY active DESC, next_billing_date ASC, id DESC
    """)

    active_plans = [plan for plan in plans if plan["active"]]
    monthly_total = sum(
        (
            plan["price"] if plan["billing_cycle"] == "monthly"
            else plan["price"] / Decimal("12")
        )
        for plan in active_plans
    )
    upcoming = sum(
        1
        for plan in active_plans
        if 0 <= (plan["next_billing_date"] - today).days <= 30
    )

    payment_id = request.args.get("pay", type=int)
    payment_plan = next((plan for plan in plans if plan["id"] == payment_id), None)
    if payment_id is not None and payment_plan is None:
        abort(404)

    return render_template(
        "subscriptions.html",
        subscriptions=plans,
        active_count=len(active_plans),
        monthly_total=monthly_total,
        upcoming=upcoming,
        today=today.isoformat(),
        active_page="subscriptions",
        payment_plan=payment_plan,
        error=error,
    ), status


@app.route("/subscription")
@app.route("/subscriptions")
def subscriptions():
    return render_subscriptions()


def next_subscription_billing_date(due_on, billing_cycle, billing_day=None):
    """Advance one cycle, clamping dates to the last day of the next period."""
    if billing_cycle == "yearly":
        year, month = due_on.year + 1, due_on.month
    else:
        year = due_on.year + (due_on.month == 12)
        month = due_on.month % 12 + 1
    if year > 2200:
        raise ValueError("The next billing date must be in 2200 or earlier.")
    return date(year, month, min(billing_day or due_on.day, monthrange(year, month)[1]))


def record_subscription_payment(subscription_id, due_on, paid_on):
    """Record one bill and advance its schedule together; reject stale bill forms."""
    with database_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM subscriptions WHERE id = %s FOR UPDATE", (subscription_id,))
        plan = cursor.fetchone()
        if plan is None:
            abort(404)
        if plan["next_billing_date"] != due_on:
            return False
        if not plan["active"]:
            raise ValueError("Resume this subscription before recording a payment.")
        if plan["price"] <= 0:
            raise ValueError("Free subscriptions do not need an expense recorded.")
        billing_day = plan.get("billing_day") or due_on.day
        next_due = next_subscription_billing_date(due_on, plan["billing_cycle"], billing_day)
        cursor.execute("""
            INSERT INTO transactions
                (title, kind, category, amount, occurred_on, description,
                 subscription_id, subscription_due_on)
            VALUES (%s, 'expense', 'bills', %s, %s, %s, %s, %s)
        """, (
            plan["name"][:200], plan["price"], paid_on,
            f"{plan['billing_cycle'].title()} subscription bill due {due_on.isoformat()}.",
            subscription_id, due_on,
        ))
        cursor.execute(
            "UPDATE subscriptions SET next_billing_date = %s, billing_day = %s WHERE id = %s",
            (next_due, billing_day, subscription_id),
        )
    return True


@app.route("/subscriptions/pay/<int:subscription_id>", methods=["POST"])
def pay_subscription(subscription_id):
    try:
        try:
            due_on = date.fromisoformat(request.form.get("due_on", ""))
            paid_on = date.fromisoformat(request.form.get("paid_on", ""))
        except ValueError as exc:
            raise ValueError("Enter a valid billing date and payment date.") from exc
        if not 2000 <= due_on.year <= 2200:
            raise ValueError("Choose a billing date between 2000 and 2200.")
        if not date(2000, 1, 1) <= paid_on <= min(local_today(), date(2200, 12, 31)):
            raise ValueError("Choose a payment date from 2000 through today, up to 2200.")
        recorded = record_subscription_payment(subscription_id, due_on, paid_on)
    except ValueError as exc:
        return render_subscriptions(str(exc), 400)
    except psycopg2.errors.UniqueViolation:
        recorded = False
    if not recorded:
        return render_subscriptions(
            "This bill was already recorded or its billing date changed. Open the current bill to continue.",
            409,
        )
    return redirect(url_for("subscriptions", saved=1, paid=1))


@app.route("/subscriptions/add", methods=["POST"])
def add_subscription():
    name = request.form.get("name", "").strip()
    billing_cycle = request.form.get("billing_cycle", "monthly")
    subscription_type = request.form.get("subscription_type", "Others")

    try:
        price = read_money(request.form.get("price", ""), maximum=MAX_SUBSCRIPTION_PRICE)
        next_billing_date = date.fromisoformat(
            request.form.get("next_billing_date", "")
        )
    except ValueError:
        return redirect(url_for("subscriptions"))

    if (
        name
        and 2000 <= next_billing_date.year <= 2200
        and billing_cycle in {"monthly", "yearly"}
        and subscription_type in ITEM_TYPE_VALUES
    ):
        execute_write(
            """
            INSERT INTO subscriptions
                (name, price, billing_cycle, next_billing_date,
                 subscription_type)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (name, price, billing_cycle, next_billing_date, subscription_type),
        )
        return redirect(url_for("subscriptions", saved=1))

    return redirect(url_for("subscriptions"))


@app.route("/subscriptions/toggle/<int:subscription_id>", methods=["POST"])
def toggle_subscription(subscription_id):
    execute_write_or_404(
        "UPDATE subscriptions SET active = NOT active WHERE id = %s",
        (subscription_id,),
    )

    return redirect(url_for("subscriptions"))


@app.route("/subscriptions/delete/<int:subscription_id>", methods=["POST"])
def delete_subscription(subscription_id):
    execute_write_or_404(
        "DELETE FROM subscriptions WHERE id = %s",
        (subscription_id,),
    )

    return redirect(url_for("subscriptions"))


@app.route("/bookmarks")
def bookmarks():
    saved_bookmarks = fetch_all("""
        SELECT id, title, url, bookmark_type, created_at
        FROM bookmarks
        ORDER BY created_at DESC, id DESC
    """)

    used_types = {bookmark["bookmark_type"] for bookmark in saved_bookmarks}

    return render_template(
        "bookmarks.html",
        bookmarks=saved_bookmarks,
        type_count=len(used_types),
        active_page="bookmarks",
    )


@app.route("/api")
def api_page():
    return render_template(
        "api.html", services=API_SERVICES, live_slugs=frozenset(SERVICE_HANDLERS), active_page="api"
    )


@app.route("/api/services/<slug>/request", methods=["POST"])
def request_api_service(slug):
    service = API_SERVICE_BY_SLUG.get(slug)
    if service is None:
        return jsonify(error="Unknown API service."), 404

    values = {}
    for field in service["fields"]:
        value = request.form.get(field["name"], "").strip()
        if not value:
            return jsonify(error=f"Enter {field['label'].lower()}."), 400
        if len(value) > 200 or (field["type"] == "select" and value not in field["options"]):
            return jsonify(error=f"Enter a valid {field['label'].lower()}."), 400
        values[field["name"]] = value

    data, status = call_api_service(service, values)
    response = jsonify(data)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/bookmarks/add", methods=["POST"])
def add_bookmark():
    title = request.form.get("title", "").strip()
    bookmark_url = normalize_url(request.form.get("url", ""))
    bookmark_type = request.form.get("bookmark_type", "Others")

    if title and bookmark_url and bookmark_type in ITEM_TYPE_VALUES:
        execute_write(
            """
            INSERT INTO bookmarks (title, url, bookmark_type)
            VALUES (%s, %s, %s)
            """,
            (title, bookmark_url, bookmark_type),
        )
        return redirect(url_for("bookmarks", saved=1))

    return redirect(url_for("bookmarks"))


@app.route("/bookmarks/delete/<int:bookmark_id>", methods=["POST"])
def delete_bookmark(bookmark_id):
    execute_write_or_404("DELETE FROM bookmarks WHERE id = %s", (bookmark_id,))

    return redirect(url_for("bookmarks"))


@app.route("/budgets")
def budgets():
    today = local_today()
    budget_rows = fetch_all("""
        SELECT id, year, month, income, savings, food, transport,
               bills, entertainment, updated_at
        FROM budgets
        ORDER BY year DESC, month ASC
    """)

    current_year = today.year
    year_sections = build_year_sections(budget_rows, current_year)

    current_section = next(
        section for section in year_sections if section["year"] == current_year
    )

    return render_template(
        "budgets.html",
        year_sections=year_sections,
        current_year=current_year,
        current_month=today.month,
        current_total=current_section["total"],
        current_expenses=current_section["total_expenses"],
        current_remaining=current_section["total_remaining"],
        current_planned_count=current_section["planned_count"],
        active_page="budgets",
    )


@app.route("/budgets/set", methods=["POST"])
def set_budget():
    try:
        year = int(request.form.get("year", ""))
        month = int(request.form.get("month", ""))
        values = {
            field: read_money(request.form.get(field, ""))
            for field in BUDGET_FIELDS
        }
    except ValueError:
        return redirect(url_for("budgets"))

    if 2000 <= year <= 2200 and 1 <= month <= 12:
        execute_write(
            """
            INSERT INTO budgets (
                year, month, income, savings, food,
                transport, bills, entertainment
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (year, month)
            DO UPDATE SET income = EXCLUDED.income,
                          savings = EXCLUDED.savings,
                          food = EXCLUDED.food,
                          transport = EXCLUDED.transport,
                          bills = EXCLUDED.bills,
                          entertainment = EXCLUDED.entertainment,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (year, month, *(values[field] for field in BUDGET_FIELDS)),
        )
        return redirect(url_for("budgets", saved=1))

    return redirect(url_for("budgets"))


@app.route("/budgets/delete/<int:budget_id>", methods=["POST"])
def delete_budget(budget_id):
    execute_write_or_404("DELETE FROM budgets WHERE id = %s", (budget_id,))

    return redirect(url_for("budgets"))


def build_logbook_months(logbook_rows, year):
    """Build all days of the selected year, including weekends and leap days."""
    entries = {row["entry_date"]: row for row in logbook_rows}
    months = []
    for number, name in enumerate(MONTH_NAMES, 1):
        days = []
        for day_number in range(1, monthrange(year, number)[1] + 1):
            day = date(year, number, day_number)
            days.append({"date": day, "entry": entries.get(day)})
        months.append({
            "number": number,
            "name": name,
            "days": days,
            "count": sum(day["entry"] is not None for day in days),
        })
    return months


def get_logbook_images(entry_id):
    """Fetch image metadata without loading the stored image bytes."""
    return fetch_all(
        """
        SELECT id, filename, mime_type, octet_length(data) AS size_bytes
        FROM logbook_images WHERE entry_id = %s ORDER BY id
        """,
        (entry_id,),
    )


def initial_logbook_values(today):
    """Load an entry for editing or prefill the requested date for a new log."""
    edit_id = request.args.get("edit", type=int)
    if edit_id is not None:
        editing = dict(fetch_one_or_404("""
            SELECT id, entry_date, title, location, description, day_type,
                   created_at, updated_at
            FROM logbook_entries WHERE id = %s
        """, (edit_id,)))
        return {**editing, "entry_date": editing["entry_date"].isoformat()}

    try:
        initial_date = date.fromisoformat(request.args.get("date", today.isoformat()))
    except ValueError:
        initial_date = today
    return {"entry_date": initial_date.isoformat(), "day_type": "Work"}


def render_logbook(form_values=None, error=None, status=200):
    today = local_today()
    if form_values is None:
        form_values = initial_logbook_values(today)

    try:
        form_date = date.fromisoformat(form_values.get("entry_date", ""))
    except ValueError:
        form_date = today
    selected_year = request.args.get("year", form_date.year, type=int)
    if not 1 <= selected_year <= 9999:
        selected_year = today.year
    selected_month = request.args.get("month", form_date.month, type=int)
    year_rows = fetch_all(
        "SELECT DISTINCT EXTRACT(YEAR FROM entry_date)::int AS year FROM logbook_entries"
    )
    years = {int(row["year"]) for row in year_rows}
    years.update((today.year, selected_year))
    rows = fetch_all("""
        SELECT e.id, e.entry_date, e.title, e.day_type, COUNT(i.id) AS image_count
        FROM logbook_entries e LEFT JOIN logbook_images i ON i.entry_id = e.id
        WHERE e.entry_date BETWEEN %s AND %s
        GROUP BY e.id ORDER BY e.entry_date
    """, (date(selected_year, 1, 1), date(selected_year, 12, 31)))
    entry_id = form_values.get("id")
    existing_images = get_logbook_images(entry_id) if entry_id else []
    return render_template(
        "logbook.html",
        active_page="logbook",
        today=today,
        years=sorted(years, reverse=True),
        selected_year=selected_year,
        selected_month=selected_month,
        months=build_logbook_months(rows, selected_year),
        entry_count=len(rows),
        image_count=sum(row["image_count"] for row in rows),
        day_types=LOGBOOK_DAY_TYPES,
        form_values=form_values,
        existing_images=existing_images,
        max_images=MAX_LOGBOOK_IMAGES,
        max_image_bytes=MAX_IMAGE_BYTES,
        max_image_pixels=MAX_IMAGE_PIXELS,
        error=error,
    ), status


@app.route("/logbook")
def logbook():
    return render_logbook()


@app.route("/logbook/day/<entry_date>")
def logbook_day(entry_date):
    try:
        day = date.fromisoformat(entry_date)
    except ValueError:
        abort(404)
    rows = fetch_all("""
        SELECT id, entry_date, title, location, description, day_type,
               created_at, updated_at
        FROM logbook_entries WHERE entry_date = %s
    """, (day,))
    if not rows:
        return jsonify(entry=None)
    entry = dict(rows[0])
    entry["entry_date"] = day.isoformat()
    entry["edit_url"] = url_for("logbook", edit=entry["id"])
    entry["images"] = [
        {
            "filename": row["filename"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "url": url_for("logbook_image", image_id=row["id"]),
            "download_url": url_for("logbook_image", image_id=row["id"], download=1),
        }
        for row in get_logbook_images(entry["id"])
    ]
    return jsonify(entry=entry)


def read_logbook_images():
    uploads = uploaded_files("images")
    if len(uploads) > MAX_LOGBOOK_IMAGES:
        raise ValueError("Choose at most 10 images per entry.")
    return [read_validated_image(upload, "Each image") for upload in uploads]


def validate_logbook_form(values):
    """Validate a log entry and read its attachment changes."""
    entry_id = optional_form_id()
    values["id"] = entry_id
    entry_date = date.fromisoformat(values["entry_date"])
    removed = form_ids("remove_images")
    if not values["title"] or not values["description"] or not values["location"]:
        raise ValueError("Enter a title, location, and description.")
    if (
        len(values["title"]) > 200
        or len(values["location"]) > 200
        or len(values["description"]) > 20000
    ):
        raise ValueError(
            "Use up to 200 characters for title and location, "
            "and 20,000 for the description."
        )
    if values["day_type"] not in LOGBOOK_DAY_TYPES:
        raise ValueError("Choose Work, Holiday, MeTIME, or Family.")
    images = read_logbook_images()
    return entry_id, entry_date, removed, images


def save_logbook_entry(entry_id, entry_date, values, removed, images):
    """Save the entry and its image changes in one transaction."""
    entry_values = (
        values["title"], values["location"], entry_date,
        values["description"], values["day_type"],
    )
    with database_connection() as conn:
        with conn.cursor() as cursor:
            if entry_id is not None:
                cursor.execute(
                    "SELECT id FROM logbook_entries WHERE id = %s FOR UPDATE",
                    (entry_id,),
                )
                if cursor.fetchone() is None:
                    abort(404)
                cursor.execute(
                    "DELETE FROM logbook_images WHERE entry_id = %s AND id = ANY(%s)",
                    (entry_id, removed),
                )
                cursor.execute(
                    "SELECT COUNT(*) FROM logbook_images WHERE entry_id = %s",
                    (entry_id,),
                )
                if cursor.fetchone()[0] + len(images) > MAX_LOGBOOK_IMAGES:
                    raise ValueError(
                        "An entry can have up to 10 images. "
                        "Remove existing images before adding more."
                    )
                cursor.execute("""
                    UPDATE logbook_entries SET title = %s, location = %s,
                        entry_date = %s, description = %s, day_type = %s,
                        updated_at = CURRENT_TIMESTAMP WHERE id = %s
                """, (*entry_values, entry_id))
            else:
                cursor.execute("""
                    INSERT INTO logbook_entries (title, location, entry_date, description, day_type)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                """, entry_values)
                entry_id = cursor.fetchone()[0]
            for filename, mime_type, data in images:
                cursor.execute("""
                    INSERT INTO logbook_images (entry_id, filename, mime_type, data)
                    VALUES (%s, %s, %s, %s)
                """, (entry_id, filename, mime_type, psycopg2.Binary(data)))


@app.route("/logbook/save", methods=["POST"])
def save_logbook():
    values = form_values(("title", "location", "entry_date", "description", "day_type"))
    try:
        entry_id, entry_date, removed, images = validate_logbook_form(values)
        save_logbook_entry(entry_id, entry_date, values, removed, images)
    except psycopg2.errors.UniqueViolation:
        return render_logbook(
            values,
            "This date already has a log. Open that day and choose Edit log to update it.",
            409,
        )
    except ValueError as exc:
        return render_logbook(values, str(exc), 400)
    return redirect(url_for(
        "logbook", year=entry_date.year, month=entry_date.month, saved=1,
    ))


@app.route("/logbook/images/<int:image_id>")
def logbook_image(image_id):
    picture = fetch_one_or_404(
        "SELECT filename, mime_type, data FROM logbook_images WHERE id = %s",
        (image_id,),
    )
    return send_stored_file(
        picture["data"], picture["filename"], picture["mime_type"],
        as_attachment=request.args.get("download") == "1",
    )


def render_projects(form_values=None, error=None, status=200):
    projects = [
        dict(row)
        for row in fetch_all("""
            SELECT id, title, description, status, github_url, website_url,
                   image_data IS NOT NULL AS has_image, created_at, updated_at
            FROM projects ORDER BY created_at DESC, id DESC
        """)
    ]
    projects_by_id = {project["id"]: project for project in projects}
    if form_values is None:
        edit_id = request.args.get("edit", type=int)
        if edit_id is not None:
            if edit_id not in projects_by_id:
                abort(404)
            form_values = dict(projects_by_id[edit_id])
        else:
            form_values = {"status": "Ongoing"}

    files_by_project = {project["id"]: [] for project in projects}
    for row in fetch_all("""
        SELECT id, project_id, filename
        FROM project_files ORDER BY id
    """):
        files_by_project[row["project_id"]].append(row)
    for project in projects:
        project["files"] = files_by_project[project["id"]]

    edit_id = form_values.get("id")
    if edit_id in projects_by_id and "has_image" not in form_values:
        form_values = {**form_values, "has_image": projects_by_id[edit_id]["has_image"]}

    return render_template(
        "projects.html",
        active_page="projects",
        projects=projects,
        form_values=form_values,
        existing_files=files_by_project.get(edit_id, []),
        status_options=PROJECT_STATUSES if edit_id else NEW_PROJECT_STATUSES,
        max_project_files=MAX_PROJECT_FILES,
        max_project_file_bytes=MAX_PROJECT_FILE_BYTES,
        max_image_bytes=MAX_IMAGE_BYTES,
        error=error,
    ), status


@app.route("/projects")
def projects():
    return render_projects()


def read_project_image():
    upload = request.files.get("main_image")
    if not upload or not upload.filename:
        return None
    return read_validated_image(upload, "The main image")


def read_project_files():
    uploads = uploaded_files("documents")
    if len(uploads) > MAX_PROJECT_FILES:
        raise ValueError("A project can have up to 10 files.")
    files = []
    for upload in uploads:
        data = read_limited_upload(
            upload, MAX_PROJECT_FILE_BYTES, "Each project file must be 20 MB or smaller."
        )
        filename = secure_filename(upload.filename)[:200]
        if not filename:
            raise ValueError("Each project file needs a valid filename.")
        files.append((filename, data))
    return files


def validate_project_form(values):
    """Validate a project and read its attachment changes."""
    project_id = optional_form_id()
    values["id"] = project_id
    if not values["title"] or not values["description"]:
        raise ValueError("Enter a title and description.")
    if len(values["title"]) > 200 or len(values["description"]) > 20000:
        raise ValueError(
            "Use up to 200 characters for the title and 20,000 for the description."
        )
    allowed_statuses = PROJECT_STATUSES if project_id else NEW_PROJECT_STATUSES
    if values["status"] not in allowed_statuses:
        raise ValueError("Choose a valid project status.")
    for field in ("github_url", "website_url"):
        if values[field]:
            values[field] = normalize_url(values[field])
            if not values[field] or len(values[field]) > 2000:
                raise ValueError(
                    "Enter valid HTTP or HTTPS project links, up to 2,000 characters."
                )
    removed = form_ids("remove_files")
    image = read_project_image()
    files = read_project_files()
    remove_image = request.form.get("remove_image") == "1"
    return project_id, removed, image, files, remove_image


def save_project_record(project_id, values, removed, image, files, remove_image):
    """Save project details and attachment changes in one transaction."""
    project_values = (
        values["title"],
        values["description"],
        values["status"],
        values["github_url"] or None,
        values["website_url"] or None,
    )
    with database_connection() as conn:
        with conn.cursor() as cursor:
            if project_id is not None:
                cursor.execute(
                    "SELECT id FROM projects WHERE id = %s FOR UPDATE",
                    (project_id,),
                )
                if cursor.fetchone() is None:
                    abort(404)
                cursor.execute(
                    "DELETE FROM project_files WHERE project_id = %s AND id = ANY(%s)",
                    (project_id, removed),
                )
                cursor.execute(
                    "SELECT COUNT(*) FROM project_files WHERE project_id = %s",
                    (project_id,),
                )
                if cursor.fetchone()[0] + len(files) > MAX_PROJECT_FILES:
                    raise ValueError(
                        "A project can have up to 10 files. "
                        "Remove saved files before adding more."
                    )
                cursor.execute(
                    """
                    UPDATE projects SET title = %s, description = %s, status = %s,
                        github_url = %s, website_url = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (*project_values, project_id),
                )
                if image:
                    cursor.execute(
                        """
                        UPDATE projects SET image_filename = %s,
                            image_mime_type = %s, image_data = %s
                        WHERE id = %s
                        """,
                        (image[0], image[1], psycopg2.Binary(image[2]), project_id),
                    )
                elif remove_image:
                    cursor.execute(
                        """
                        UPDATE projects SET image_filename = NULL,
                            image_mime_type = NULL, image_data = NULL
                        WHERE id = %s
                        """,
                        (project_id,),
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO projects (
                        title, description, status, github_url, website_url,
                        image_filename, image_mime_type, image_data
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        *project_values,
                        image[0] if image else None,
                        image[1] if image else None,
                        psycopg2.Binary(image[2]) if image else None,
                    ),
                )
                project_id = cursor.fetchone()[0]
            for filename, data in files:
                cursor.execute(
                    """
                    INSERT INTO project_files (project_id, filename, data)
                    VALUES (%s, %s, %s)
                    """,
                    (project_id, filename, psycopg2.Binary(data)),
                )


@app.route("/projects/save", methods=["POST"])
def save_project():
    values = form_values(("title", "description", "status", "github_url", "website_url"))
    try:
        project_id, removed, image, files, remove_image = validate_project_form(values)
        save_project_record(project_id, values, removed, image, files, remove_image)
    except ValueError as exc:
        return render_projects(values, str(exc), 400)
    return redirect(url_for("projects", saved=1))


@app.route("/projects/images/<int:project_id>")
def project_image(project_id):
    picture = fetch_one_or_404(
        "SELECT image_filename, image_mime_type, image_data FROM projects WHERE id = %s",
        (project_id,),
    )
    if picture["image_data"] is None:
        abort(404)
    return send_stored_file(
        picture["image_data"], picture["image_filename"], picture["image_mime_type"],
    )


@app.route("/projects/files/<int:file_id>")
def project_file(file_id):
    document = fetch_one_or_404(
        "SELECT filename, data FROM project_files WHERE id = %s", (file_id,)
    )
    return send_stored_file(
        document["data"], document["filename"], "application/octet-stream",
        as_attachment=True,
    )


def render_file_formats(tool="images-to-pdf", error=None, status=200):
    return render_template(
        "file_formats.html", active_page="file_formats", tools=CONVERSION_TOOLS,
        selected_tool=tool, selected=CONVERSION_TOOLS[tool], dpi_values=PDF_DPI_VALUES,
        error=error,
    ), status


@app.route("/file-formats")
def file_formats():
    tool = request.args.get("tool", "images-to-pdf")
    if tool not in CONVERSION_TOOLS:
        abort(404)
    return render_file_formats(tool)


@app.route("/file-formats/convert", methods=["POST"])
def convert_file_format():
    tool = request.form.get("conversion", "images-to-pdf")
    if tool not in CONVERSION_TOOLS:
        return render_file_formats(error="Choose a supported conversion.", status=400)
    try:
        files = uploaded_files("files")
        if tool == "images-to-pdf":
            data, filename, mimetype = images_to_pdf(files)
        else:
            if len(files) != 1:
                raise ValueError("Choose one file to convert.")
            if tool == "office-to-pdf":
                data, filename, mimetype = office_to_pdf(files[0])
            else:
                try:
                    dpi = int(request.form.get("dpi", "150"))
                    first_page = int(request.form.get("first_page", "1"))
                    last_page = int(request.form["last_page"]) if request.form.get("last_page") else None
                except ValueError as exc:
                    raise ValueError("Enter valid page numbers and a supported resolution.") from exc
                data, filename, mimetype = pdf_to_images(
                    files[0], request.form.get("image_format", "png"), dpi, first_page, last_page,
                )
    except ValueError as exc:
        return render_file_formats(tool, str(exc), 400)
    except ConversionUnavailable as exc:
        return render_file_formats(tool, str(exc), 503)
    return send_stored_file(data, filename, mimetype, as_attachment=True)


@app.errorhandler(413)
def upload_too_large(error):
    if request.path.startswith("/file-formats"):
        return render_file_formats(
            error="The complete upload must be 55 MB or smaller. Use smaller files or fewer images.",
            status=413,
        )
    is_project = request.path.startswith("/projects")
    return render_template(
        "upload_error.html",
        active_page="projects" if is_project else "logbook",
        upload_section="Projects" if is_project else "Logbook",
    ), 413


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    app.run(host="0.0.0.0", port=5000)
